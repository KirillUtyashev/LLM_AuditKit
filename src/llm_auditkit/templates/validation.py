"""Validation for template-generation configuration and DataFrame inputs."""

from __future__ import annotations

import re

import pandas as pd

from llm_auditkit.data.identity import SCENARIO_ID_COLUMN, derive_scenario_ids
from llm_auditkit.inference.exceptions import InferenceConfigurationError
from llm_auditkit.inference.validation import validate_inference_config

from .exceptions import (
    TemplateGenerationConfigurationError,
    TemplateGenerationDatasetError,
)
from .models import TemplateDatasetSchema, TemplateGenerationConfig
from .prompts import available_prompt_fields, template_prompt_fields


_PLACEHOLDER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_REQUIRED_PROMPT_FIELDS = {
    "job_posting",
    "templates_per_scenario",
    "required_placeholders",
}


def validate_template_generation_config(config: TemplateGenerationConfig) -> None:
    """Validate a complete generation configuration before request construction."""

    if not isinstance(config, TemplateGenerationConfig):
        raise TemplateGenerationConfigurationError(
            "config must be a TemplateGenerationConfig"
        )
    if (
        not isinstance(config.templates_per_scenario, int)
        or isinstance(config.templates_per_scenario, bool)
        or config.templates_per_scenario <= 0
    ):
        raise TemplateGenerationConfigurationError(
            "templates_per_scenario must be a positive integer"
        )
    _validate_dataset_schema(config.dataset_schema)
    _validate_placeholders(config.required_placeholders)

    prompt_fields = template_prompt_fields(config.prompt_template, "prompt_template")
    missing_required = sorted(_REQUIRED_PROMPT_FIELDS.difference(prompt_fields))
    if missing_required:
        rendered = ", ".join(repr(field) for field in missing_required)
        raise TemplateGenerationConfigurationError(
            f"prompt_template must reference required fields: {rendered}"
        )
    if config.system_prompt_template is not None:
        template_prompt_fields(
            config.system_prompt_template,
            "system_prompt_template",
        )
    if (
        not isinstance(config.model_config_id, str)
        or not config.model_config_id.strip()
    ):
        raise TemplateGenerationConfigurationError(
            "model_config_id must be a non-empty string"
        )
    if not isinstance(config.save_after_each_result, bool):
        raise TemplateGenerationConfigurationError(
            "save_after_each_result must be a boolean"
        )

    try:
        validate_inference_config(config.inference)
    except InferenceConfigurationError as error:
        raise TemplateGenerationConfigurationError(
            f"invalid inference configuration: {error}"
        ) from error
    matching_models = [
        model
        for model in config.inference.models
        if model.config_id == config.model_config_id
    ]
    if len(matching_models) != 1:
        raise TemplateGenerationConfigurationError(
            "model_config_id must reference exactly one inference model"
        )


def validate_template_generation_dataset(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> None:
    """Validate source rows and prompt fields without mutating the DataFrame."""

    if not isinstance(dataset, pd.DataFrame):
        raise TemplateGenerationDatasetError("dataset must be a pandas DataFrame")
    if dataset.empty:
        raise TemplateGenerationDatasetError("dataset must contain at least one row")
    if not dataset.columns.is_unique:
        raise TemplateGenerationDatasetError("dataset column names must be unique")
    invalid_columns = [
        column for column in dataset.columns if not isinstance(column, str)
    ]
    if invalid_columns:
        raise TemplateGenerationDatasetError("dataset column names must be strings")

    schema = config.dataset_schema
    required_columns = {schema.job_posting_column, *schema.context_columns.values()}
    missing_columns = sorted(required_columns.difference(dataset.columns))
    if missing_columns:
        rendered = ", ".join(repr(column) for column in missing_columns)
        raise TemplateGenerationDatasetError(
            f"dataset is missing configured columns: {rendered}"
        )

    invalid_postings = [
        position
        for position, value in enumerate(dataset[schema.job_posting_column].tolist())
        if not isinstance(value, str) or not value.strip()
    ]
    if invalid_postings:
        raise TemplateGenerationDatasetError(
            f"job posting column {schema.job_posting_column!r} must contain "
            "non-empty strings"
        )

    scenario_ids = derive_scenario_ids(dataset)
    if SCENARIO_ID_COLUMN in dataset.columns and any(
        not isinstance(value, str) or not value.strip() for value in scenario_ids
    ):
        raise TemplateGenerationDatasetError(
            "scenario_id values must be non-empty strings"
        )
    if len(set(scenario_ids)) != len(scenario_ids):
        raise TemplateGenerationDatasetError(
            "scenario_id values must be unique; exact duplicate source rows require "
            "a stable replicate column"
        )

    available = available_prompt_fields(set(dataset.columns), config)
    for label, template in (
        ("prompt_template", config.prompt_template),
        ("system_prompt_template", config.system_prompt_template),
    ):
        if template is None:
            continue
        unavailable = sorted(
            template_prompt_fields(template, label).difference(available)
        )
        if unavailable:
            rendered = ", ".join(repr(field) for field in unavailable)
            raise TemplateGenerationDatasetError(
                f"{label} references unavailable fields: {rendered}"
            )


def validate_template_generation_inputs(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> None:
    """Validate config and dataset together."""

    validate_template_generation_config(config)
    validate_template_generation_dataset(dataset, config)


def _validate_dataset_schema(schema: TemplateDatasetSchema) -> None:
    if not isinstance(schema, TemplateDatasetSchema):
        raise TemplateGenerationConfigurationError(
            "dataset_schema must be a TemplateDatasetSchema"
        )
    if (
        not isinstance(schema.job_posting_column, str)
        or not schema.job_posting_column.strip()
    ):
        raise TemplateGenerationConfigurationError(
            "job_posting_column must be a non-empty string"
        )
    if not isinstance(schema.context_columns, dict) or any(
        not isinstance(alias, str)
        or not alias.strip()
        or not isinstance(column, str)
        or not column.strip()
        for alias, column in schema.context_columns.items()
    ):
        raise TemplateGenerationConfigurationError(
            "context_columns must map non-empty string aliases to non-empty columns"
        )
    reserved_aliases = {"templates_per_scenario", "required_placeholders"}
    invalid_aliases = sorted(reserved_aliases.intersection(schema.context_columns))
    if invalid_aliases:
        rendered = ", ".join(repr(alias) for alias in invalid_aliases)
        raise TemplateGenerationConfigurationError(
            f"context aliases are reserved: {rendered}"
        )
    if (
        "job_posting" in schema.context_columns
        and schema.context_columns["job_posting"] != schema.job_posting_column
    ):
        raise TemplateGenerationConfigurationError(
            "context alias 'job_posting' must map to job_posting_column"
        )


def _validate_placeholders(placeholders: list[str]) -> None:
    if not isinstance(placeholders, list) or not placeholders:
        raise TemplateGenerationConfigurationError(
            "required_placeholders must be a non-empty list"
        )
    if any(
        not isinstance(name, str) or _PLACEHOLDER_NAME.fullmatch(name) is None
        for name in placeholders
    ):
        raise TemplateGenerationConfigurationError(
            "required placeholder names must match [A-Za-z][A-Za-z0-9_]*"
        )
    if len(set(placeholders)) != len(placeholders):
        raise TemplateGenerationConfigurationError(
            "required placeholder names must be unique"
        )
