"""Tests for complete inference input validation."""

from __future__ import annotations

import math

import pytest

from llm_auditkit.inference import (
    InferenceConfig,
    InferenceConfigurationError,
    InferenceRequest,
    InferenceRequestValidationError,
    ModelConfig,
)
from llm_auditkit.inference.validation import (
    validate_inference_config,
    validate_inference_inputs,
    validate_inference_requests,
)


def _model(**changes: object) -> ModelConfig:
    values: dict[str, object] = {
        "config_id": "model-1",
        "provider": "test",
        "model": "test-model",
        "parameters": {"temperature": 0.2, "response_format": {"type": "text"}},
    }
    values.update(changes)
    return ModelConfig(**values)  # type: ignore[arg-type]


def _config(**changes: object) -> InferenceConfig:
    values: dict[str, object] = {"models": [_model()], "batch_size": 10}
    values.update(changes)
    return InferenceConfig(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> InferenceRequest:
    values: dict[str, object] = {
        "request_id": "request-1",
        "prompt": "Assess this candidate.",
        "model_config_id": "model-1",
        "system_prompt": None,
        "metadata": {"row_id": "row-1"},
    }
    values.update(changes)
    return InferenceRequest(**values)  # type: ignore[arg-type]


def test_valid_inputs_and_empty_request_collection_are_accepted() -> None:
    config = _config()

    validate_inference_inputs([_request()], config)
    validate_inference_inputs([], config)


@pytest.mark.parametrize("batch_size", [True, 1.5, 0, -1])
def test_batch_size_must_be_a_positive_integer(batch_size: object) -> None:
    with pytest.raises(InferenceConfigurationError, match="batch_size"):
        validate_inference_config(_config(batch_size=batch_size))


def test_configuration_requires_at_least_one_model() -> None:
    with pytest.raises(InferenceConfigurationError, match="at least one"):
        validate_inference_config(_config(models=[]))


@pytest.mark.parametrize("field_name", ["config_id", "provider", "model"])
def test_model_identity_fields_must_be_non_empty(field_name: str) -> None:
    with pytest.raises(InferenceConfigurationError, match=field_name):
        validate_inference_config(_config(models=[_model(**{field_name: "  "})]))


def test_model_configuration_ids_must_be_unique() -> None:
    with pytest.raises(InferenceConfigurationError, match="duplicate"):
        validate_inference_config(_config(models=[_model(), _model(model="other")]))


@pytest.mark.parametrize(
    "parameter_name",
    ["model", "model_name", "service_name", "inference_service", "_inference_service_"],
)
def test_edsl_identity_fields_are_not_provider_parameters(
    parameter_name: str,
) -> None:
    with pytest.raises(InferenceConfigurationError, match="reserved EDSL"):
        validate_inference_config(
            _config(models=[_model(parameters={parameter_name: "override"})])
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"unsupported": object()},
        {"unsupported": ("tuple",)},
        {"unsupported": math.nan},
        {"unsupported": math.inf},
        {1: "non-string key"},
    ],
)
def test_model_parameters_must_be_json_compatible(parameters: object) -> None:
    with pytest.raises(InferenceConfigurationError, match="parameters"):
        validate_inference_config(_config(models=[_model(parameters=parameters)]))


def test_cyclic_model_parameters_are_rejected() -> None:
    parameters: dict[str, object] = {}
    parameters["cycle"] = parameters

    with pytest.raises(InferenceConfigurationError, match="cyclic"):
        validate_inference_config(_config(models=[_model(parameters=parameters)]))


@pytest.mark.parametrize("field_name", ["request_id", "prompt", "model_config_id"])
def test_required_request_strings_must_be_non_empty(field_name: str) -> None:
    with pytest.raises(InferenceRequestValidationError, match=field_name):
        validate_inference_requests([_request(**{field_name: "  "})], _config())


def test_request_ids_must_be_unique_across_the_complete_collection() -> None:
    with pytest.raises(InferenceRequestValidationError, match="duplicate"):
        validate_inference_requests(
            [_request(), _request(prompt="A different prompt")],
            _config(),
        )


def test_requests_must_reference_a_known_model_configuration() -> None:
    with pytest.raises(InferenceRequestValidationError, match="unknown model"):
        validate_inference_requests(
            [_request(model_config_id="missing")],
            _config(),
        )


def test_system_prompt_must_be_a_string_or_none() -> None:
    with pytest.raises(InferenceRequestValidationError, match="system_prompt"):
        validate_inference_requests([_request(system_prompt=123)], _config())


def test_empty_explicit_system_prompt_is_valid() -> None:
    validate_inference_requests([_request(system_prompt="")], _config())


@pytest.mark.parametrize("metadata", [[], {1: "non-string key"}])
def test_request_metadata_must_be_a_string_keyed_dictionary(metadata: object) -> None:
    with pytest.raises(InferenceRequestValidationError, match="metadata"):
        validate_inference_requests([_request(metadata=metadata)], _config())
