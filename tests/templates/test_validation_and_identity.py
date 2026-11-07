"""Configuration, dataset, and identity tests for template generation."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from llm_auditkit.data.identity import derive_scenario_ids
from llm_auditkit.inference import ModelConfig
from llm_auditkit.templates import (
    TemplateGenerationConfigurationError,
    TemplateGenerationDatasetError,
    build_template_request_id,
    validate_template_generation_config,
    validate_template_generation_inputs,
)
from llm_auditkit.templates.identity import build_generation_fingerprint

from .helpers import config, dataset


def test_valid_inputs_and_internal_scenario_ids_are_accepted() -> None:
    source = dataset(supplied_ids=False)
    validate_template_generation_inputs(source, config())

    first = derive_scenario_ids(source)
    reordered_columns = source[list(reversed(source.columns))]
    assert derive_scenario_ids(reordered_columns) == first
    assert all(value.startswith("scenario:") for value in first)


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "2"])
def test_template_cardinality_must_be_a_positive_integer(value: object) -> None:
    generation = config()
    generation.templates_per_scenario = value  # type: ignore[assignment]
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="templates_per_scenario must be a positive integer",
    ):
        validate_template_generation_config(generation)


@pytest.mark.parametrize(
    "placeholders",
    [[], ["name", "name"], ["bad-name"], ["1name"], [1]],
)
def test_required_placeholder_names_are_strict(placeholders: list[object]) -> None:
    generation = config()
    generation.required_placeholders = placeholders  # type: ignore[assignment]
    with pytest.raises(TemplateGenerationConfigurationError):
        validate_template_generation_config(generation)


def test_prompt_must_reference_dynamic_contract_fields() -> None:
    generation = config()
    generation.prompt_template = "Generate resumes for {job_posting}."
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="must reference required fields",
    ):
        validate_template_generation_config(generation)


def test_invalid_braces_and_unknown_prompt_fields_fail_before_inference() -> None:
    generation = config()
    generation.system_prompt_template = "Broken {city"
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="invalid brace syntax",
    ):
        validate_template_generation_config(generation)

    generation = config()
    generation.system_prompt_template = "Use {missing_context}."
    with pytest.raises(
        TemplateGenerationDatasetError,
        match="unavailable fields",
    ):
        validate_template_generation_inputs(dataset(), generation)


def test_model_selection_and_checkpoint_flag_are_validated() -> None:
    generation = config()
    generation.model_config_id = "missing"
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="exactly one inference model",
    ):
        validate_template_generation_config(generation)

    generation = config()
    generation.save_after_each_result = 1  # type: ignore[assignment]
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="must be a boolean",
    ):
        validate_template_generation_config(generation)


def test_dataset_requires_unique_valid_scenarios_and_job_text() -> None:
    duplicate_ids = dataset()
    duplicate_ids.loc[1, "scenario_id"] = duplicate_ids.loc[0, "scenario_id"]
    with pytest.raises(TemplateGenerationDatasetError, match="must be unique"):
        validate_template_generation_inputs(duplicate_ids, config())

    duplicate_rows = dataset(supplied_ids=False)
    duplicate_rows.loc[1] = duplicate_rows.loc[0]
    with pytest.raises(TemplateGenerationDatasetError, match="must be unique"):
        validate_template_generation_inputs(duplicate_rows, config())

    empty_job = dataset()
    empty_job.loc[0, "job_text"] = " "
    with pytest.raises(TemplateGenerationDatasetError, match="non-empty strings"):
        validate_template_generation_inputs(empty_job, config())


def test_generation_fingerprint_tracks_content_but_not_execution_policy() -> None:
    baseline = config()
    fingerprint = build_generation_fingerprint(baseline)

    execution_only = deepcopy(baseline)
    execution_only.inference.batch_size = 99
    execution_only.save_after_each_result = False
    assert build_generation_fingerprint(execution_only) == fingerprint

    changed_prompt = deepcopy(baseline)
    changed_prompt.prompt_template += " Use concise language."
    assert build_generation_fingerprint(changed_prompt) != fingerprint

    changed_model = deepcopy(baseline)
    changed_model.inference.models[0] = ModelConfig(
        config_id="template-model-v1",
        provider="test",
        model="test-model",
        parameters={"temperature": 0.5},
    )
    assert build_generation_fingerprint(changed_model) != fingerprint


def test_request_identity_is_stable_and_scenario_specific() -> None:
    fingerprint = build_generation_fingerprint(config())
    first = build_template_request_id("scenario-1", fingerprint)
    assert first == build_template_request_id("scenario-1", fingerprint)
    assert first != build_template_request_id("scenario-2", fingerprint)
    assert first.startswith("template-request:")


def test_dataset_must_be_a_nonempty_dataframe() -> None:
    with pytest.raises(TemplateGenerationDatasetError, match="pandas DataFrame"):
        validate_template_generation_inputs(
            "not-data",  # type: ignore[arg-type]
            config(),
        )
    with pytest.raises(TemplateGenerationDatasetError, match="at least one row"):
        validate_template_generation_inputs(
            pd.DataFrame(columns=["job_text"]),
            config(),
        )
