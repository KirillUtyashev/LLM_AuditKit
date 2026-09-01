"""Validation for experiment configuration and DataFrame inputs."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from llm_auditkit.inference import InferenceConfigurationError
from llm_auditkit.inference.validation import validate_inference_config

from .exceptions import ExperimentConfigurationError, ExperimentDatasetError
from .models import ExperimentConfig, ExperimentDatasetSchema, Persona


def validate_experiment_config(config: ExperimentConfig) -> None:
    """Validate a complete experiment configuration before request construction."""

    if not isinstance(config, ExperimentConfig):
        raise ExperimentConfigurationError("config must be an ExperimentConfig")

    _require_non_empty_string(config.experiment_id, "experiment_id")
    _validate_dataset_schema(config.dataset_schema)
    _validate_personas(config.personas)

    try:
        validate_inference_config(config.inference)
    except InferenceConfigurationError as error:
        raise ExperimentConfigurationError(
            f"invalid inference configuration: {error}"
        ) from error

    models_without_logprobs = [
        model.config_id
        for model in config.inference.models
        if model.parameters.get("logprobs") is not True
    ]
    if models_without_logprobs:
        model_ids = ", ".join(repr(model_id) for model_id in models_without_logprobs)
        raise ExperimentConfigurationError(
            f"experiment models must request token log probabilities with "
            f"parameters['logprobs']=True: {model_ids}"
        )

    if not isinstance(config.save_after_each_batch, bool):
        raise ExperimentConfigurationError(
            "save_after_each_batch must be a boolean"
        )


def validate_experiment_dataset(
    dataset: pd.DataFrame,
    schema: ExperimentDatasetSchema,
) -> None:
    """Validate experiment rows against their configured semantic columns."""

    _validate_dataset_schema(schema)
    if not isinstance(dataset, pd.DataFrame):
        raise ExperimentDatasetError("dataset must be a pandas DataFrame")
    if not dataset.columns.is_unique:
        raise ExperimentDatasetError("dataset column names must be unique")

    required_columns = list(
        dict.fromkeys(
            [
                schema.scenario_id_column,
                schema.job_posting_column,
                *schema.resume_columns,
                *schema.context_columns.values(),
            ]
        )
    )
    missing_columns = [
        column_name
        for column_name in required_columns
        if column_name not in dataset.columns
    ]
    if missing_columns:
        names = ", ".join(repr(name) for name in missing_columns)
        raise ExperimentDatasetError(
            f"dataset is missing configured columns: {names}"
        )

    scenario_ids = dataset[schema.scenario_id_column]
    if not scenario_ids.map(_is_non_empty_string).all():
        raise ExperimentDatasetError(
            f"scenario ID column {schema.scenario_id_column!r} must contain "
            "non-empty strings"
        )
    if scenario_ids.duplicated().any():
        raise ExperimentDatasetError(
            f"scenario ID column {schema.scenario_id_column!r} must contain "
            "unique values"
        )

    text_columns = [schema.job_posting_column, *schema.resume_columns]
    for column_name in text_columns:
        if not dataset[column_name].map(_is_non_empty_string).all():
            raise ExperimentDatasetError(
                f"experiment text column {column_name!r} must contain non-empty "
                "strings"
            )


def validate_experiment_inputs(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> None:
    """Validate configuration and dataset before any experiment inference."""

    validate_experiment_config(config)
    validate_experiment_dataset(dataset, config.dataset_schema)


def _validate_dataset_schema(schema: ExperimentDatasetSchema) -> None:
    if not isinstance(schema, ExperimentDatasetSchema):
        raise ExperimentConfigurationError(
            "dataset_schema must be an ExperimentDatasetSchema"
        )

    _require_non_empty_string(schema.scenario_id_column, "scenario_id_column")
    _require_non_empty_string(schema.job_posting_column, "job_posting_column")
    if not _is_sequence(schema.resume_columns) or not schema.resume_columns:
        raise ExperimentConfigurationError(
            "resume_columns must be a non-empty sequence"
        )
    for index, column_name in enumerate(schema.resume_columns):
        _require_non_empty_string(
            column_name,
            f"resume column at position {index}",
        )

    core_columns = [
        schema.scenario_id_column,
        schema.job_posting_column,
        *schema.resume_columns,
    ]
    if len(set(core_columns)) != len(core_columns):
        raise ExperimentConfigurationError(
            "scenario, job-posting, and resume column names must be distinct"
        )

    if not isinstance(schema.context_columns, dict):
        raise ExperimentConfigurationError("context_columns must be a dictionary")
    for context_name, column_name in schema.context_columns.items():
        _require_non_empty_string(context_name, "context column semantic name")
        _require_non_empty_string(
            column_name,
            f"context column {context_name!r}",
        )


def _validate_personas(personas: Sequence[Persona]) -> None:
    if not _is_sequence(personas) or not personas:
        raise ExperimentConfigurationError(
            "personas must be a non-empty sequence of Persona values"
        )

    seen_ids: set[str] = set()
    for index, persona in enumerate(personas):
        if not isinstance(persona, Persona):
            raise ExperimentConfigurationError(
                f"persona at position {index} must be a Persona"
            )
        _require_non_empty_string(persona.id, f"persona at position {index} id")
        _require_non_empty_string(persona.name, f"persona {persona.id!r} name")
        _require_non_empty_string(
            persona.description,
            f"persona {persona.id!r} description",
        )
        if persona.id in seen_ids:
            raise ExperimentConfigurationError(
                f"duplicate persona ID: {persona.id!r}"
            )
        seen_ids.add(persona.id)


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not _is_non_empty_string(value):
        raise ExperimentConfigurationError(
            f"{field_name} must be a non-empty string"
        )


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )
