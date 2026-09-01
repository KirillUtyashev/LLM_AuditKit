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


class ExperimentResultAssociationError(ExperimentException):
    """Raised when inference results cannot be safely associated with planned jobs."""


class ExperimentResponseParseError(ExperimentException):
    """Raised internally when one model response cannot become an experiment outcome."""
