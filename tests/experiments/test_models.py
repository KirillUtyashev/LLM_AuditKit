"""Tests for experiment-domain data models and durable identities."""

from __future__ import annotations

import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentIdentityError,
    ExperimentJobKey,
    Persona,
    build_experiment_request_id,
)
from llm_auditkit.inference import InferenceConfig, ModelConfig


def _inference_config() -> InferenceConfig:
    return InferenceConfig(
        models=[
            ModelConfig(
                config_id="model-1",
                provider="openai",
                model="test-model",
                parameters={"logprobs": True},
            )
        ],
        batch_size=10,
    )


def test_experiment_model_defaults_are_independent() -> None:
    first_schema = ExperimentDatasetSchema(
        job_posting_column="job_posting",
        resume_columns=["resume_1"],
    )
    second_schema = ExperimentDatasetSchema(
        job_posting_column="job_posting",
        resume_columns=["resume_1"],
    )
    first = ExperimentConfig(
        experiment_id="experiment-1",
        dataset_schema=first_schema,
        prompt_template="Applicant 1: {resume_1}",
        personas=[
            Persona(
                "manager",
                "Manager",
                "You are a hiring manager.",
                "Evaluate applicants.",
            )
        ],
        inference=_inference_config(),
    )

    first_schema.context_columns["city"] = "city"

    assert second_schema.context_columns == {}
    assert first.save_after_each_batch is True


def test_request_id_is_stable_and_unambiguous() -> None:
    key = ExperimentJobKey(
        experiment_id="experiment-1",
        scenario_id="scenario-1",
        persona_id="manager",
        model_config_id="model-1",
    )
    delimiter_variant = ExperimentJobKey(
        experiment_id="experiment-1:scenario-1",
        scenario_id="scenario-1",
        persona_id="manager",
        model_config_id="model-1",
    )

    request_id = build_experiment_request_id(key)

    assert request_id == build_experiment_request_id(key)
    assert request_id.startswith("experiment-request:")
    assert request_id != build_experiment_request_id(delimiter_variant)


def test_request_id_rejects_empty_job_key_fields() -> None:
    invalid_key = ExperimentJobKey(
        experiment_id="experiment-1",
        scenario_id="scenario-1",
        persona_id="manager",
        model_config_id="",
    )

    with pytest.raises(ExperimentIdentityError, match="non-empty"):
        build_experiment_request_id(invalid_key)


def test_request_id_changes_with_every_job_key_dimension() -> None:
    base_values = {
        "experiment_id": "experiment-1",
        "scenario_id": "scenario-1",
        "persona_id": "manager",
        "model_config_id": "model-1",
    }
    base_id = build_experiment_request_id(ExperimentJobKey(**base_values))

    for field_name in base_values:
        changed = dict(base_values)
        changed[field_name] = f"different-{field_name}"
        assert (
            build_experiment_request_id(ExperimentJobKey(**changed)) != base_id
        )


def test_request_id_requires_an_experiment_job_key() -> None:
    with pytest.raises(ExperimentIdentityError, match="ExperimentJobKey"):
        build_experiment_request_id(object())  # type: ignore[arg-type]
