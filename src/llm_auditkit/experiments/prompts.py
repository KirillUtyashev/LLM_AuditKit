"""Deterministic prompt construction for hiring experiments."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from string import Formatter

from .exceptions import ExperimentConfigurationError, ExperimentDatasetError
from .models import ExperimentDatasetSchema, Persona


_FORMATTER = Formatter()
_NEWSPAPER_BY_CITY = {
    "Chicago": "Chicago Tribune",
    "Boston": "Boston Globe",
    "Birmingham": "Birmingham News",
}


def persona_trait_fields(persona: Persona) -> set[str]:
    """Return the simple field names referenced by a persona trait template."""

    return _template_fields(
        persona.trait_template,
        f"persona {persona.id!r} trait template",
    )


def experiment_prompt_fields(prompt_template: str) -> set[str]:
    """Return the simple field names referenced by an experiment prompt template."""

    return _template_fields(prompt_template, "experiment prompt template")


def _template_fields(template: str, label: str) -> set[str]:
    try:
        parsed = _FORMATTER.parse(template)
        fields = {
            field_name
            for _, field_name, _, _ in parsed
            if field_name is not None
        }
    except ValueError as error:
        raise ExperimentConfigurationError(
            f"{label} is invalid: {error}"
        ) from error

    invalid_fields = sorted(
        field_name
        for field_name in fields
        if not field_name or "." in field_name or "[" in field_name or "]" in field_name
    )
    if invalid_fields:
        rendered = ", ".join(repr(field_name) for field_name in invalid_fields)
        raise ExperimentConfigurationError(
            f"{label} fields must be simple names: {rendered}"
        )
    return fields


def render_persona_trait(
    row: Mapping[str, object],
    schema: ExperimentDatasetSchema,
    persona: Persona,
) -> str:
    """Render one persona trait from source columns and semantic context aliases."""

    fields = persona_trait_fields(persona)
    values = _template_values(row, schema, fields)
    try:
        return persona.trait_template.format_map(values)
    except (KeyError, ValueError) as error:
        raise ExperimentDatasetError(
            f"could not render persona {persona.id!r} trait template: {error}"
        ) from error


def build_experiment_prompt(
    row: Mapping[str, object],
    schema: ExperimentDatasetSchema,
    prompt_template: str,
) -> str:
    """Render one configured experiment question from a source row."""

    fields = experiment_prompt_fields(prompt_template)
    values = _template_values(row, schema, fields)
    try:
        return prompt_template.format_map(values)
    except (KeyError, ValueError) as error:
        raise ExperimentDatasetError(
            f"could not render experiment prompt template: {error}"
        ) from error


def _template_values(
    row: Mapping[str, object],
    schema: ExperimentDatasetSchema,
    fields: set[str],
) -> dict[str, object]:
    values = dict(row)
    values["job_posting"] = row[schema.job_posting_column]
    values.update(
        {
            context_name: row[column_name]
            for context_name, column_name in schema.context_columns.items()
        }
    )
    if "date14" in fields:
        values["date14"] = _date_after_posting(values)
    if "newspaper" in fields:
        values["newspaper"] = _newspaper_for_city(values)
    return values


def derived_persona_trait_fields(schema: ExperimentDatasetSchema) -> set[str]:
    """Return paper-compatible derived fields available for a configured schema."""

    fields: set[str] = set()
    if {"year", "month", "day"}.issubset(schema.context_columns):
        fields.add("date14")
    if "city" in schema.context_columns:
        fields.add("newspaper")
    return fields


def _date_after_posting(values: Mapping[str, object]) -> str:
    try:
        posting_date = datetime(
            int(values["year"]),
            int(values["month"]),
            int(values["day"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ExperimentDatasetError(
            "persona trait field 'date14' requires valid year, month, and day values"
        ) from error
    return (posting_date + timedelta(days=14)).strftime("%B %d, %Y")


def _newspaper_for_city(values: Mapping[str, object]) -> str:
    city = values.get("city")
    if not isinstance(city, str) or city not in _NEWSPAPER_BY_CITY:
        supported = ", ".join(sorted(_NEWSPAPER_BY_CITY))
        raise ExperimentDatasetError(
            "persona trait field 'newspaper' requires a supported city: "
            f"{supported}"
        )
    return _NEWSPAPER_BY_CITY[city]
