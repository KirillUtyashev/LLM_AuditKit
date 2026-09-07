"""Deterministic logical batching and adapter job grouping."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .exceptions import InferenceConfigurationError, InferenceRequestValidationError
from .models import InferenceRequest, ModelConfig


@dataclass(frozen=True, slots=True)
class RequestBatch:
    """One deterministic logical batch of inference requests."""

    batch_number: int
    total_batches: int
    requests: tuple[InferenceRequest, ...]


@dataclass(frozen=True, slots=True)
class AdapterJobGroup:
    """Requests compatible with one backend job.

    EDSL jobs created by the shared adapter use exactly one model configuration and
    one system prompt. Request-specific user prompts remain separate scenarios.
    """

    model_config: ModelConfig
    system_prompt: str | None
    requests: tuple[InferenceRequest, ...]


def build_request_batches(
    requests: Sequence[InferenceRequest],
    batch_size: int,
) -> tuple[RequestBatch, ...]:
    """Partition requests in input order into deterministic logical batches."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        raise InferenceConfigurationError("batch_size must be an integer")
    if batch_size <= 0:
        raise InferenceConfigurationError("batch_size must be positive")

    request_count = len(requests)
    if request_count == 0:
        return ()

    total_batches = (request_count + batch_size - 1) // batch_size
    return tuple(
        RequestBatch(
            batch_number=batch_index + 1,
            total_batches=total_batches,
            requests=tuple(
                requests[
                    batch_index * batch_size : (batch_index + 1) * batch_size
                ]
            ),
        )
        for batch_index in range(total_batches)
    )


def group_requests_by_model_and_system_prompt(
    requests: Sequence[InferenceRequest],
    models: Mapping[str, ModelConfig],
) -> tuple[AdapterJobGroup, ...]:
    """Build compatible job groups without adding request combinations.

    Groups and requests within each group preserve first-seen input order. ``None``
    and an explicitly empty system prompt are distinct grouping keys.
    """

    grouped_requests: dict[tuple[str, str | None], list[InferenceRequest]] = {}

    for request in requests:
        if request.model_config_id not in models:
            raise InferenceRequestValidationError(
                f"request {request.request_id!r} references unknown model "
                f"configuration ID {request.model_config_id!r}"
            )
        group_key = (request.model_config_id, request.system_prompt)
        grouped_requests.setdefault(group_key, []).append(request)

    return tuple(
        AdapterJobGroup(
            model_config=models[model_config_id],
            system_prompt=system_prompt,
            requests=tuple(group_requests),
        )
        for (model_config_id, system_prompt), group_requests in grouped_requests.items()
    )
