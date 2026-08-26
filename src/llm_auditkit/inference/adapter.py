"""Domain-neutral execution boundary for inference backends."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from .models import InferenceRequest, InferenceResult, ModelConfig, RenderedPrompt


@runtime_checkable
class InferenceAdapter(Protocol):
    """Backend contract consumed by the inference orchestrator.

    Implementations translate generic requests and model configuration into their
    backend's native objects. Backend-specific values must not cross this boundary.
    """

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        """Render one logical batch without performing inference."""

        ...

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        """Execute one logical batch synchronously."""

        ...

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        """Execute one logical batch asynchronously."""

        ...
