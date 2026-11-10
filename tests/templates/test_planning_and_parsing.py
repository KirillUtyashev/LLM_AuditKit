"""Request construction and normalized template-result parsing tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from llm_auditkit.inference import InferenceError, InferenceResult
from llm_auditkit.templates import (
    TemplateGenerationIdentityError,
    TemplateResponseParseError,
    TemplateResultAssociationError,
    build_template_request_id,
)
from llm_auditkit.templates.identity import build_generation_fingerprint
from llm_auditkit.templates.parsing import parse_template_batch, parse_template_result
from llm_auditkit.templates.planning import build_template_requests
from llm_auditkit.templates.prompts import (
    build_template_prompt,
    build_template_system_prompt,
)

from .helpers import config, dataset, template_text


def _result(
    scenario_id: str,
    *,
    generation=None,
    structured_content: dict[str, object] | None = None,
    error: InferenceError | None = None,
) -> InferenceResult:
    generation = generation or config()
    fingerprint = build_generation_fingerprint(generation)
    if structured_content is None and error is None:
        structured_content = {
            f"template_{position}": template_text(scenario_id, position)
            for position in range(1, generation.templates_per_scenario + 1)
        }
    return InferenceResult(
        request_id=build_template_request_id(scenario_id, fingerprint),
        model_config_id=generation.model_config_id,
        content=None if error is not None else "structured templates",
        metadata={
            "scenario_id": scenario_id,
            "generation_fingerprint": fingerprint,
        },
        structured_content=structured_content,
        error=error,
    )


def test_prompts_render_context_and_preserve_canonical_tokens() -> None:
    generation = config()
    row = dataset(1).to_dict(orient="records")[0]

    prompt = build_template_prompt(row, generation)
    system_prompt = build_template_system_prompt(row, generation)

    assert "Synthetic job 1" in prompt
    assert "Toronto" in prompt
    assert "2 distinct resume templates" in prompt
    assert "{{name}}, {{address}}" in prompt
    assert system_prompt == "You are a resume agency serving Toronto."


def test_requests_use_dynamic_structured_fields_and_stable_metadata() -> None:
    generation = config(templates_per_scenario=3)
    requests = build_template_requests(dataset(2), generation)

    assert [request.metadata["scenario_id"] for request in requests] == [
        "scenario-1",
        "scenario-2",
    ]
    assert all(
        request.model_config_id == generation.model_config_id
        for request in requests
    )
    assert all(request.persona is None for request in requests)
    assert all(request.response_format is not None for request in requests)
    response_format = requests[0].response_format
    assert response_format is not None
    assert [
        field.name for field in response_format.fields
    ] == ["template_1", "template_2", "template_3"]
    assert response_format.include_comment is False
    assert response_format.include_type_hints is False


def test_completed_scenarios_are_skipped_without_reordering() -> None:
    requests = build_template_requests(
        dataset(3),
        config(),
        completed_scenario_ids={"scenario-2"},
    )
    assert [request.metadata["scenario_id"] for request in requests] == [
        "scenario-1",
        "scenario-3",
    ]

    with pytest.raises(TemplateGenerationIdentityError, match="current dataset"):
        build_template_requests(
            dataset(2),
            config(),
            completed_scenario_ids={"unknown"},
        )


def test_successful_result_is_parsed_and_trimmed() -> None:
    generation = config()
    result = _result(
        "scenario-1",
        generation=generation,
        structured_content={
            "template_1": "  First {{name}} at {{address}}  ",
            "template_2": "Second {{name}} at {{address}}",
        },
    )
    record = parse_template_result(result, "scenario-1", generation)

    assert record.is_successful
    assert record.templates == [
        "First {{name}} at {{address}}",
        "Second {{name}} at {{address}}",
    ]


def test_edsl_spaced_placeholders_are_stored_canonically() -> None:
    generation = config()
    result = _result(
        "scenario-1",
        generation=generation,
        structured_content={
            "template_1": "First {{ name }} at {{\taddress }}",
            "template_2": "Second {{name\t}} at {{ address}}",
        },
    )

    record = parse_template_result(result, "scenario-1", generation)

    assert record.is_successful
    assert record.templates == [
        "First {{name}} at {{address}}",
        "Second {{name}} at {{address}}",
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            {
                "template_1": "Same {{name}} {{address}}",
                "template_2": "Same {{name}} {{address}}",
            },
            "pairwise distinct",
        ),
        (
            {
                "template_1": "Missing address {{name}}",
                "template_2": "Valid {{name}} {{address}}",
            },
            "missing required placeholders",
        ),
        (
            {
                "template_1": "Unknown {{name}} {{address}} {{phone}}",
                "template_2": "Valid {{name}} {{address}}",
            },
            "unknown placeholders",
        ),
        (
            {
                "template_1": "Malformed {{name}} {{address}} {{bad-name}}",
                "template_2": "Valid {{name}} {{address}}",
            },
            "invalid double-brace placeholder syntax",
        ),
        (
            {
                "template_1": "Malformed {{{name}}} {{address}}",
                "template_2": "Valid {{name}} {{address}}",
            },
            "invalid double-brace placeholder syntax",
        ),
        (
            {"template_1": "Only {{name}} {{address}}"},
            "configured cardinality",
        ),
    ],
)
def test_invalid_template_content_becomes_a_failed_record(
    content: dict[str, object],
    message: str,
) -> None:
    generation = config()
    record = parse_template_result(
        _result("scenario-1", generation=generation, structured_content=content),
        "scenario-1",
        generation,
    )

    assert not record.is_successful
    assert record.error_type == "TemplateResponseParseError"
    assert message in str(record.error_message)


def test_terminal_inference_error_remains_a_failed_pending_record() -> None:
    generation = config()
    record = parse_template_result(
        _result(
            "scenario-1",
            generation=generation,
            error=InferenceError("ProviderError", "request failed after retries"),
        ),
        "scenario-1",
        generation,
    )
    assert record.templates is None
    assert record.error_type == "ProviderError"
    assert record.error_message == "request failed after retries"


def test_batch_association_uses_request_ids_and_restores_order() -> None:
    generation = config()
    records = parse_template_batch(
        [_result("scenario-2"), _result("scenario-1")],
        ["scenario-1", "scenario-2"],
        generation,
    )
    assert [record.scenario_id for record in records] == [
        "scenario-1",
        "scenario-2",
    ]


def test_batch_contract_and_result_metadata_mismatches_are_systemic() -> None:
    generation = config()
    with pytest.raises(TemplateResultAssociationError, match="cardinality"):
        parse_template_batch(
            [_result("scenario-1")],
            ["scenario-1", "scenario-2"],
            generation,
        )

    wrong = _result("scenario-1")
    wrong.metadata["scenario_id"] = "other"
    with pytest.raises(TemplateResultAssociationError, match="metadata scenario_id"):
        parse_template_result(wrong, "scenario-1", generation)

    changed = deepcopy(generation)
    changed.prompt_template += " Changed."
    with pytest.raises(TemplateResultAssociationError, match="request ID"):
        parse_template_result(_result("scenario-1"), "scenario-1", changed)


def test_low_level_content_parser_raises_for_missing_structured_data() -> None:
    generation = config()
    result = _result("scenario-1")
    result.structured_content = None
    record = parse_template_result(result, "scenario-1", generation)
    assert record.error_type == TemplateResponseParseError.__name__
    assert "no structured content" in str(record.error_message)
