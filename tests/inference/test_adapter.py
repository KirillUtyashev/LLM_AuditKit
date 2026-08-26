"""Tests for the domain-neutral inference adapter contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from llm_auditkit.inference import (
    InferenceAdapter,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)


class FakeAdapter:
    """Minimal structural implementation used to verify the public protocol."""

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        return [
            RenderedPrompt(
                request_id=request.request_id,
                user_prompt=request.prompt,
                system_prompt=request.system_prompt,
            )
            for request in requests
        ]

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        return []

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        return []


def test_adapter_protocol_uses_structural_typing() -> None:
    assert isinstance(FakeAdapter(), InferenceAdapter)
