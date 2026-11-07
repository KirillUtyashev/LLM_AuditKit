"""Public interfaces for normalized local dataset loading."""

from .exceptions import (
    DatasetConfigurationError,
    DatasetIdentityError,
    DatasetLoadingException,
    DatasetNormalizationError,
    DatasetSourceError,
    DatasetValidationError,
    MissingOptionalColumnWarning,
)
from .identity import SCENARIO_ID_COLUMN, build_scenario_id, derive_scenario_ids
from .loader import DatasetLoader
from .models import DatasetSchema
from .sources import DatasetSource, LocalDatasetSource
from .validation import DatasetValidator

__all__ = [
    "DatasetConfigurationError",
    "DatasetIdentityError",
    "DatasetLoader",
    "DatasetLoadingException",
    "DatasetNormalizationError",
    "DatasetSchema",
    "DatasetSource",
    "DatasetSourceError",
    "DatasetValidationError",
    "DatasetValidator",
    "LocalDatasetSource",
    "MissingOptionalColumnWarning",
    "SCENARIO_ID_COLUMN",
    "build_scenario_id",
    "derive_scenario_ids",
]
