"""Tests for domain-neutral inference data models."""

from __future__ import annotations

from llm_auditkit.inference import (
    InferenceBatchPreview,
    InferenceBatchResult,
    InferenceConfig,
    InferenceError,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)


def test_model_and_request_defaults_are_independent() -> None:
    first_model = ModelConfig(config_id="first", provider="test", model="one")
    second_model = ModelConfig(config_id="second", provider="test", model="two")
    first_request = InferenceRequest(
        request_id="request-1",
        prompt="Prompt one",
        model_config_id="first",
    )
    second_request = InferenceRequest(
        request_id="request-2",
        prompt="Prompt two",
        model_config_id="second",
    )

    first_model.parameters["temperature"] = 0.1
    first_request.metadata["row_id"] = "row-1"

    assert second_model.parameters == {}
    assert second_request.metadata == {}


def test_generic_models_represent_preview_and_terminal_outcomes() -> None:
    model = ModelConfig(
        config_id="model-1",
        provider="test",
        model="test-model",
        parameters={"temperature": 0.2},
    )
    config = InferenceConfig(models=[model], batch_size=2)
    rendered = RenderedPrompt(
        request_id="request-1",
        user_prompt="Rendered user prompt",
        system_prompt="Rendered system prompt",
    )
    preview = InferenceBatchPreview(
        batch_number=1,
        total_batches=1,
        prompts=[rendered],
    )
    success = InferenceResult(
        request_id="request-1",
        model_config_id="model-1",
        content="response",
        metadata={"row_id": "row-1"},
    )
    failure = InferenceResult(
        request_id="request-2",
        model_config_id="model-1",
        content=None,
        metadata={"row_id": "row-2"},
        error=InferenceError(type="ProviderError", message="request failed"),
    )
    batch = InferenceBatchResult(
        batch_number=1,
        total_batches=1,
        elapsed_seconds=0.5,
        results=[success, failure],
    )

    assert config.models == [model]
    assert preview.prompts == [rendered]
    assert batch.results == [success, failure]
