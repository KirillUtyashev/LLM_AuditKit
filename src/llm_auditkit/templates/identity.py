"""Stable request and configuration identity for template generation."""

from __future__ import annotations

import hashlib
import json

from .exceptions import (
    TemplateGenerationConfigurationError,
    TemplateGenerationIdentityError,
)
from .models import TemplateGenerationConfig


_FINGERPRINT_SCHEMA = "template-generation-v1"


def build_generation_fingerprint(config: TemplateGenerationConfig) -> str:
    """Hash every configuration value that can change generated template content."""

    models = [
        model
        for model in config.inference.models
        if model.config_id == config.model_config_id
    ]
    if len(models) != 1:
        raise TemplateGenerationConfigurationError(
            "model_config_id must reference exactly one inference model"
        )
    model = models[0]
    payload = {
        "schema": _FINGERPRINT_SCHEMA,
        "templates_per_scenario": config.templates_per_scenario,
        "dataset_schema": {
            "job_posting_column": config.dataset_schema.job_posting_column,
            "context_columns": dict(
                sorted(config.dataset_schema.context_columns.items())
            ),
        },
        "prompt_template": config.prompt_template,
        "system_prompt_template": config.system_prompt_template,
        "required_placeholders": list(config.required_placeholders),
        "model": {
            "config_id": model.config_id,
            "provider": model.provider,
            "model": model.model,
            "parameters": model.parameters,
        },
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TemplateGenerationConfigurationError(
            f"generation-defining configuration must be JSON-compatible: {error}"
        ) from error
    return f"template-generation:{hashlib.sha256(encoded).hexdigest()}"


def build_template_request_id(scenario_id: str, generation_fingerprint: str) -> str:
    """Derive one stable request ID from scenario and generation identity."""

    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise TemplateGenerationIdentityError(
            "scenario_id must be a non-empty string"
        )
    if (
        not isinstance(generation_fingerprint, str)
        or not generation_fingerprint.strip()
    ):
        raise TemplateGenerationIdentityError(
            "generation_fingerprint must be a non-empty string"
        )
    encoded = json.dumps(
        [scenario_id, generation_fingerprint],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"template-request:{hashlib.sha256(encoded).hexdigest()}"
