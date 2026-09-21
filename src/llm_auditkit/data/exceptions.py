"""Exceptions and warnings for dataset loading."""

from __future__ import annotations


class DatasetLoadingException(Exception):
    """Base class for dataset-loading failures."""


class DatasetConfigurationError(DatasetLoadingException):
    """Raised when a dataset source or validation schema is invalid."""


class DatasetSourceError(DatasetLoadingException):
    """Raised when a local or remote source cannot produce a table."""


class DatasetNormalizationError(DatasetLoadingException):
    """Raised when a source table cannot satisfy the normalized contract."""


class DatasetValidationError(DatasetLoadingException):
    """Raised when a normalized table violates its configured schema."""


class DatasetIdentityError(DatasetValidationError):
    """Raised when durable scenario identity cannot be established safely."""


class MissingOptionalColumnWarning(UserWarning):
    """Warn that an absent optional column changes downstream behavior."""
