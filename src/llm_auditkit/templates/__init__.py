"""Public interfaces for configurable resume-template generation."""

from .exceptions import (
    TemplateGenerationConfigurationError,
    TemplateGenerationDatasetError,
    TemplateGenerationException,
    TemplateGenerationIdentityError,
    TemplateGenerationValidationError,
    TemplateResponseParseError,
    TemplateResultAssociationError,
    TemplateStoreError,
)
from .generator import TemplateGenerator
from .identity import build_template_request_id
from .models import (
    TemplateDatasetSchema,
    TemplateGenerationConfig,
    TemplateOutputRecord,
)
from .store import TemplateStore
from .validation import (
    validate_template_generation_config,
    validate_template_generation_dataset,
    validate_template_generation_inputs,
)

__all__ = [
    "TemplateDatasetSchema",
    "TemplateGenerationConfig",
    "TemplateGenerationConfigurationError",
    "TemplateGenerationDatasetError",
    "TemplateGenerationException",
    "TemplateGenerationIdentityError",
    "TemplateGenerationValidationError",
    "TemplateGenerator",
    "TemplateOutputRecord",
    "TemplateResponseParseError",
    "TemplateResultAssociationError",
    "TemplateStore",
    "TemplateStoreError",
    "build_template_request_id",
    "validate_template_generation_config",
    "validate_template_generation_dataset",
    "validate_template_generation_inputs",
]
