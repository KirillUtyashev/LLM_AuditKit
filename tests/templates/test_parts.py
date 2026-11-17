"""Structured resume parts preserve prose and researcher-controlled slots."""

import asyncio
from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest
from pydantic import ValidationError

from llm_auditkit.inference import InferenceOrchestrator, InferenceResult, StructuredResponseFormat
from llm_auditkit.templates import (
    TemplateGenerator, TemplateStore, TemplateStoreError,
    TemplateGenerationConfigurationError, TemplateResponseParseError,
    load_template_generation_run_config,
)
from llm_auditkit.templates.identity import build_generation_fingerprint
from llm_auditkit.templates.parsing import parse_template_contents
from llm_auditkit.templates.parts import render_template_parts, template_parts_model
from llm_auditkit.templates.planning import build_template_requests
from llm_auditkit.templates.prompts import build_template_prompt
from llm_auditkit.templates.validation import validate_template_generation_config

from .helpers import config, dataset


def payload(count=2, names=("name", "address")):
    return {"templates": [
        {"parts": [{"text": f"Resume {i}\n"}, *[
            part for name in names for part in ({"field": name}, {"text": "\n"})
        ], {"text": "Clerk: maintained files and correspondence."}]}
        for i in range(count)
    ]}


def parts_config(**kwargs):
    generation = replace(config(**kwargs), response_mode="parts")
    generation.inference.models[0].provider = "openai"
    return generation


@pytest.mark.parametrize("count", [1, 2, 5])
def test_dynamic_schema_preserves_prose_and_renders_only_configured_slots(count):
    names = ("first_name", "qualification", "school")
    content = payload(count, names)
    schema = template_parts_model(count, names)
    schema.model_validate(content)
    assert schema.model_json_schema()["additionalProperties"] is False
    for definition in schema.model_json_schema()["$defs"].values():
        assert definition["additionalProperties"] is False
    rendered = render_template_parts(content, count, list(names))
    assert len(rendered) == count
    assert rendered[0] == (
        "Resume 0\n{{first_name}}\n{{qualification}}\n{{school}}\n"
        "Clerk: maintained files and correspondence."
    )
    assert content == payload(count, names)  # Rendering never modifies responses.


@pytest.mark.parametrize("part", [
    {"field": "age"}, {"field": "name", "value": "Invented Person"},
    {"field": "name", "text": "Invented Person"}, {}, {"text": 12}, {"text": ""},
    {"text": "{{age}}"}, {"text": "{{name}}"}, {"text": "malformed {{ token"},
    {"text": "bad\x00text"},
])
def test_invalid_or_unconfigured_parts_fail_without_silent_repair(part):
    content = payload()
    content["templates"][0]["parts"].append(part)
    generation = parts_config()
    result = InferenceResult("r", "m", "raw", {}, structured_content=content)
    with pytest.raises(TemplateResponseParseError):
        parse_template_contents(result, generation)


def test_required_reference_cannot_be_satisfied_by_literal_text():
    content = payload()
    content["templates"][0]["parts"] = [{"field": "name"}, {"text": "An address"}]
    with pytest.raises(TemplateResponseParseError, match="missing required fields: address"):
        render_template_parts(content, 2, ["name", "address"])


@pytest.mark.parametrize("change", ["extra_root", "extra_template", "count", "no_parts", "duplicate"])
def test_output_shape_and_distinctness_are_still_validated(change):
    content = payload()
    if change == "extra_root":
        content["other"] = "unsupported"
    elif change == "extra_template":
        content["templates"][0]["name"] = "unsupported"
    elif change == "count":
        content["templates"].pop()
    elif change == "no_parts":
        content["templates"][0]["parts"] = []
    else:
        content["templates"][1] = deepcopy(content["templates"][0])
    with pytest.raises(TemplateResponseParseError):
        parse_template_contents(
            InferenceResult("r", "m", "raw", {}, structured_content=content), parts_config(),
        )


def test_planned_requests_include_schema_instructions_and_separate_identity():
    generation = parts_config()
    request, = build_template_requests(dataset(1), generation)
    assert isinstance(request.response_format, StructuredResponseFormat)
    request.response_format.response_model.model_validate(payload())
    assert "Do not supply values" in request.prompt
    assert "field parts" in request.prompt
    assert "Synthetic job 1" in request.prompt
    assert request.prompt == build_template_prompt(dataset(1).iloc[0].to_dict(), generation)
    assert build_generation_fingerprint(generation) != build_generation_fingerprint(
        replace(generation, response_mode="text")
    )
    with pytest.raises(ValidationError):
        request.response_format.response_model.model_validate({"templates": []})


@pytest.mark.parametrize("mode", [None, True, "invalid"])
def test_invalid_mode_fails_before_inference(mode):
    with pytest.raises(TemplateGenerationConfigurationError, match="response_mode"):
        validate_template_generation_config(replace(config(), response_mode=mode))


def test_unsupported_provider_rejected_instead_of_prompt_only_fallback():
    with pytest.raises(TemplateGenerationConfigurationError, match="openai"):
        validate_template_generation_config(replace(config(), response_mode="parts"))


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_generation_checkpoints_and_resumes_parts_without_changing_output_shape(tmp_path, mode):
    class Adapter:
        calls = 0

        def render_batch(self, requests, models):
            raise AssertionError("not needed")

        def execute_batch(self, requests, models):
            self.calls += 1
            return [InferenceResult(r.request_id, r.model_config_id, "raw", {},
                                    structured_content=payload()) for r in requests]

        async def execute_batch_async(self, requests, models):
            return self.execute_batch(requests, models)

    adapter = Adapter()
    store = TemplateStore(tmp_path / "templates.csv")
    generator = TemplateGenerator(InferenceOrchestrator(adapter), store)
    generation = parts_config()
    source = dataset(3)

    def execute():
        return (generator.generate(source, generation) if mode == "sync" else
                asyncio.run(generator.generate_async(source, generation)))

    output = execute()
    assert output["template_generation_error_type"].isna().all()
    assert output["template_1"].str.contains("{{name}}", regex=False).all()
    assert adapter.calls == 2
    saved = store.output_path.read_bytes()
    pd.testing.assert_frame_equal(output, execute())
    assert adapter.calls == 2
    assert store.output_path.read_bytes() == saved
    with pytest.raises(TemplateStoreError):
        store.initialize(source, replace(generation, response_mode="text"))


def test_manual_workflow_opts_into_parts_with_fresh_checkpoint():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    run = load_template_generation_run_config(root / "tests/manual/newspaper_pipeline/templates.yaml")
    assert run.generation_config.response_mode == "parts"
    assert run.output_path.name == "templates-gpt55-medium-parts.csv"


def test_literal_tokens_cannot_be_smuggled_across_adjacent_text_parts():
    content = payload()
    content["templates"][0]["parts"] += [{"text": "{"}, {"text": "{name}"}, {"text": "}"}]
    with pytest.raises(TemplateResponseParseError, match="literal text"):
        render_template_parts(content, 2, ["name", "address"])


def test_rendered_parts_feed_population_without_model_supplied_values():
    from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator
    rendered = render_template_parts(payload(), 2, ["name", "address"])
    templates = pd.DataFrame([{
        "scenario_id": "scenario", "Text": "Synthetic office job",
        "template_1": rendered[0], "template_2": rendered[1],
    }])
    assignments = pd.DataFrame([
        {"scenario_id": "scenario", "template_id": "a", "candidate_id": "candidate-a",
         "candidate_order": 2, "name": "Alex", "address": "First Street"},
        {"scenario_id": "scenario", "template_id": "b", "candidate_id": "candidate-b",
         "candidate_order": 1, "name": "Casey", "address": "Second Street"},
    ])
    populated = TemplatePopulator().populate(templates, assignments, TemplatePopulationConfig(
        template_columns={"a": "template_1", "b": "template_2"},
        placeholder_columns={"name": "name", "address": "address"},
    ))
    assert populated.loc[0, "resume_1"] == rendered[1].replace("{{name}}", "Casey").replace("{{address}}", "Second Street")
    assert populated.loc[0, "resume_2"] == rendered[0].replace("{{name}}", "Alex").replace("{{address}}", "First Street")
