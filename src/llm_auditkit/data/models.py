"""Configuration models for dataset loading."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DatasetSchema:
    """Describe the minimum columns and values required by a caller."""

    required_columns: list[str]
    nonempty_columns: list[str] = field(default_factory=list)
    optional_columns: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RemoteConfig:
    """Configure one bounded HTTP(S) dataset download."""

    backend: str
    url: str
    file_format: str | None = None
    credential_env: str | None = None
    timeout_seconds: float = 30.0
    max_bytes: int = 50_000_000
