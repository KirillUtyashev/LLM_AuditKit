"""Configuration models for dataset loading."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DatasetSchema:
    """Describe the minimum columns and values required by a caller."""

    required_columns: list[str]
    nonempty_columns: list[str] = field(default_factory=list)
    optional_columns: dict[str, str] = field(default_factory=dict)
