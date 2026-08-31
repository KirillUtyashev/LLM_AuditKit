"""Tests for deterministic request batching and job grouping."""

from __future__ import annotations

import pytest

from llm_auditkit.inference import (
    InferenceConfigurationError,
    InferenceRequest,
    InferenceRequestValidationError,
    ModelConfig,
)
from llm_auditkit.inference.batching import (
    build_request_batches,
    group_requests_by_model_and_system_prompt,
)


def _request(
    request_id: str,
    *,
    model_config_id: str = "model-1",
    system_prompt: str | None = None,
) -> InferenceRequest:
    return InferenceRequest(
        request_id=request_id,
        prompt=f"Prompt for {request_id}",
        model_config_id=model_config_id,
        system_prompt=system_prompt,
    )


def _models() -> dict[str, ModelConfig]:
    first = ModelConfig(config_id="model-1", provider="test", model="first")
    second = ModelConfig(config_id="model-2", provider="test", model="second")
    return {first.config_id: first, second.config_id: second}


def test_request_batches_preserve_order_and_progress_metadata() -> None:
    requests = [_request(f"request-{index}") for index in range(1, 6)]

    batches = build_request_batches(requests, batch_size=2)

    assert [batch.batch_number for batch in batches] == [1, 2, 3]
    assert [batch.total_batches for batch in batches] == [3, 3, 3]
    assert [
        [request.request_id for request in batch.requests] for batch in batches
    ] == [
        ["request-1", "request-2"],
        ["request-3", "request-4"],
        ["request-5"],
    ]


def test_empty_request_collection_produces_no_batches() -> None:
    assert build_request_batches([], batch_size=10) == ()


@pytest.mark.parametrize("batch_size", [True, 1.5, 0, -1])
def test_batch_builder_rejects_invalid_batch_size(batch_size: object) -> None:
    with pytest.raises(InferenceConfigurationError, match="batch_size"):
        build_request_batches([], batch_size=batch_size)  # type: ignore[arg-type]


def test_job_groups_preserve_first_seen_group_and_request_order() -> None:
    requests = [
        _request("request-1", system_prompt="persona-a"),
        _request(
            "request-2",
            model_config_id="model-2",
            system_prompt="persona-a",
        ),
        _request("request-3", system_prompt="persona-a"),
        _request("request-4"),
        _request("request-5", system_prompt=""),
    ]

    groups = group_requests_by_model_and_system_prompt(requests, _models())

    assert [
        (group.model_config.config_id, group.system_prompt) for group in groups
    ] == [
        ("model-1", "persona-a"),
        ("model-2", "persona-a"),
        ("model-1", None),
        ("model-1", ""),
    ]
    assert [request.request_id for request in groups[0].requests] == [
        "request-1",
        "request-3",
    ]
    assert sum(len(group.requests) for group in groups) == len(requests)


def test_empty_request_collection_produces_no_job_groups() -> None:
    assert group_requests_by_model_and_system_prompt([], _models()) == ()


def test_job_grouping_rejects_an_unknown_model_reference() -> None:
    with pytest.raises(InferenceRequestValidationError, match="unknown model"):
        group_requests_by_model_and_system_prompt(
            [_request("request-1", model_config_id="missing")],
            _models(),
        )
