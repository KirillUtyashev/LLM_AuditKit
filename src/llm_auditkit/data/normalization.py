"""Normalize source DataFrames into the pipeline's scalar string contract."""

from __future__ import annotations

import pandas as pd

from .exceptions import DatasetNormalizationError


def normalize_dataset(dataset: pd.DataFrame) -> pd.DataFrame:
    """Return a normalized copy without relying on source index or scalar types."""

    if not isinstance(dataset, pd.DataFrame):
        raise DatasetNormalizationError(
            "dataset source must return a pandas DataFrame"
        )
    if not dataset.columns.is_unique:
        raise DatasetNormalizationError("dataset column names must be unique")
    if any(
        not isinstance(column, str) or not column.strip()
        for column in dataset.columns
    ):
        raise DatasetNormalizationError(
            "dataset column names must be non-empty strings"
        )

    normalized = pd.DataFrame(index=range(len(dataset)))
    for column in dataset.columns:
        values = [
            _normalize_scalar(value, column, row_position)
            for row_position, value in enumerate(dataset[column].tolist())
        ]
        normalized[column] = pd.array(values, dtype="string")
    return normalized.reset_index(drop=True)


def _normalize_scalar(value: object, column: str, row_position: int) -> object:
    if value is None:
        return pd.NA
    if pd.api.types.is_scalar(value):
        try:
            if pd.isna(value):
                return pd.NA
        except (TypeError, ValueError):
            pass
        return str(value)
    raise DatasetNormalizationError(
        f"dataset cell in column {column!r} at row position {row_position} "
        "must be a scalar value"
    )
