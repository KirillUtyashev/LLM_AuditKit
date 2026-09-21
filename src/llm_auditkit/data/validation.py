"""Configurable validation for normalized pipeline datasets."""

from __future__ import annotations

import warnings

import pandas as pd

from .exceptions import (
    DatasetConfigurationError,
    DatasetValidationError,
    MissingOptionalColumnWarning,
)
from .identity import SCENARIO_ID_COLUMN
from .models import DatasetSchema


class DatasetValidator:
    """Validate required fields and warn about optional stage inputs."""

    def __init__(self, schema: DatasetSchema) -> None:
        _validate_schema(schema)
        self.schema = schema

    def validate(self, dataset: pd.DataFrame) -> None:
        """Validate one normalized DataFrame against the configured schema."""

        _validate_schema(self.schema)
        if not isinstance(dataset, pd.DataFrame):
            raise DatasetValidationError("dataset must be a pandas DataFrame")
        if not dataset.columns.is_unique:
            raise DatasetValidationError("dataset column names must be unique")
        if any(
            not isinstance(column, str) or not column.strip()
            for column in dataset.columns
        ):
            raise DatasetValidationError(
                "dataset column names must be non-empty strings"
            )

        missing = [
            column
            for column in self.schema.required_columns
            if column not in dataset.columns
        ]
        if missing:
            rendered = ", ".join(repr(column) for column in missing)
            raise DatasetValidationError(
                f"dataset is missing required columns: {rendered}"
            )

        for column in self.schema.nonempty_columns:
            invalid_positions = [
                position
                for position, value in enumerate(dataset[column].tolist())
                if not isinstance(value, str) or not value.strip()
            ]
            if invalid_positions:
                raise DatasetValidationError(
                    f"required dataset column {column!r} must contain non-empty "
                    "strings"
                )

        for column, impact in self.schema.optional_columns.items():
            if column not in dataset.columns:
                warnings.warn(
                    f"dataset is missing optional column {column!r}; {impact}",
                    MissingOptionalColumnWarning,
                    stacklevel=2,
                )


def _validate_schema(schema: DatasetSchema) -> None:
    if not isinstance(schema, DatasetSchema):
        raise DatasetConfigurationError("schema must be a DatasetSchema")
    _validate_column_list(
        schema.required_columns,
        "required_columns",
        allow_empty=False,
    )
    _validate_column_list(
        schema.nonempty_columns,
        "nonempty_columns",
        allow_empty=True,
    )
    if not isinstance(schema.optional_columns, dict) or any(
        not isinstance(column, str)
        or not column.strip()
        or not isinstance(impact, str)
        or not impact.strip()
        for column, impact in schema.optional_columns.items()
    ):
        raise DatasetConfigurationError(
            "optional_columns must map non-empty column names to non-empty impacts"
        )

    required = set(schema.required_columns)
    nonempty = set(schema.nonempty_columns)
    optional = set(schema.optional_columns)
    if not nonempty.issubset(required):
        raise DatasetConfigurationError(
            "nonempty_columns must also appear in required_columns"
        )
    if required.intersection(optional):
        raise DatasetConfigurationError(
            "required_columns and optional_columns must not overlap"
        )
    if SCENARIO_ID_COLUMN in required | nonempty | optional:
        raise DatasetConfigurationError(
            "scenario_id is reserved for the dataset identity contract"
        )


def _validate_column_list(
    value: object,
    label: str,
    *,
    allow_empty: bool,
) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise DatasetConfigurationError(f"{label} must be {qualifier}")
    if any(not isinstance(column, str) or not column.strip() for column in value):
        raise DatasetConfigurationError(
            f"{label} must contain non-empty strings"
        )
    if len(set(value)) != len(value):
        raise DatasetConfigurationError(f"{label} must contain unique columns")
