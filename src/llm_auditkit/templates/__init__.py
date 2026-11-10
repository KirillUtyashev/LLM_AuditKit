"""Public interfaces for configurable resume-template generation."""

from .configuration import load_template_generation_run_config
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
    TemplateGenerationRunConfig,
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
    "TemplateGenerationRunConfig",
    "TemplateGenerationValidationError",
    "TemplateGenerator",
    "TemplateOutputRecord",
    "TemplateResponseParseError",
    "TemplateResultAssociationError",
    "TemplateStore",
    "TemplateStoreError",
    "build_template_request_id",
    "load_template_generation_run_config",
    "validate_template_generation_config",
    "validate_template_generation_dataset",
    "validate_template_generation_inputs",
]
