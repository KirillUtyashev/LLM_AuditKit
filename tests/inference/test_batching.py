"""Tests for deterministic request batching and job grouping."""

from __future__ import annotations

import pytest

from llm_auditkit.inference import (
    DictResponseFormat,
    InferenceConfigurationError,
    InferenceRequest,
    InferenceRequestValidationError,
    ModelConfig,
    ResponseField,
)
from llm_auditkit.inference.batching import (
    build_request_batches,
    group_requests_by_compatibility,
)


def _request(
    request_id: str,
    *,
    model_config_id: str = "model-1",
    system_prompt: str | None = None,
    persona: str | None = None,
    response_format: DictResponseFormat | None = None,
) -> InferenceRequest:
    return InferenceRequest(
        request_id=request_id,
        prompt=f"Prompt for {request_id}",
        model_config_id=model_config_id,
        system_prompt=system_prompt,
        persona=persona,
        response_format=response_format,
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
        _request("request-1", system_prompt="instruction-a", persona="persona-a"),
        _request(
            "request-2",
            model_config_id="model-2",
            system_prompt="instruction-a",
            persona="persona-a",
        ),
        _request("request-3", system_prompt="instruction-b", persona="persona-b"),
        _request("request-4"),
        _request("request-5", system_prompt=""),
        _request("request-6", system_prompt="instruction-a", persona="persona-a"),
    ]

    groups = group_requests_by_compatibility(requests, _models())

    assert [group.model_config.config_id for group in groups] == [
        "model-1",
        "model-2",
        "model-1",
        "model-1",
        "model-1",
    ]
    assert [request.request_id for request in groups[0].requests] == [
        "request-1",
        "request-6",
    ]
    assert [[request.request_id for request in group.requests] for group in groups[1:]] == [
        ["request-2"],
        ["request-3"],
        ["request-4"],
        ["request-5"],
    ]
    assert sum(len(group.requests) for group in groups) == len(requests)


def test_empty_request_collection_produces_no_job_groups() -> None:
    assert group_requests_by_compatibility([], _models()) == ()


def test_job_grouping_rejects_an_unknown_model_reference() -> None:
    with pytest.raises(InferenceRequestValidationError, match="unknown model"):
        group_requests_by_compatibility(
            [_request("request-1", model_config_id="missing")],
            _models(),
        )


def test_job_groups_include_structural_response_format_compatibility() -> None:
    first_format = DictResponseFormat(
        fields=[ResponseField("decision", "string", "Yes or No")],
        include_comment=True,
    )
    equivalent_format = DictResponseFormat(
        fields=[ResponseField("decision", "string", "Yes or No")],
        include_comment=True,
    )
    different_format = DictResponseFormat(
        fields=[ResponseField("decision", "string", "Yes or No")],
        include_comment=False,
    )
    format_without_type_hints = DictResponseFormat(
        fields=[ResponseField("decision", "string", "Yes or No")],
        include_comment=True,
        include_type_hints=False,
    )
    requests = [
        _request("request-1", response_format=first_format),
        _request("request-2", response_format=equivalent_format),
        _request("request-3", response_format=different_format),
        _request("request-4", response_format=format_without_type_hints),
        _request("request-5"),
    ]

    groups = group_requests_by_compatibility(requests, _models())

    assert [[request.request_id for request in group.requests] for group in groups] == [
        ["request-1", "request-2"],
        ["request-3"],
        ["request-4"],
        ["request-5"],
    ]
    assert groups[0].response_format is first_format
    assert groups[3].response_format is None
