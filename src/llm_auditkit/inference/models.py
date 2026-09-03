"""Domain-neutral data models for shared inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
ResponseValueType: TypeAlias = Literal["string", "integer", "number", "boolean"]


@dataclass(slots=True)
class ModelConfig:
    """Configuration for one EDSL provider and model combination."""

    config_id: str
    provider: str
    model: str
    parameters: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class InferenceConfig:
    """Configuration shared by one inference run."""

    models: list[ModelConfig]
    batch_size: int


@dataclass(frozen=True, slots=True)
class ResponseField:
    """One named value in a generic dictionary response."""

    name: str
    value_type: ResponseValueType
    description: str


@dataclass(slots=True)
class DictResponseFormat:
    """Backend-neutral schema for an ordered dictionary response."""

    fields: list[ResponseField]
    include_comment: bool = True
    include_type_hints: bool = True


@dataclass(slots=True)
class InferenceRequest:
    """One domain-neutral prompt submitted for inference."""

    request_id: str
    prompt: str
    model_config_id: str
    system_prompt: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    response_format: DictResponseFormat | None = None
    persona: str | None = None


@dataclass(slots=True)
class RenderedPrompt:
    """Effective prompts rendered by the inference backend for one request."""

    request_id: str
    user_prompt: str
    system_prompt: str | None


@dataclass(slots=True)
class InferenceBatchPreview:
    """Rendered prompts and position information for one logical batch."""

    batch_number: int
    total_batches: int
    prompts: list[RenderedPrompt]


@dataclass(slots=True)
class InferenceError:
    """Normalized terminal error for one inference request."""

    type: str
    message: str


@dataclass(frozen=True, slots=True)
class TokenLogprob:
    """Natural log probability associated with one emitted token."""

    token: str
    logprob: float


@dataclass(slots=True)
class InferenceResult:
    """Normalized terminal outcome for one inference request."""

    request_id: str
    model_config_id: str
    content: str | None
    metadata: dict[str, object]
    error: InferenceError | None = None
    structured_content: dict[str, JSONValue] | None = None
    comment: str | None = None
    token_logprobs: list[TokenLogprob] = field(default_factory=list)
    rendered_prompt: RenderedPrompt | None = None


@dataclass(slots=True)
class InferenceBatchResult:
    """Normalized outcomes and progress data for one logical batch."""

    batch_number: int
    total_batches: int
    elapsed_seconds: float
    results: list[InferenceResult]
