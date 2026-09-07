"""Tests for synchronous and asynchronous inference orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence

import pytest

from llm_auditkit.inference import (
    InferenceBatchError,
    InferenceConfig,
    InferenceError,
    InferenceOrchestrator,
    InferenceRequest,
    InferenceRequestValidationError,
    InferenceResult,
    InferenceValidationError,
    ModelConfig,
    RenderedPrompt,
)


class RecordingAdapter:
    def __init__(self) -> None:
        self.render_calls: list[list[str]] = []
        self.sync_calls: list[list[str]] = []
        self.async_calls: list[list[str]] = []

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        self.render_calls.append([request.request_id for request in requests])
        return [
            RenderedPrompt(
                request_id=request.request_id,
                user_prompt=f"rendered:{request.prompt}",
                system_prompt=request.system_prompt,
            )
            for request in reversed(requests)
        ]

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        self.sync_calls.append([request.request_id for request in requests])
        return _successful_results(reversed(requests))

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        self.async_calls.append([request.request_id for request in requests])
        return _successful_results(reversed(requests))


class FixedResultsAdapter(RecordingAdapter):
    def __init__(self, results: object) -> None:
        super().__init__()
        self.results = results

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        self.render_calls.append([request.request_id for request in requests])
        return self.results  # type: ignore[return-value]

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        self.sync_calls.append([request.request_id for request in requests])
        return self.results  # type: ignore[return-value]

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        self.async_calls.append([request.request_id for request in requests])
        return self.results  # type: ignore[return-value]


class FailingAdapter(RecordingAdapter):
    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        raise RuntimeError("render failed")

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        raise RuntimeError("sync failed")

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        raise RuntimeError("async failed")


def _config(*, batch_size: int = 2) -> InferenceConfig:
    return InferenceConfig(
        models=[
            ModelConfig(config_id="model-1", provider="test", model="first"),
            ModelConfig(config_id="model-2", provider="test", model="second"),
        ],
        batch_size=batch_size,
    )


def _requests(count: int = 5) -> list[InferenceRequest]:
    return [
        InferenceRequest(
            request_id=f"request-{index}",
            prompt=f"Prompt {index}",
            model_config_id="model-1" if index % 2 else "model-2",
            system_prompt="persona" if index % 2 else None,
            metadata={"position": index},
        )
        for index in range(1, count + 1)
    ]


def _successful_results(
    requests: Iterable[InferenceRequest],
) -> list[InferenceResult]:
    return [
        InferenceResult(
            request_id=request.request_id,
            model_config_id=request.model_config_id,
            content=f"response:{request.request_id}",
            metadata={"adapter": "must not leak"},
        )
        for request in requests
    ]


def test_preview_selects_one_batch_and_restores_request_order() -> None:
    adapter = RecordingAdapter()
    orchestrator = InferenceOrchestrator(adapter)

    preview = orchestrator.preview_batch(_requests(), _config(), batch_number=2)

    assert preview.batch_number == 2
    assert preview.total_batches == 3
    assert adapter.render_calls == [["request-3", "request-4"]]
    assert [prompt.request_id for prompt in preview.prompts] == [
        "request-3",
        "request-4",
    ]


@pytest.mark.parametrize("batch_number", [True, 1.5, 0, -1, 4])
def test_preview_rejects_invalid_batch_selection(batch_number: object) -> None:
    with pytest.raises(InferenceValidationError, match="batch_number"):
        InferenceOrchestrator(RecordingAdapter()).preview_batch(
            _requests(),
            _config(),
            batch_number=batch_number,  # type: ignore[arg-type]
        )


def test_preview_rejects_an_empty_request_collection() -> None:
    with pytest.raises(InferenceValidationError, match="empty"):
        InferenceOrchestrator(RecordingAdapter()).preview_batch([], _config())


def test_sync_batches_are_lazy_sequential_and_normalized() -> None:
    adapter = RecordingAdapter()
    requests = _requests()
    iterator = InferenceOrchestrator(adapter).run_batches(requests, _config())

    assert adapter.sync_calls == []

    first = next(iterator)
    assert adapter.sync_calls == [["request-1", "request-2"]]
    assert first.batch_number == 1
    assert first.total_batches == 3
    assert first.elapsed_seconds >= 0
    assert [result.request_id for result in first.results] == [
        "request-1",
        "request-2",
    ]
    assert first.results[0].metadata == requests[0].metadata
    assert first.results[0].metadata is not requests[0].metadata

    second = next(iterator)
    assert adapter.sync_calls == [
        ["request-1", "request-2"],
        ["request-3", "request-4"],
    ]
    assert second.batch_number == 2


def test_async_batches_are_lazy_sequential_and_normalized() -> None:
    async def exercise() -> None:
        adapter = RecordingAdapter()
        requests = _requests()
        iterator = InferenceOrchestrator(adapter).run_batches_async(
            requests,
            _config(),
        )

        assert adapter.async_calls == []

        first = await anext(iterator)
        assert adapter.async_calls == [["request-1", "request-2"]]
        assert adapter.sync_calls == []
        assert [result.request_id for result in first.results] == [
            "request-1",
            "request-2",
        ]
        assert first.results[0].metadata == requests[0].metadata

        second = await anext(iterator)
        assert adapter.async_calls == [
            ["request-1", "request-2"],
            ["request-3", "request-4"],
        ]
        assert second.batch_number == 2

    asyncio.run(exercise())


def test_empty_runs_do_not_call_the_adapter() -> None:
    adapter = RecordingAdapter()
    orchestrator = InferenceOrchestrator(adapter)

    assert list(orchestrator.run_batches([], _config())) == []

    async def exercise() -> list[object]:
        return [batch async for batch in orchestrator.run_batches_async([], _config())]

    assert asyncio.run(exercise()) == []
    assert adapter.sync_calls == []
    assert adapter.async_calls == []


def test_terminal_request_failure_is_a_normalized_result() -> None:
    request = _requests(1)[0]
    adapter = FixedResultsAdapter(
        [
            InferenceResult(
                request_id=request.request_id,
                model_config_id=request.model_config_id,
                content=None,
                metadata={},
                error=InferenceError(
                    type="ProviderError",
                    message="request failed after retries",
                ),
            )
        ]
    )

    batch = next(InferenceOrchestrator(adapter).run_batches([request], _config()))

    assert batch.results[0].content is None
    assert batch.results[0].error == InferenceError(
        type="ProviderError",
        message="request failed after retries",
    )


def test_complete_collection_is_validated_before_an_adapter_call() -> None:
    adapter = RecordingAdapter()
    requests = _requests()
    requests[-1].request_id = requests[0].request_id

    with pytest.raises(InferenceRequestValidationError, match="duplicate"):
        InferenceOrchestrator(adapter).run_batches(requests, _config())

    assert adapter.sync_calls == []


@pytest.mark.parametrize(
    ("results", "message"),
    [
        ([], "cardinality"),
        (
            [
                InferenceResult("request-1", "model-1", "ok", {}),
                InferenceResult("request-1", "model-1", "ok", {}),
            ],
            "duplicate",
        ),
        (
            [
                InferenceResult("request-1", "model-1", "ok", {}),
                InferenceResult("unknown", "model-2", "ok", {}),
            ],
            "unknown",
        ),
        (
            [
                InferenceResult("request-1", "model-2", "ok", {}),
                InferenceResult("request-2", "model-2", "ok", {}),
            ],
            "expected",
        ),
        (
            [
                InferenceResult("request-1", "model-1", None, {}),
                InferenceResult("request-2", "model-2", "ok", {}),
            ],
            "neither content nor error",
        ),
        (
            [
                InferenceResult(
                    "request-1",
                    "model-1",
                    "ok",
                    {},
                    InferenceError("Failure", "failed"),
                ),
                InferenceResult("request-2", "model-2", "ok", {}),
            ],
            "both content and error",
        ),
    ],
)
def test_systemic_result_contract_failures_stop_the_batch(
    results: object,
    message: str,
) -> None:
    iterator = InferenceOrchestrator(FixedResultsAdapter(results)).run_batches(
        _requests(2),
        _config(),
    )

    with pytest.raises(InferenceBatchError, match=message):
        next(iterator)


def test_systemic_failure_prevents_submission_of_a_later_batch() -> None:
    adapter = FixedResultsAdapter([])
    iterator = InferenceOrchestrator(adapter).run_batches(
        _requests(3),
        _config(batch_size=2),
    )

    with pytest.raises(InferenceBatchError, match="cardinality"):
        next(iterator)

    assert adapter.sync_calls == [["request-1", "request-2"]]


@pytest.mark.parametrize(
    ("prompts", "message"),
    [
        ([], "cardinality"),
        (
            [
                RenderedPrompt("request-1", "prompt", None),
                RenderedPrompt("request-1", "prompt", None),
            ],
            "duplicate",
        ),
    ],
)
def test_systemic_preview_contract_failures_are_rejected(
    prompts: object,
    message: str,
) -> None:
    with pytest.raises(InferenceBatchError, match=message):
        InferenceOrchestrator(FixedResultsAdapter(prompts)).preview_batch(
            _requests(2),
            _config(),
        )


def test_adapter_exceptions_are_wrapped_as_systemic_batch_failures() -> None:
    orchestrator = InferenceOrchestrator(FailingAdapter())

    with pytest.raises(InferenceBatchError, match="render failed") as preview_error:
        orchestrator.preview_batch(_requests(1), _config())
    assert isinstance(preview_error.value.__cause__, RuntimeError)

    with pytest.raises(InferenceBatchError, match="sync failed") as sync_error:
        next(orchestrator.run_batches(_requests(1), _config()))
    assert isinstance(sync_error.value.__cause__, RuntimeError)

    async def exercise() -> None:
        with pytest.raises(InferenceBatchError, match="async failed") as async_error:
            await anext(orchestrator.run_batches_async(_requests(1), _config()))
        assert isinstance(async_error.value.__cause__, RuntimeError)

    asyncio.run(exercise())
