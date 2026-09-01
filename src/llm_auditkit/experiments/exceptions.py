"""Exceptions raised by experiment configuration and input validation."""

from __future__ import annotations


class ExperimentException(Exception):
    """Base class for exceptions raised by experiment execution."""


class ExperimentValidationError(ExperimentException):
    """Base class for invalid experiment inputs."""


class ExperimentConfigurationError(ExperimentValidationError):
    """Raised when experiment configuration is invalid."""


class ExperimentDatasetError(ExperimentValidationError):
    """Raised when an experiment DataFrame violates its configured schema."""


class ExperimentIdentityError(ExperimentValidationError):
    """Raised when a durable experiment job identity is invalid."""
