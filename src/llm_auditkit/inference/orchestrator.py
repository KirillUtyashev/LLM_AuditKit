"""Validation, batching, and result verification for shared inference."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from time import perf_counter

from .adapter import InferenceAdapter
from .batching import RequestBatch, build_request_batches
from .exceptions import InferenceBatchError, InferenceValidationError
from .models import (
    InferenceBatchPreview,
    InferenceBatchResult,
    InferenceConfig,
    InferenceError,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)
from .validation import validate_inference_inputs


class InferenceOrchestrator:
    """Coordinate validated logical batches through an inference adapter."""

    def __init__(self, adapter: InferenceAdapter) -> None:
        self._adapter = adapter

    def preview_batch(
        self,
        requests: Sequence[InferenceRequest],
        config: InferenceConfig,
        batch_number: int = 1,
    ) -> InferenceBatchPreview:
        """Render one selected logical batch without performing inference."""

        models, batches = self._prepare(requests, config)
        batch = _select_preview_batch(batches, batch_number)

        try:
            rendered_prompts = self._adapter.render_batch(batch.requests, models)
        except InferenceBatchError:
            raise
        except Exception as error:
            raise InferenceBatchError(
                f"inference adapter failed to render logical batch "
                f"{batch.batch_number}: {type(error).__name__}: {error}"
            ) from error

        return InferenceBatchPreview(
            batch_number=batch.batch_number,
            total_batches=batch.total_batches,
            prompts=_verify_rendered_prompts(batch.requests, rendered_prompts),
        )

    def run_batches(
        self,
        requests: Sequence[InferenceRequest],
        config: InferenceConfig,
    ) -> Iterator[InferenceBatchResult]:
        """Return a lazy blocking iterator over normalized logical batches."""

        models, batches = self._prepare(requests, config)
        return self._run_prepared_batches(batches, models)

    def run_batches_async(
        self,
        requests: Sequence[InferenceRequest],
        config: InferenceConfig,
    ) -> AsyncIterator[InferenceBatchResult]:
        """Return a lazy async iterator over normalized logical batches."""

        models, batches = self._prepare(requests, config)
        return self._run_prepared_batches_async(batches, models)

    def _prepare(
        self,
        requests: Sequence[InferenceRequest],
        config: InferenceConfig,
    ) -> tuple[dict[str, ModelConfig], tuple[RequestBatch, ...]]:
        validate_inference_inputs(requests, config)
        models = {model.config_id: model for model in config.models}
        batches = build_request_batches(requests, config.batch_size)
        return models, batches

    def _run_prepared_batches(
        self,
        batches: Sequence[RequestBatch],
        models: Mapping[str, ModelConfig],
    ) -> Iterator[InferenceBatchResult]:
        for batch in batches:
            started_at = perf_counter()
            try:
                adapter_results = self._adapter.execute_batch(batch.requests, models)
            except InferenceBatchError:
                raise
            except Exception as error:
                raise InferenceBatchError(
                    f"inference adapter failed to execute logical batch "
                    f"{batch.batch_number}: {type(error).__name__}: {error}"
                ) from error
            elapsed_seconds = perf_counter() - started_at

            yield InferenceBatchResult(
                batch_number=batch.batch_number,
                total_batches=batch.total_batches,
                elapsed_seconds=elapsed_seconds,
                results=_verify_results(batch.requests, adapter_results),
            )

    async def _run_prepared_batches_async(
        self,
        batches: Sequence[RequestBatch],
        models: Mapping[str, ModelConfig],
    ) -> AsyncIterator[InferenceBatchResult]:
        for batch in batches:
            started_at = perf_counter()
            try:
                adapter_results = await self._adapter.execute_batch_async(
                    batch.requests,
                    models,
                )
            except InferenceBatchError:
                raise
            except Exception as error:
                raise InferenceBatchError(
                    f"inference adapter failed to execute logical batch "
                    f"{batch.batch_number}: {type(error).__name__}: {error}"
                ) from error
            elapsed_seconds = perf_counter() - started_at

            yield InferenceBatchResult(
                batch_number=batch.batch_number,
                total_batches=batch.total_batches,
                elapsed_seconds=elapsed_seconds,
                results=_verify_results(batch.requests, adapter_results),
            )


def _select_preview_batch(
    batches: Sequence[RequestBatch],
    batch_number: int,
) -> RequestBatch:
    if isinstance(batch_number, bool) or not isinstance(batch_number, int):
        raise InferenceValidationError("batch_number must be an integer")
    if batch_number <= 0:
        raise InferenceValidationError("batch_number must be positive")
    if not batches:
        raise InferenceValidationError("cannot preview an empty request collection")
    if batch_number > len(batches):
        raise InferenceValidationError(
            f"batch_number {batch_number} exceeds total batches {len(batches)}"
        )
    return batches[batch_number - 1]


def _verify_rendered_prompts(
    requests: Sequence[InferenceRequest],
    rendered_prompts: object,
) -> list[RenderedPrompt]:
    if not _is_result_sequence(rendered_prompts):
        raise InferenceBatchError(
            "inference adapter must return a sequence of RenderedPrompt values"
        )
    if len(rendered_prompts) != len(requests):
        raise InferenceBatchError(
            "rendered prompt cardinality does not match the submitted request batch"
        )

    expected_by_id = {request.request_id: request for request in requests}
    rendered_by_id: dict[str, RenderedPrompt] = {}

    for position, rendered_prompt in enumerate(rendered_prompts):
        if not isinstance(rendered_prompt, RenderedPrompt):
            raise InferenceBatchError(
                f"rendered prompt at position {position} must be a RenderedPrompt"
            )
        if rendered_prompt.request_id not in expected_by_id:
            raise InferenceBatchError(
                f"rendered prompt contains unknown request ID "
                f"{rendered_prompt.request_id!r}"
            )
        if rendered_prompt.request_id in rendered_by_id:
            raise InferenceBatchError(
                f"rendered prompt contains duplicate request ID "
                f"{rendered_prompt.request_id!r}"
            )
        if not isinstance(rendered_prompt.user_prompt, str) or not (
            rendered_prompt.user_prompt.strip()
        ):
            raise InferenceBatchError(
                f"rendered prompt for request {rendered_prompt.request_id!r} "
                "must contain a non-empty user prompt"
            )
        if rendered_prompt.system_prompt is not None and not isinstance(
            rendered_prompt.system_prompt,
            str,
        ):
            raise InferenceBatchError(
                f"rendered prompt for request {rendered_prompt.request_id!r} "
                "must contain a string system prompt or None"
            )
        rendered_by_id[rendered_prompt.request_id] = rendered_prompt

    return [rendered_by_id[request.request_id] for request in requests]


def _verify_results(
    requests: Sequence[InferenceRequest],
    results: object,
) -> list[InferenceResult]:
    if not _is_result_sequence(results):
        raise InferenceBatchError(
            "inference adapter must return a sequence of InferenceResult values"
        )
    if len(results) != len(requests):
        raise InferenceBatchError(
            "result cardinality does not match the submitted request batch"
        )

    expected_by_id = {request.request_id: request for request in requests}
    results_by_id: dict[str, InferenceResult] = {}

    for position, result in enumerate(results):
        if not isinstance(result, InferenceResult):
            raise InferenceBatchError(
                f"result at position {position} must be an InferenceResult"
            )
        if result.request_id not in expected_by_id:
            raise InferenceBatchError(
                f"result contains unknown request ID {result.request_id!r}"
            )
        if result.request_id in results_by_id:
            raise InferenceBatchError(
                f"result contains duplicate request ID {result.request_id!r}"
            )

        request = expected_by_id[result.request_id]
        if result.model_config_id != request.model_config_id:
            raise InferenceBatchError(
                f"result for request {result.request_id!r} has model configuration "
                f"ID {result.model_config_id!r}; expected {request.model_config_id!r}"
            )
        _verify_terminal_outcome(result)

        results_by_id[result.request_id] = InferenceResult(
            request_id=result.request_id,
            model_config_id=request.model_config_id,
            content=result.content,
            metadata=dict(request.metadata),
            error=result.error,
        )

    return [results_by_id[request.request_id] for request in requests]


def _verify_terminal_outcome(result: InferenceResult) -> None:
    if result.content is not None and not isinstance(result.content, str):
        raise InferenceBatchError(
            f"result for request {result.request_id!r} content must be a string or None"
        )
    if result.error is not None and not isinstance(result.error, InferenceError):
        raise InferenceBatchError(
            f"result for request {result.request_id!r} error must be an InferenceError "
            "or None"
        )
    if result.content is None and result.error is None:
        raise InferenceBatchError(
            f"result for request {result.request_id!r} has neither content nor error"
        )
    if result.content is not None and result.error is not None:
        raise InferenceBatchError(
            f"result for request {result.request_id!r} has both content and error"
        )
    if result.error is not None:
        if not isinstance(result.error.type, str) or not result.error.type.strip():
            raise InferenceBatchError(
                f"result for request {result.request_id!r} error type must be "
                "a non-empty string"
            )
        if not isinstance(result.error.message, str) or not result.error.message.strip():
            raise InferenceBatchError(
                f"result for request {result.request_id!r} error message must be "
                "a non-empty string"
            )


def _is_result_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )
