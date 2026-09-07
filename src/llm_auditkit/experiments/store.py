"""Canonical DataFrame output, checkpoint, and resume storage for experiments."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from .exceptions import ExperimentResultStoreError
from .identity import derive_scenario_ids
from .models import (
    ExperimentConfig,
    ExperimentJobKey,
    ExperimentOutcome,
    ExperimentOutputRecord,
    build_experiment_request_id,
)
from .planning import build_experiment_job_keys
from .validation import validate_experiment_inputs


_IDENTITY_COLUMNS = [
    "experiment_id",
    "scenario_id",
    "persona_id",
    "model_config_id",
    "request_id",
]
_DETAIL_COLUMNS = [
    "persona_instruction",
    "user_prompt",
    "system_prompt",
    "generated_response",
    "comment",
    "picks",
]
_ERROR_COLUMNS = ["error_type", "error_message"]
_RESERVED_STATIC_COLUMNS = set(
    _IDENTITY_COLUMNS + _DETAIL_COLUMNS + _ERROR_COLUMNS
)
_DYNAMIC_RESULT_COLUMN = re.compile(r"(?:pick|logprob)[1-9][0-9]*\Z")


class ExperimentResultStore:
    """Own a canonical experiment CSV and its atomic checkpoint operations."""

    def __init__(self, output_path: str | Path) -> None:
        if not isinstance(output_path, (str, Path)) or not str(output_path).strip():
            raise ExperimentResultStoreError(
                "output_path must be a non-empty string or Path"
            )
        self.output_path = Path(output_path)
        if self.output_path.exists() and self.output_path.is_dir():
            raise ExperimentResultStoreError("output_path must not be a directory")

    def initialize(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        """Return empty canonical output or validate and load an existing checkpoint."""

        validate_experiment_inputs(dataset, config)
        expected_columns = _expected_columns(dataset, config)
        if not self.output_path.exists():
            return pd.DataFrame(columns=expected_columns)

        output_dataset = self._read_existing(expected_columns, config)
        _validate_existing_output(output_dataset, dataset, config)
        return _canonicalize_output(output_dataset, dataset, config)

    def apply_batch(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
        records: Sequence[ExperimentOutputRecord],
    ) -> pd.DataFrame:
        """Apply a fully handled batch in memory and restore canonical job order."""

        validate_experiment_inputs(dataset, config)
        _validate_existing_output(output_dataset, dataset, config)
        validated_records = _validate_records(records, output_dataset, dataset, config)
        if not validated_records:
            return output_dataset.copy(deep=True).reset_index(drop=True)

        replaced_keys = {record.key for record in validated_records}
        retained_rows = [
            row
            for row in output_dataset.to_dict(orient="records")
            if _key_from_row(row) not in replaced_keys
        ]
        source_rows = dict(
            zip(
                derive_scenario_ids(dataset),
                dataset.to_dict(orient="records"),
                strict=True,
            )
        )
        new_rows = [
            _record_to_row(record, source_rows[record.key.scenario_id], config)
            for record in validated_records
        ]
        combined = pd.DataFrame(
            retained_rows + new_rows,
            columns=_expected_columns(dataset, config),
        )
        return _canonicalize_output(combined, dataset, config)

    def save(self, output_dataset: pd.DataFrame) -> None:
        """Persist one complete in-memory snapshot with atomic replacement."""

        if not isinstance(output_dataset, pd.DataFrame):
            raise ExperimentResultStoreError(
                "output_dataset must be a pandas DataFrame"
            )
        if not output_dataset.columns.is_unique:
            raise ExperimentResultStoreError(
                "output_dataset column names must be unique before saving"
            )
        self._atomic_write(output_dataset)

    def save_batch(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
        records: Sequence[ExperimentOutputRecord],
    ) -> pd.DataFrame:
        """Apply one completed logical batch and atomically checkpoint it once."""

        updated_output = self.apply_batch(
            output_dataset,
            dataset,
            config,
            records,
        )
        self.save(updated_output)
        return updated_output

    def completed_keys(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> set[ExperimentJobKey]:
        """Return durable job keys with complete successful output rows."""

        validate_experiment_inputs(dataset, config)
        _validate_existing_output(output_dataset, dataset, config)
        return {
            _key_from_row(row)
            for row in output_dataset.to_dict(orient="records")
            if _row_is_complete(row, config)
        }

    def is_complete(
        self,
        output_dataset: pd.DataFrame,
        key: ExperimentJobKey,
        config: ExperimentConfig,
    ) -> bool:
        """Check whether exactly one row has every successful result field for a key."""

        if not isinstance(output_dataset, pd.DataFrame):
            raise ExperimentResultStoreError(
                "output_dataset must be a pandas DataFrame"
            )
        if not isinstance(key, ExperimentJobKey):
            raise ExperimentResultStoreError("key must be an ExperimentJobKey")
        required_columns = set(_output_columns(config))
        if not required_columns.issubset(output_dataset.columns):
            raise ExperimentResultStoreError(
                "output_dataset does not contain the configured result columns"
            )

        matching_rows = [
            row
            for row in output_dataset.to_dict(orient="records")
            if _key_from_row(row) == key
        ]
        return len(matching_rows) == 1 and _row_is_complete(
            matching_rows[0],
            config,
        )

    def _read_existing(
        self,
        expected_columns: list[str],
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        try:
            header = pd.read_csv(self.output_path, nrows=0)
            if list(header.columns) != expected_columns:
                raise ExperimentResultStoreError(
                    "existing experiment CSV columns do not match the current "
                    "dataset and experiment configuration"
                )
            string_columns = set(_IDENTITY_COLUMNS)
            return pd.read_csv(
                self.output_path,
                dtype={column: "string" for column in string_columns},
            )
        except ExperimentResultStoreError:
            raise
        except Exception as error:
            raise ExperimentResultStoreError(
                f"could not read existing experiment CSV: {type(error).__name__}: "
                f"{error}"
            ) from error

    def _atomic_write(self, output_dataset: pd.DataFrame) -> None:
        temporary_path: Path | None = None
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self.output_path.parent,
                prefix=f".{self.output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                output_dataset.to_csv(temporary_file, index=False)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.output_path)
            temporary_path = None
        except Exception as error:
            raise ExperimentResultStoreError(
                f"could not atomically save experiment CSV: {type(error).__name__}: "
                f"{error}"
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _expected_columns(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> list[str]:
    _validate_source_columns(dataset, config)
    source_columns = list(dataset.columns)
    return source_columns + [
        column for column in _output_columns(config) if column not in source_columns
    ]


def _output_columns(config: ExperimentConfig) -> list[str]:
    resume_count = len(config.dataset_schema.resume_columns)
    return (
        _IDENTITY_COLUMNS
        + _DETAIL_COLUMNS
        + [f"pick{position}" for position in range(1, resume_count + 1)]
        + [f"logprob{position}" for position in range(1, resume_count + 1)]
        + _ERROR_COLUMNS
    )


def _validate_source_columns(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> None:
    for column in dataset.columns:
        if not isinstance(column, str):
            raise ExperimentResultStoreError(
                "experiment source column names must be strings for CSV persistence"
            )
        if column == "scenario_id":
            continue
        if (
            column in _RESERVED_STATIC_COLUMNS
            or _DYNAMIC_RESULT_COLUMN.fullmatch(column)
        ):
            raise ExperimentResultStoreError(
                f"source column {column!r} conflicts with an experiment output column"
            )


def _validate_existing_output(
    output_dataset: pd.DataFrame,
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> None:
    if not isinstance(output_dataset, pd.DataFrame):
        raise ExperimentResultStoreError("output_dataset must be a pandas DataFrame")
    expected_columns = _expected_columns(dataset, config)
    if list(output_dataset.columns) != expected_columns:
        raise ExperimentResultStoreError(
            "output_dataset columns do not match the current dataset and configuration"
        )

    planned_keys = set(build_experiment_job_keys(dataset, config))
    seen_keys: set[ExperimentJobKey] = set()
    personas = {persona.id: persona for persona in config.personas}
    for row in output_dataset.to_dict(orient="records"):
        key = _key_from_row(row)
        if key in seen_keys:
            raise ExperimentResultStoreError(
                "output_dataset contains duplicate experiment job keys"
            )
        if key not in planned_keys:
            raise ExperimentResultStoreError(
                "output_dataset contains a job key outside the current experiment plan"
            )
        if not _is_non_empty_string(row["request_id"]) or row[
            "request_id"
        ] != build_experiment_request_id(key):
            raise ExperimentResultStoreError(
                "output_dataset contains a request ID that does not match its job key"
            )
        persona = personas[key.persona_id]
        if (
            not _is_non_empty_string(row["persona_instruction"])
            or row["persona_instruction"] != persona.instruction
        ):
            raise ExperimentResultStoreError(
                "output_dataset persona fields do not match the current configuration"
            )
        seen_keys.add(key)


def _validate_records(
    records: Sequence[ExperimentOutputRecord],
    output_dataset: pd.DataFrame,
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> list[ExperimentOutputRecord]:
    if not _is_sequence(records) or not all(
        isinstance(record, ExperimentOutputRecord) for record in records
    ):
        raise ExperimentResultStoreError(
            "records must be a sequence of ExperimentOutputRecord values"
        )

    validated_records = list(records)
    planned_keys = set(build_experiment_job_keys(dataset, config))
    personas = {persona.id: persona for persona in config.personas}
    seen_keys: set[ExperimentJobKey] = set()
    completed_keys = {
        _key_from_row(row)
        for row in output_dataset.to_dict(orient="records")
        if _row_is_complete(row, config)
    }
    resume_count = len(config.dataset_schema.resume_columns)
    for record in validated_records:
        if not isinstance(record.key, ExperimentJobKey):
            raise ExperimentResultStoreError(
                "batch record key must be an ExperimentJobKey"
            )
        if record.key not in planned_keys:
            raise ExperimentResultStoreError(
                "batch record contains a job key outside the current experiment plan"
            )
        if record.key in seen_keys:
            raise ExperimentResultStoreError(
                "batch records contain duplicate experiment job keys"
            )
        if record.request_id != build_experiment_request_id(record.key):
            raise ExperimentResultStoreError(
                "batch record request ID does not match its experiment job key"
            )
        persona = personas[record.key.persona_id]
        if record.persona_instruction != persona.instruction:
            raise ExperimentResultStoreError(
                "batch record persona fields do not match the current configuration"
            )
        if record.key in completed_keys:
            raise ExperimentResultStoreError(
                "a completed experiment job cannot be replaced by another batch record"
            )
        _validate_record_outcome(record, resume_count)
        seen_keys.add(record.key)
    return validated_records


def _validate_record_outcome(
    record: ExperimentOutputRecord,
    resume_count: int,
) -> None:
    if record.user_prompt is not None and not isinstance(record.user_prompt, str):
        raise ExperimentResultStoreError(
            "batch record user prompt must be a string or None"
        )
    if record.system_prompt is not None and not isinstance(record.system_prompt, str):
        raise ExperimentResultStoreError(
            "batch record system prompt must be a string or None"
        )
    if record.is_successful:
        outcome = record.outcome
        if not isinstance(outcome, ExperimentOutcome):
            raise ExperimentResultStoreError(
                "successful batch record outcome must be an ExperimentOutcome"
            )
        if len(outcome.picks) != resume_count or any(
            type(pick) is not int or pick not in {0, 1} for pick in outcome.picks
        ):
            raise ExperimentResultStoreError(
                "successful batch record picks must contain one 0 or 1 per resume"
            )
        if len(outcome.logprobs) != resume_count or any(
            not _is_finite_number(logprob) for logprob in outcome.logprobs
        ):
            raise ExperimentResultStoreError(
                "successful batch record logprobs must contain one finite value per "
                "resume"
            )
        if not _is_non_empty_string(outcome.generated_response):
            raise ExperimentResultStoreError(
                "successful batch record must contain a generated response"
            )
        if outcome.comment is not None and not isinstance(outcome.comment, str):
            raise ExperimentResultStoreError(
                "successful batch record comment must be a string or None"
            )
        if not _is_non_empty_string(record.user_prompt):
            raise ExperimentResultStoreError(
                "successful batch record must contain a rendered user prompt"
            )
        return

    if record.outcome is not None:
        raise ExperimentResultStoreError(
            "failed batch record must not contain a parsed outcome"
        )
    if not _is_non_empty_string(record.error_type) or not _is_non_empty_string(
        record.error_message
    ):
        raise ExperimentResultStoreError(
            "failed batch record must contain an error type and message"
        )


def _record_to_row(
    record: ExperimentOutputRecord,
    source_row: dict[str, object],
    config: ExperimentConfig,
) -> dict[str, object]:
    row = dict(source_row)
    row.update(
        {
            "experiment_id": record.key.experiment_id,
            "scenario_id": record.key.scenario_id,
            "persona_id": record.key.persona_id,
            "model_config_id": record.key.model_config_id,
            "request_id": record.request_id,
            "persona_instruction": record.persona_instruction,
            "user_prompt": record.user_prompt,
            "system_prompt": record.system_prompt,
            "generated_response": None,
            "comment": None,
            "picks": None,
            "error_type": record.error_type,
            "error_message": record.error_message,
        }
    )
    resume_count = len(config.dataset_schema.resume_columns)
    for position in range(1, resume_count + 1):
        row[f"pick{position}"] = None
        row[f"logprob{position}"] = None

    if record.outcome is not None:
        row.update(
            {
                "generated_response": record.outcome.generated_response,
                "comment": record.outcome.comment,
                "picks": json.dumps(record.outcome.picks, separators=(",", ":")),
                "error_type": None,
                "error_message": None,
            }
        )
        for position, (pick, logprob) in enumerate(
            zip(record.outcome.picks, record.outcome.logprobs, strict=True),
            start=1,
        ):
            row[f"pick{position}"] = pick
            row[f"logprob{position}"] = logprob
    return row


def _canonicalize_output(
    output_dataset: pd.DataFrame,
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> pd.DataFrame:
    rows_by_key = {
        _key_from_row(row): row
        for row in output_dataset.to_dict(orient="records")
    }
    ordered_rows = [
        rows_by_key[key]
        for key in build_experiment_job_keys(dataset, config)
        if key in rows_by_key
    ]
    return pd.DataFrame(
        ordered_rows,
        columns=_expected_columns(dataset, config),
    ).reset_index(drop=True)


def _row_is_complete(row: dict[str, object], config: ExperimentConfig) -> bool:
    if not _is_missing(row["error_type"]) or not _is_missing(row["error_message"]):
        return False
    if not _is_non_empty_string(row["generated_response"]):
        return False
    if not _is_non_empty_string(row["user_prompt"]):
        return False

    resume_count = len(config.dataset_schema.resume_columns)
    try:
        picks = json.loads(row["picks"]) if isinstance(row["picks"], str) else None
    except (TypeError, ValueError):
        return False
    if not isinstance(picks, list) or len(picks) != resume_count:
        return False
    if any(type(pick) is not int or pick not in {0, 1} for pick in picks):
        return False

    for position, expected_pick in enumerate(picks, start=1):
        stored_pick = row[f"pick{position}"]
        if not _is_finite_number(stored_pick) or int(stored_pick) != expected_pick:
            return False
        if stored_pick not in {0, 1}:
            return False
        if not _is_finite_number(row[f"logprob{position}"]):
            return False
    return True


def _key_from_row(row: dict[str, object]) -> ExperimentJobKey:
    values: dict[str, str] = {}
    for column in _IDENTITY_COLUMNS[:4]:
        value = row.get(column)
        if not _is_non_empty_string(value):
            raise ExperimentResultStoreError(
                f"output_dataset identity column {column!r} must be a non-empty string"
            )
        values[column] = value
    return ExperimentJobKey(**values)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
