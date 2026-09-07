"""Validation for generic inference configuration and requests."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .exceptions import (
    InferenceConfigurationError,
    InferenceRequestValidationError,
)
from .models import InferenceConfig, InferenceRequest, JSONValue, ModelConfig


_RESERVED_MODEL_PARAMETERS = frozenset(
    {
        "_inference_service_",
        "inference_service",
        "model",
        "model_name",
        "service_name",
    }
)


def validate_inference_config(config: InferenceConfig) -> None:
    """Validate model definitions and logical batch size.

    Raises:
        InferenceConfigurationError: If any configuration value is invalid.
    """

    if not isinstance(config, InferenceConfig):
        raise InferenceConfigurationError("config must be an InferenceConfig")

    if isinstance(config.batch_size, bool) or not isinstance(config.batch_size, int):
        raise InferenceConfigurationError("batch_size must be an integer")
    if config.batch_size <= 0:
        raise InferenceConfigurationError("batch_size must be positive")

    if not _is_sequence(config.models):
        raise InferenceConfigurationError("models must be a sequence of ModelConfig values")
    if not config.models:
        raise InferenceConfigurationError("at least one model configuration is required")

    seen_config_ids: set[str] = set()
    for index, model_config in enumerate(config.models):
        _validate_model_config(model_config, index=index)
        if model_config.config_id in seen_config_ids:
            raise InferenceConfigurationError(
                f"duplicate model configuration ID: {model_config.config_id!r}"
            )
        seen_config_ids.add(model_config.config_id)


def validate_inference_requests(
    requests: Sequence[InferenceRequest],
    config: InferenceConfig,
) -> None:
    """Validate a complete request collection against inference configuration.

    The complete collection is checked before orchestration so duplicates or unknown
    model references cannot be discovered only after earlier batches have run.

    Raises:
        InferenceConfigurationError: If ``config`` is invalid.
        InferenceRequestValidationError: If any request is invalid.
    """

    validate_inference_config(config)

    if not _is_sequence(requests):
        raise InferenceRequestValidationError(
            "requests must be a sequence of InferenceRequest values"
        )

    known_model_ids = {model.config_id for model in config.models}
    seen_request_ids: set[str] = set()

    for index, request in enumerate(requests):
        if not isinstance(request, InferenceRequest):
            raise InferenceRequestValidationError(
                f"request at position {index} must be an InferenceRequest"
            )

        _require_non_empty_string(
            request.request_id,
            field_name=f"request at position {index} request_id",
            exception_type=InferenceRequestValidationError,
        )
        if request.request_id in seen_request_ids:
            raise InferenceRequestValidationError(
                f"duplicate request ID: {request.request_id!r}"
            )
        seen_request_ids.add(request.request_id)

        _require_non_empty_string(
            request.prompt,
            field_name=f"request {request.request_id!r} prompt",
            exception_type=InferenceRequestValidationError,
        )
        if request.system_prompt is not None and not isinstance(
            request.system_prompt, str
        ):
            raise InferenceRequestValidationError(
                f"request {request.request_id!r} system_prompt must be a string or None"
            )
        _require_non_empty_string(
            request.model_config_id,
            field_name=f"request {request.request_id!r} model_config_id",
            exception_type=InferenceRequestValidationError,
        )
        if request.model_config_id not in known_model_ids:
            raise InferenceRequestValidationError(
                f"request {request.request_id!r} references unknown model "
                f"configuration ID {request.model_config_id!r}"
            )

        if not isinstance(request.metadata, dict):
            raise InferenceRequestValidationError(
                f"request {request.request_id!r} metadata must be a dictionary"
            )
        invalid_metadata_keys = [
            key for key in request.metadata if not isinstance(key, str)
        ]
        if invalid_metadata_keys:
            raise InferenceRequestValidationError(
                f"request {request.request_id!r} metadata keys must be strings"
            )


def validate_inference_inputs(
    requests: Sequence[InferenceRequest],
    config: InferenceConfig,
) -> None:
    """Validate all generic inputs before the first inference batch is submitted."""

    validate_inference_requests(requests, config)


def _validate_model_config(model_config: ModelConfig, *, index: int) -> None:
    if not isinstance(model_config, ModelConfig):
        raise InferenceConfigurationError(
            f"model at position {index} must be a ModelConfig"
        )

    _require_non_empty_string(
        model_config.config_id,
        field_name=f"model at position {index} config_id",
        exception_type=InferenceConfigurationError,
    )
    _require_non_empty_string(
        model_config.provider,
        field_name=f"model {model_config.config_id!r} provider",
        exception_type=InferenceConfigurationError,
    )
    _require_non_empty_string(
        model_config.model,
        field_name=f"model {model_config.config_id!r} model",
        exception_type=InferenceConfigurationError,
    )

    if not isinstance(model_config.parameters, dict):
        raise InferenceConfigurationError(
            f"model {model_config.config_id!r} parameters must be a dictionary"
        )

    reserved_parameters = sorted(
        key for key in model_config.parameters if key in _RESERVED_MODEL_PARAMETERS
    )
    if reserved_parameters:
        names = ", ".join(repr(name) for name in reserved_parameters)
        raise InferenceConfigurationError(
            f"model {model_config.config_id!r} parameters contain reserved "
            f"EDSL model fields: {names}"
        )

    _validate_json_value(
        model_config.parameters,
        location=f"model {model_config.config_id!r} parameters",
        ancestors=set(),
    )


def _validate_json_value(
    value: JSONValue | object,
    *,
    location: str,
    ancestors: set[int],
) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            raise InferenceConfigurationError(
                f"{location} must not contain NaN or infinite numbers"
            )
        return

    if isinstance(value, (list, dict)):
        container_id = id(value)
        if container_id in ancestors:
            raise InferenceConfigurationError(
                f"{location} must not contain cyclic values"
            )
        ancestors.add(container_id)
        try:
            if isinstance(value, list):
                for index, item in enumerate(value):
                    _validate_json_value(
                        item,
                        location=f"{location}[{index}]",
                        ancestors=ancestors,
                    )
            else:
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise InferenceConfigurationError(
                            f"{location} must use string object keys"
                        )
                    _validate_json_value(
                        item,
                        location=f"{location}.{key}",
                        ancestors=ancestors,
                    )
        finally:
            ancestors.remove(container_id)
        return

    raise InferenceConfigurationError(
        f"{location} contains non-JSON-compatible value of type "
        f"{type(value).__name__}"
    )


def _require_non_empty_string(
    value: object,
    *,
    field_name: str,
    exception_type: type[InferenceConfigurationError]
    | type[InferenceRequestValidationError],
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise exception_type(f"{field_name} must be a non-empty string")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
