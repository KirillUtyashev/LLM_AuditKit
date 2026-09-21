"""Canonical DataFrame output, checkpoint, and resume storage for templates."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from llm_auditkit.data.identity import SCENARIO_ID_COLUMN, derive_scenario_ids

from .exceptions import TemplateResponseParseError, TemplateStoreError
from .identity import build_generation_fingerprint, build_template_request_id
from .models import TemplateGenerationConfig, TemplateOutputRecord
from .parsing import validate_template_contents
from .validation import validate_template_generation_inputs


_FINGERPRINT_COLUMN = "template_generation_fingerprint"
_MODEL_COLUMN = "template_generation_model_config_id"
_REQUEST_COLUMN = "template_generation_request_id"
_ERROR_TYPE_COLUMN = "template_generation_error_type"
_ERROR_MESSAGE_COLUMN = "template_generation_error_message"
_METADATA_COLUMNS = [_FINGERPRINT_COLUMN, _MODEL_COLUMN, _REQUEST_COLUMN]
_ERROR_COLUMNS = [_ERROR_TYPE_COLUMN, _ERROR_MESSAGE_COLUMN]
_RESERVED_STATIC_COLUMNS = set(_METADATA_COLUMNS + _ERROR_COLUMNS)
_DYNAMIC_TEMPLATE_COLUMN = re.compile(r"template_[1-9][0-9]*\Z")


class TemplateStore:
    """Own a canonical template CSV and its atomic checkpoint operations."""

    def __init__(self, output_path: str | Path) -> None:
        if not isinstance(output_path, (str, Path)) or not str(output_path).strip():
            raise TemplateStoreError("output_path must be a non-empty string or Path")
        self.output_path = Path(output_path)
        if self.output_path.suffix.lower() != ".csv":
            raise TemplateStoreError("output_path must reference a .csv file")
        if self.output_path.exists() and self.output_path.is_dir():
            raise TemplateStoreError("output_path must not be a directory")

    def initialize(
        self,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> pd.DataFrame:
        """Create canonical pending rows or validate and restore a checkpoint."""

        validate_template_generation_inputs(dataset, config)
        _validate_source_columns(dataset, config)
        expected_columns = _expected_columns(dataset, config)
        if not self.output_path.exists():
            return _new_output(dataset, config)
        return self._read_existing(expected_columns, dataset, config)

    def completed_scenario_ids(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> set[str]:
        """Return scenario IDs with complete compatible successful templates."""

        _validate_output(output_dataset, dataset, config)
        return {
            row[SCENARIO_ID_COLUMN]
            for row in output_dataset.to_dict(orient="records")
            if _row_is_complete(row, config)
        }

    def apply_result(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
        record: TemplateOutputRecord,
    ) -> pd.DataFrame:
        """Apply one validated result in memory and preserve canonical row order."""

        _validate_output(output_dataset, dataset, config)
        _validate_record(record, output_dataset, config)
        updated = output_dataset.copy(deep=True)
        matches = updated.index[
            updated[SCENARIO_ID_COLUMN] == record.scenario_id
        ].tolist()
        if len(matches) != 1:
            raise TemplateStoreError(
                "template output must contain exactly one row for a result scenario"
            )
        row_index = matches[0]
        existing_row = updated.loc[row_index].to_dict()
        if _row_is_complete(existing_row, config):
            raise TemplateStoreError("a completed template row cannot be overwritten")

        template_columns = _template_columns(config)
        if record.is_successful:
            assert record.templates is not None
            for column, value in zip(
                template_columns,
                record.templates,
                strict=True,
            ):
                updated.at[row_index, column] = value
            updated.at[row_index, _ERROR_TYPE_COLUMN] = None
            updated.at[row_index, _ERROR_MESSAGE_COLUMN] = None
        else:
            for column in template_columns:
                updated.at[row_index, column] = None
            updated.at[row_index, _ERROR_TYPE_COLUMN] = record.error_type
            updated.at[row_index, _ERROR_MESSAGE_COLUMN] = record.error_message
        return updated.reset_index(drop=True)

    def save_result(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
        record: TemplateOutputRecord,
    ) -> pd.DataFrame:
        """Apply one handled result and atomically checkpoint it."""

        updated = self.apply_result(output_dataset, dataset, config, record)
        self.save(updated)
        return updated

    def apply_results(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
        records: Sequence[TemplateOutputRecord],
    ) -> pd.DataFrame:
        """Apply a sequence in memory without persistence."""

        updated = output_dataset
        for record in records:
            updated = self.apply_result(updated, dataset, config, record)
        return updated

    def save(self, output_dataset: pd.DataFrame) -> None:
        """Persist one complete in-memory snapshot using atomic replacement."""

        if not isinstance(output_dataset, pd.DataFrame):
            raise TemplateStoreError("output_dataset must be a pandas DataFrame")
        if not output_dataset.columns.is_unique:
            raise TemplateStoreError(
                "output_dataset column names must be unique before saving"
            )
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
            raise TemplateStoreError(
                f"could not atomically save template CSV: {type(error).__name__}: "
                f"{error}"
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _read_existing(
        self,
        expected_columns: list[str],
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> pd.DataFrame:
        try:
            header = pd.read_csv(self.output_path, nrows=0)
            if list(header.columns) != expected_columns:
                raise TemplateStoreError(
                    "existing template CSV columns do not match the current dataset "
                    "and generation configuration"
                )
            existing = pd.read_csv(
                self.output_path,
                dtype="string",
                keep_default_na=False,
            )
            restored = _restore_checkpoint(existing, dataset, config)
            _validate_output(restored, dataset, config)
            return restored
        except TemplateStoreError:
            raise
        except Exception as error:
            raise TemplateStoreError(
                f"could not read existing template CSV: {type(error).__name__}: "
                f"{error}"
            ) from error


def _new_output(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> pd.DataFrame:
    output = dataset.copy(deep=True).reset_index(drop=True)
    scenario_ids = derive_scenario_ids(dataset)
    if SCENARIO_ID_COLUMN not in output.columns:
        output[SCENARIO_ID_COLUMN] = scenario_ids
    fingerprint = build_generation_fingerprint(config)
    output[_FINGERPRINT_COLUMN] = fingerprint
    output[_MODEL_COLUMN] = config.model_config_id
    output[_REQUEST_COLUMN] = [
        build_template_request_id(scenario_id, fingerprint)
        for scenario_id in scenario_ids
    ]
    for column in _template_columns(config) + _ERROR_COLUMNS:
        output[column] = None
    return output[_expected_columns(dataset, config)]


def _expected_columns(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> list[str]:
    source_columns = list(dataset.columns)
    if SCENARIO_ID_COLUMN not in source_columns:
        source_columns.append(SCENARIO_ID_COLUMN)
    return (
        source_columns
        + _METADATA_COLUMNS
        + _template_columns(config)
        + _ERROR_COLUMNS
    )


def _source_columns(dataset: pd.DataFrame) -> list[str]:
    columns = list(dataset.columns)
    if SCENARIO_ID_COLUMN not in columns:
        columns.append(SCENARIO_ID_COLUMN)
    return columns


def _template_columns(config: TemplateGenerationConfig) -> list[str]:
    return [
        f"template_{position}"
        for position in range(1, config.templates_per_scenario + 1)
    ]


def _validate_source_columns(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> None:
    for column in dataset.columns:
        if column == SCENARIO_ID_COLUMN:
            continue
        if (
            column in _RESERVED_STATIC_COLUMNS
            or _DYNAMIC_TEMPLATE_COLUMN.fullmatch(column)
        ):
            raise TemplateStoreError(
                f"source column {column!r} conflicts with a template output column"
            )


def _restore_checkpoint(
    existing: pd.DataFrame,
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> pd.DataFrame:
    base = _new_output(dataset, config)
    source_columns = _source_columns(dataset)
    comparison_columns = source_columns + _METADATA_COLUMNS

    serialized_buffer = StringIO()
    base[comparison_columns].to_csv(serialized_buffer, index=False)
    serialized_buffer.seek(0)
    serialized_base = pd.read_csv(
        serialized_buffer,
        dtype="string",
        keep_default_na=False,
    )

    existing_ids = existing[SCENARIO_ID_COLUMN].tolist()
    if any(not isinstance(value, str) or not value for value in existing_ids):
        raise TemplateStoreError(
            "existing template CSV contains an invalid scenario_id"
        )
    if len(set(existing_ids)) != len(existing_ids):
        raise TemplateStoreError(
            "existing template CSV contains duplicate scenario_id values"
        )
    current_ids = serialized_base[SCENARIO_ID_COLUMN].tolist()
    if set(existing_ids) != set(current_ids):
        raise TemplateStoreError(
            "existing template CSV scenario IDs do not match the current dataset"
        )

    existing_by_id = {
        row[SCENARIO_ID_COLUMN]: row
        for row in existing.to_dict(orient="records")
    }
    serialized_by_id = {
        row[SCENARIO_ID_COLUMN]: row
        for row in serialized_base.to_dict(orient="records")
    }
    restored = base.copy(deep=True)
    result_columns = _template_columns(config) + _ERROR_COLUMNS
    for row_index, scenario_id in enumerate(current_ids):
        saved = existing_by_id[scenario_id]
        expected = serialized_by_id[scenario_id]
        for column in comparison_columns:
            if saved[column] != expected[column]:
                raise TemplateStoreError(
                    "existing template CSV source or generation metadata does not "
                    "match the current dataset and configuration"
                )
        for column in result_columns:
            value = saved[column]
            restored.at[row_index, column] = None if value == "" else value
        _validate_checkpoint_row(restored.loc[row_index].to_dict(), config)
    return restored


def _validate_output(
    output_dataset: pd.DataFrame,
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> None:
    validate_template_generation_inputs(dataset, config)
    _validate_source_columns(dataset, config)
    if not isinstance(output_dataset, pd.DataFrame):
        raise TemplateStoreError("output_dataset must be a pandas DataFrame")
    if list(output_dataset.columns) != _expected_columns(dataset, config):
        raise TemplateStoreError(
            "output_dataset columns do not match the current dataset and configuration"
        )
    expected_ids = derive_scenario_ids(dataset)
    actual_ids = output_dataset[SCENARIO_ID_COLUMN].tolist()
    if actual_ids != expected_ids:
        raise TemplateStoreError(
            "output_dataset rows do not match canonical scenario order"
        )
    fingerprint = build_generation_fingerprint(config)
    for row in output_dataset.to_dict(orient="records"):
        scenario_id = row[SCENARIO_ID_COLUMN]
        if row[_FINGERPRINT_COLUMN] != fingerprint:
            raise TemplateStoreError("template generation fingerprint does not match")
        if row[_MODEL_COLUMN] != config.model_config_id:
            raise TemplateStoreError("template model configuration does not match")
        if row[_REQUEST_COLUMN] != build_template_request_id(scenario_id, fingerprint):
            raise TemplateStoreError("template request identity does not match")
        _validate_checkpoint_row(row, config)


def _validate_checkpoint_row(
    row: dict[str, object],
    config: TemplateGenerationConfig,
) -> None:
    templates = [row[column] for column in _template_columns(config)]
    error_type = row[_ERROR_TYPE_COLUMN]
    error_message = row[_ERROR_MESSAGE_COLUMN]
    has_templates = [
        isinstance(value, str) and bool(value.strip()) for value in templates
    ]
    has_error_type = isinstance(error_type, str) and bool(error_type.strip())
    has_error_message = isinstance(error_message, str) and bool(error_message.strip())

    if not any(has_templates) and not has_error_type and not has_error_message:
        return
    if not any(has_templates) and has_error_type and has_error_message:
        return
    if all(has_templates) and not has_error_type and not has_error_message:
        try:
            validate_template_contents(
                [str(value).strip() for value in templates],
                config.required_placeholders,
            )
        except TemplateResponseParseError as error:
            raise TemplateStoreError(
                f"existing template CSV contains invalid template content: {error}"
            ) from error
        return
    raise TemplateStoreError(
        "existing template CSV row must be pending, failed, or completely successful"
    )


def _row_is_complete(
    row: dict[str, object],
    config: TemplateGenerationConfig,
) -> bool:
    return (
        all(
            isinstance(row[column], str) and bool(row[column].strip())
            for column in _template_columns(config)
        )
        and row[_ERROR_TYPE_COLUMN] is None
        and row[_ERROR_MESSAGE_COLUMN] is None
    )


def _validate_record(
    record: TemplateOutputRecord,
    output_dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
) -> None:
    if not isinstance(record, TemplateOutputRecord):
        raise TemplateStoreError("record must be a TemplateOutputRecord")
    fingerprint = build_generation_fingerprint(config)
    if record.generation_fingerprint != fingerprint:
        raise TemplateStoreError("record generation fingerprint does not match")
    if record.model_config_id != config.model_config_id:
        raise TemplateStoreError("record model configuration does not match")
    if record.request_id != build_template_request_id(record.scenario_id, fingerprint):
        raise TemplateStoreError("record request identity does not match")
    if record.scenario_id not in set(output_dataset[SCENARIO_ID_COLUMN]):
        raise TemplateStoreError("record scenario_id does not belong to the output")

    if record.is_successful:
        assert record.templates is not None
        if len(record.templates) != config.templates_per_scenario:
            raise TemplateStoreError(
                "successful record template count does not match configuration"
            )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in record.templates
        ):
            raise TemplateStoreError(
                "successful record templates must be non-empty strings"
            )
        try:
            validate_template_contents(
                [value.strip() for value in record.templates],
                config.required_placeholders,
            )
        except TemplateResponseParseError as error:
            raise TemplateStoreError(
                f"record contains invalid templates: {error}"
            ) from error
        return
    if record.templates is not None:
        raise TemplateStoreError("failed record must not contain templates")
    if (
        not isinstance(record.error_type, str)
        or not record.error_type.strip()
        or not isinstance(record.error_message, str)
        or not record.error_message.strip()
    ):
        raise TemplateStoreError(
            "failed record must contain non-empty error type and message"
        )
