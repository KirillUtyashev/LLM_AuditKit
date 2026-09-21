"""Public interfaces for normalized local and remote dataset loading."""

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
from .models import DatasetSchema, RemoteConfig
from .sources import DatasetSource, LocalDatasetSource, RemoteDatasetSource
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
    "RemoteConfig",
    "RemoteDatasetSource",
    "SCENARIO_ID_COLUMN",
    "build_scenario_id",
    "derive_scenario_ids",
]
