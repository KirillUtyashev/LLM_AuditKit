"""Orchestration for source loading, normalization, identity, and validation."""

from __future__ import annotations

import pandas as pd

from .exceptions import (
    DatasetIdentityError,
    DatasetLoadingException,
    DatasetSourceError,
)
from .identity import SCENARIO_ID_COLUMN, derive_scenario_ids
from .models import DatasetSchema
from .normalization import normalize_dataset
from .sources import DatasetSource
from .validation import DatasetValidator


class DatasetLoader:
    """Load any dataset source into the canonical pipeline DataFrame contract."""

    def __init__(self, schema: DatasetSchema) -> None:
        self._validator = DatasetValidator(schema)
        self.schema = schema

    def load(self, source: DatasetSource) -> pd.DataFrame:
        """Load, normalize, identify, and validate one complete source."""

        if not isinstance(source, DatasetSource):
            raise DatasetSourceError(
                "source must implement DatasetSource.load()"
            )
        try:
            raw_dataset = source.load()
        except DatasetLoadingException:
            raise
        except Exception as error:
            raise DatasetSourceError(
                f"dataset source failed: {type(error).__name__}: {error}"
            ) from error

        dataset = normalize_dataset(raw_dataset)
        scenario_ids = derive_scenario_ids(dataset)
        _validate_scenario_ids(scenario_ids)
        if SCENARIO_ID_COLUMN not in dataset.columns:
            dataset[SCENARIO_ID_COLUMN] = pd.array(scenario_ids, dtype="string")
        self._validator.validate(dataset)
        return dataset


def _validate_scenario_ids(scenario_ids: list[object]) -> None:
    if any(
        not isinstance(scenario_id, str) or not scenario_id.strip()
        for scenario_id in scenario_ids
    ):
        raise DatasetIdentityError(
            "scenario_id values must be non-empty strings"
        )
    if len(set(scenario_ids)) != len(scenario_ids):
        raise DatasetIdentityError(
            "scenario_id values must be unique; exact duplicate source rows require "
            "a stable replicate column"
        )
