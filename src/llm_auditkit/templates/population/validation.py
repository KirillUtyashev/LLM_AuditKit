"""Internal validation and identity matching for template population."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd
from pandas.api.types import (
    is_bool,
    is_datetime64_dtype,
    is_float,
    is_integer,
    is_timedelta64_dtype,
)

from .exceptions import (
    TemplatePopulationConfigurationError,
    TemplatePopulationDatasetError,
)
from .models import TemplatePopulationConfig


_STRUCTURAL_COLUMNS = (
    "scenario_id", "template_id", "candidate_id", "candidate_order",
)
_LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Public experiment output contract; deliberately independent of its internals.
# Keep source-column restrictions in sync with ExperimentResultStore.
_EXPERIMENT_RESERVED = frozenset({
    "experiment_id", "persona_id", "model_config_id", "request_id",
    "persona_name", "model", "provider", "persona_instruction", "user_prompt",
    "system_prompt", "generated_response", "comment", "picks", "error_type",
    "error_message",
})
_EXPERIMENT_RESULT = re.compile(r"(?:pick|logprob)[1-9][0-9]*\Z")


@dataclass(slots=True)
class ValidatedInputs:
    """Validated records in source order with candidates keyed by output slot."""

    source_rows: list[dict[str, object]]
    candidates: dict[str, dict[int, dict[str, object]]]
    payload_columns: tuple[str, ...]
    appended_columns: tuple[str, ...]


def is_nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_config(config: TemplatePopulationConfig) -> None:
    error = TemplatePopulationConfigurationError
    if not isinstance(config, TemplatePopulationConfig):
        raise error("config must be a TemplatePopulationConfig")
    if not is_nonblank_string(config.job_posting_column):
        raise error("job_posting_column must be a nonblank string")
    if not isinstance(config.template_columns, Mapping) or not config.template_columns:
        raise error("template_columns must be a nonempty mapping")
    if not isinstance(config.placeholder_columns, Mapping):
        raise error("placeholder_columns must be a mapping")
    for template_id, column in config.template_columns.items():
        if not is_nonblank_string(template_id):
            raise error("template_columns keys must be nonblank template ID strings")
        if not is_nonblank_string(column):
            raise error(f"template_columns[{template_id!r}] must name a nonblank column")
    template_columns = list(config.template_columns.values())
    if len(set(template_columns)) != len(template_columns):
        raise error("template_columns must name distinct text columns")
    if "scenario_id" in template_columns or config.job_posting_column == "scenario_id":
        raise error("job and template text columns must differ from scenario_id")
    if config.job_posting_column in template_columns:
        raise error("job_posting_column must differ from template text columns")
    for label, column in config.placeholder_columns.items():
        if not isinstance(label, str) or _LABEL.fullmatch(label) is None:
            raise error("placeholder_columns keys must match [A-Za-z_][A-Za-z0-9_]*")
        if not is_nonblank_string(column):
            raise error(f"placeholder_columns[{label!r}] must name a nonblank column")
        if column in _STRUCTURAL_COLUMNS:
            raise error(
                f"placeholder_columns[{label!r}] targets structural column {column!r}; "
                "a payload column is required"
            )


def _validate_frame(frame: pd.DataFrame, name: str, required: list[str]) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TemplatePopulationDatasetError(f"{name} must be a pandas DataFrame")
    if not all(is_nonblank_string(column) for column in frame.columns):
        raise TemplatePopulationDatasetError(
            f"{name} column names must be nonblank strings"
        )
    if not frame.columns.is_unique:
        raise TemplatePopulationDatasetError(f"{name} column names must be unique")
    missing = [column for column in dict.fromkeys(required) if column not in frame]
    if missing:
        raise TemplatePopulationDatasetError(f"{name} is missing columns: {missing!r}")
    if frame.empty:
        raise TemplatePopulationDatasetError(f"{name} must contain at least one row")


def _is_supported_scalar(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str) or is_bool(value) or is_integer(value):
        return True
    if is_float(value):
        # Avoid float(value): it can narrow a NumPy floating scalar.
        return bool(pd.isna(value) or -math.inf < value < math.inf)
    if is_datetime64_dtype(type(value)) or is_timedelta64_dtype(type(value)):
        # NumPy NaT equivalents are missing scalars; actual dates are not metadata.
        return bool(pd.isna(value))
    return False


def _validate_scalars(row: dict[str, object], context: str) -> None:
    for column, value in row.items():
        if not _is_supported_scalar(value):
            raise TemplatePopulationDatasetError(
                f"{context}: column {column!r} contains an unsupported scalar type "
                "or nonfinite value"
            )


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    # iterrows can coerce integers to floats; tuple iteration keeps cell scalars.
    return [dict(zip(frame.columns, values)) for values in frame.itertuples(index=False, name=None)]


def _require_string(row: dict[str, object], column: str, context: str) -> None:
    if not is_nonblank_string(row[column]):
        raise TemplatePopulationDatasetError(
            f"{context}: column {column!r} must contain a nonblank string"
        )


def _output_columns(
    source_columns: list[str], payload: tuple[str, ...], count: int,
) -> tuple[str, ...]:
    appended = ["candidate_count"]
    for slot in range(1, count + 1):
        appended.extend([
            f"resume_{slot}", f"candidate_{slot}_id",
            f"candidate_{slot}_template_id", f"candidate_{slot}_template_column",
            *(f"candidate_{slot}_{column}" for column in payload),
        ])
    seen: set[str] = set()
    for column in [*source_columns, *appended]:
        if column in seen:
            raise TemplatePopulationDatasetError(f"output column collision: {column!r}")
        if column in _EXPERIMENT_RESERVED or _EXPERIMENT_RESULT.fullmatch(column):
            raise TemplatePopulationDatasetError(
                f"output column {column!r} is reserved by experiment execution"
            )
        seen.add(column)
    return tuple(appended)


def validate_inputs(
    templates: pd.DataFrame,
    replacements: pd.DataFrame,
    config: TemplatePopulationConfig,
) -> ValidatedInputs:
    """Validate both tables completely, without changing inputs or config."""
    _validate_config(config)
    _validate_frame(
        templates, "templates",
        ["scenario_id", config.job_posting_column, *config.template_columns.values()],
    )
    _validate_frame(
        replacements, "replacements",
        [*_STRUCTURAL_COLUMNS, *config.placeholder_columns.values()],
    )
    payload = tuple(column for column in replacements if column not in _STRUCTURAL_COLUMNS)
    count = len(config.template_columns)
    appended = _output_columns(list(templates.columns), payload, count)
    sources = _records(templates)
    candidates: dict[str, dict[int, dict[str, object]]] = {}
    used_templates: dict[str, set[str]] = {}
    used_candidates: dict[str, set[str]] = {}
    for row in sources:
        _require_string(row, "scenario_id", "templates")
        scenario_id = row["scenario_id"]
        context = f"templates scenario_id={scenario_id!r}"
        if scenario_id in candidates:
            raise TemplatePopulationDatasetError(f"{context}: duplicate scenario_id")
        for column in [config.job_posting_column, *config.template_columns.values()]:
            _require_string(row, column, context)
        _validate_scalars(row, context)
        candidates[scenario_id] = {}
        used_templates[scenario_id] = set()
        used_candidates[scenario_id] = set()

    for row in _records(replacements):
        for column in _STRUCTURAL_COLUMNS[:3]:
            _require_string(row, column, "replacements")
        scenario_id = row["scenario_id"]
        template_id = row["template_id"]
        candidate_id = row["candidate_id"]
        context = (
            f"replacements scenario_id={scenario_id!r}, template_id={template_id!r}, "
            f"candidate_id={candidate_id!r}"
        )
        if scenario_id not in candidates:
            raise TemplatePopulationDatasetError(f"{context}: unknown scenario_id")
        if template_id not in config.template_columns:
            raise TemplatePopulationDatasetError(f"{context}: unknown template_id")
        if template_id in used_templates[scenario_id]:
            raise TemplatePopulationDatasetError(f"{context}: duplicate template_id in scenario")
        if candidate_id in used_candidates[scenario_id]:
            raise TemplatePopulationDatasetError(f"{context}: duplicate candidate_id in scenario")
        order = row["candidate_order"]
        if not is_integer(order) or is_bool(order) or not 1 <= order <= count:
            raise TemplatePopulationDatasetError(
                f"{context}: candidate_order must be an integer in 1..{count}"
            )
        if order in candidates[scenario_id]:
            raise TemplatePopulationDatasetError(f"{context}: duplicate candidate_order")
        _validate_scalars(row, context)
        candidates[scenario_id][order] = row
        used_templates[scenario_id].add(template_id)
        used_candidates[scenario_id].add(candidate_id)

    for scenario_id in candidates:
        missing = set(config.template_columns) - used_templates[scenario_id]
        if missing:
            raise TemplatePopulationDatasetError(
                f"scenario_id={scenario_id!r}: missing replacement rows for "
                f"template IDs {sorted(missing)!r}; exactly {count} applicants required"
            )
    return ValidatedInputs(sources, candidates, payload, appended)
