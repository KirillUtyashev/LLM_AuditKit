"""Exceptions raised by the shared inference layer."""

from __future__ import annotations


class InferenceException(Exception):
    """Base class for exceptions raised by shared inference."""


class InferenceValidationError(InferenceException):
    """Base class for invalid inference inputs."""


class InferenceConfigurationError(InferenceValidationError):
    """Raised when inference configuration is invalid."""


class InferenceRequestValidationError(InferenceValidationError):
    """Raised when an inference request collection is invalid."""


class InferenceBatchError(InferenceException):
    """Raised when a batch cannot produce a trustworthy normalized result set."""
