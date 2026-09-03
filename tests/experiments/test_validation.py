"""Tests for experiment configuration and DataFrame validation."""

from __future__ import annotations

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentConfigurationError,
    ExperimentDatasetError,
    ExperimentDatasetSchema,
    Persona,
    validate_experiment_config,
    validate_experiment_dataset,
    validate_experiment_inputs,
)
from llm_auditkit.inference import InferenceConfig, ModelConfig


def _schema(**changes: object) -> ExperimentDatasetSchema:
    values: dict[str, object] = {
        "job_posting_column": "job_posting",
        "resume_columns": ["resume_1", "resume_2"],
        "context_columns": {"city": "city", "year": "year"},
    }
    values.update(changes)
    return ExperimentDatasetSchema(**values)  # type: ignore[arg-type]


def _config(**changes: object) -> ExperimentConfig:
    values: dict[str, object] = {
        "experiment_id": "experiment-1",
        "dataset_schema": _schema(),
        "prompt_template": (
            "Applicant 1: {resume_1}\nApplicant 2: {resume_2}"
        ),
        "personas": [
            Persona(
                id="manager",
                name="Hiring manager",
                trait_template="You are a hiring manager in {city}.",
                instruction="Evaluate each applicant carefully.",
            )
        ],
        "inference": InferenceConfig(
            models=[
                ModelConfig(
                    config_id="model-1",
                    provider="openai",
                    model="test-model",
                    parameters={"temperature": 0, "logprobs": True},
                )
            ],
            batch_size=5,
        ),
        "save_after_each_batch": True,
    }
    values.update(changes)
    return ExperimentConfig(**values)  # type: ignore[arg-type]


def _dataset(**changes: object) -> pd.DataFrame:
    values: dict[str, object] = {
        "scenario_id": ["scenario-1", "scenario-2"],
        "job_posting": ["Posting one", "Posting two"],
        "resume_1": ["Resume 1A", "Resume 1B"],
        "resume_2": ["Resume 2A", "Resume 2B"],
        "city": ["Toronto", "Boston"],
        "year": [2020, 1960],
        "caller_metadata": ["keep-1", "keep-2"],
    }
    values.update(changes)
    return pd.DataFrame(values)


def test_valid_experiment_inputs_are_accepted() -> None:
    validate_experiment_inputs(_dataset(), _config())


def test_dataset_does_not_require_a_scenario_id_column() -> None:
    validate_experiment_inputs(
        _dataset().drop(columns=["scenario_id"]),
        _config(),
    )


def test_empty_dataset_with_configured_columns_is_valid() -> None:
    validate_experiment_inputs(_dataset().iloc[0:0], _config())


@pytest.mark.parametrize("experiment_id", [None, 1, " "])
def test_experiment_id_must_be_a_non_empty_string(experiment_id: object) -> None:
    with pytest.raises(ExperimentConfigurationError, match="experiment_id"):
        validate_experiment_config(_config(experiment_id=experiment_id))


@pytest.mark.parametrize(
    ("personas", "message"),
    [
        ([], "non-empty"),
        ([object()], "Persona"),
        ([Persona(" ", "Manager", "Trait", "Instruction")], "id"),
        ([Persona("manager", " ", "Trait", "Instruction")], "name"),
        ([Persona("manager", "Manager", " ", "Instruction")], "trait_template"),
        ([Persona("manager", "Manager", "Trait", " ")], "instruction"),
        (
            [
                Persona("manager", "Manager", "Trait", "Instruction"),
                Persona("manager", "Other", "Other trait", "Instruction"),
            ],
            "duplicate",
        ),
    ],
)
def test_invalid_personas_are_rejected(
    personas: object,
    message: str,
) -> None:
    with pytest.raises(ExperimentConfigurationError, match=message):
        validate_experiment_config(_config(personas=personas))


@pytest.mark.parametrize("trait_template", ["{", "{city.name}", "{city[name]}"])
def test_invalid_persona_trait_templates_are_rejected(
    trait_template: str,
) -> None:
    persona = Persona("manager", "Manager", trait_template, "Instruction")

    with pytest.raises(ExperimentConfigurationError, match="trait template"):
        validate_experiment_config(_config(personas=[persona]))


def test_persona_trait_fields_must_exist_in_dataset_or_semantic_context() -> None:
    persona = Persona(
        "manager",
        "Manager",
        "Manage hiring in {missing_context}.",
        "Instruction",
    )

    with pytest.raises(ExperimentDatasetError, match="missing_context"):
        validate_experiment_inputs(_dataset(), _config(personas=[persona]))


@pytest.mark.parametrize("prompt_template", [None, 1, " ", "{"])
def test_prompt_template_must_be_a_valid_non_empty_string(
    prompt_template: object,
) -> None:
    with pytest.raises(ExperimentConfigurationError, match="prompt_template|prompt template"):
        validate_experiment_config(_config(prompt_template=prompt_template))


def test_prompt_template_must_reference_every_configured_resume() -> None:
    with pytest.raises(ExperimentConfigurationError, match="resume_2"):
        validate_experiment_config(
            _config(prompt_template="Applicant 1: {resume_1}")
        )


def test_prompt_template_fields_must_exist_in_dataset_or_semantic_context() -> None:
    with pytest.raises(ExperimentDatasetError, match="missing_context"):
        validate_experiment_inputs(
            _dataset(),
            _config(
                prompt_template=(
                    "{resume_1}\n{resume_2}\nContext: {missing_context}"
                )
            ),
        )


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        (object(), "ExperimentDatasetSchema"),
        (_schema(job_posting_column=" "), "job_posting_column"),
        (_schema(resume_columns=[]), "non-empty"),
        (_schema(resume_columns=["resume_1", " "]), "position 1"),
        (_schema(resume_columns=["resume_1", "resume_1"]), "distinct"),
        (_schema(resume_columns=["job_posting"]), "distinct"),
        (_schema(context_columns=[]), "dictionary"),
        (_schema(context_columns={" ": "city"}), "semantic"),
        (_schema(context_columns={"city": " "}), "context column"),
    ],
)
def test_invalid_dataset_schemas_are_rejected(
    schema: object,
    message: str,
) -> None:
    with pytest.raises(ExperimentConfigurationError, match=message):
        validate_experiment_config(_config(dataset_schema=schema))


def test_shared_inference_configuration_is_validated() -> None:
    invalid_inference = InferenceConfig(models=[], batch_size=0)

    with pytest.raises(
        ExperimentConfigurationError,
        match="inference configuration",
    ):
        validate_experiment_config(_config(inference=invalid_inference))


def test_all_experiment_models_must_request_logprobs() -> None:
    inference = InferenceConfig(
        models=[
            ModelConfig(
                config_id="model-1",
                provider="openai",
                model="test-model",
                parameters={"temperature": 0},
            )
        ],
        batch_size=5,
    )

    with pytest.raises(ExperimentConfigurationError, match="logprobs"):
        validate_experiment_config(_config(inference=inference))


def test_checkpoint_setting_must_be_boolean() -> None:
    with pytest.raises(ExperimentConfigurationError, match="save_after_each_batch"):
        validate_experiment_config(_config(save_after_each_batch=1))


def test_dataset_must_be_a_dataframe() -> None:
    with pytest.raises(ExperimentDatasetError, match="DataFrame"):
        validate_experiment_dataset([], _schema())  # type: ignore[arg-type]


def test_dataset_columns_must_be_unique() -> None:
    dataset = _dataset()
    dataset.columns = [
        "scenario_id",
        "job_posting",
        "resume_1",
        "resume_2",
        "city",
        "year",
        "year",
    ]

    with pytest.raises(ExperimentDatasetError, match="column names"):
        validate_experiment_dataset(dataset, _schema())


def test_dataset_must_contain_every_configured_column() -> None:
    with pytest.raises(ExperimentDatasetError, match="resume_2"):
        validate_experiment_dataset(_dataset().drop(columns=["resume_2"]), _schema())


@pytest.mark.parametrize(
    "scenario_ids",
    [
        ["scenario-1", "scenario-1"],
        ["scenario-1", " "],
        ["scenario-1", None],
        ["scenario-1", 2],
    ],
)
def test_scenario_ids_must_be_unique_non_empty_strings(
    scenario_ids: list[object],
) -> None:
    with pytest.raises(ExperimentDatasetError, match="scenario ID"):
        validate_experiment_dataset(
            _dataset(scenario_id=scenario_ids),
            _schema(),
        )


def test_identical_rows_without_scenario_ids_are_rejected() -> None:
    row = _dataset().drop(columns=["scenario_id"]).iloc[[0]]
    duplicates = pd.concat([row, row], ignore_index=True)

    with pytest.raises(ExperimentDatasetError, match="replicate column"):
        validate_experiment_dataset(duplicates, _schema())


@pytest.mark.parametrize(
    ("column_name", "values"),
    [
        ("job_posting", ["Posting", " "]),
        ("resume_1", ["Resume", None]),
        ("resume_2", ["Resume", 3]),
    ],
)
def test_required_experiment_text_must_be_non_empty(
    column_name: str,
    values: list[object],
) -> None:
    with pytest.raises(ExperimentDatasetError, match=column_name):
        validate_experiment_dataset(
            _dataset(**{column_name: values}),
            _schema(),
        )
