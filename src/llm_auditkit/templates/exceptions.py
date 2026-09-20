"""Exceptions raised by resume-template generation."""

from __future__ import annotations


class TemplateGenerationException(Exception):
    """Base class for template-generation errors."""


class TemplateGenerationValidationError(TemplateGenerationException):
    """Base class for invalid generation inputs."""


class TemplateGenerationConfigurationError(TemplateGenerationValidationError):
    """Raised when template-generation configuration is invalid."""


class TemplateGenerationDatasetError(TemplateGenerationValidationError):
    """Raised when an input DataFrame violates its configured schema."""


class TemplateGenerationIdentityError(TemplateGenerationValidationError):
    """Raised when stable generation identity cannot be constructed safely."""


class TemplateResultAssociationError(TemplateGenerationException):
    """Raised when inference results cannot be associated with planned scenarios."""


class TemplateResponseParseError(TemplateGenerationException):
    """Raised internally when one normalized result contains invalid templates."""


class TemplateStoreError(TemplateGenerationException):
    """Raised when template output cannot be validated or persisted safely."""
