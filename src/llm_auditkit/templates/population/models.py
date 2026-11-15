"""Column configuration for deterministic two-table template population."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(slots=True)
class TemplatePopulationConfig:
    """Map explicit template IDs and placeholder labels to input columns.

    Values and assignments belong in the two input DataFrames. Configuration
    is validated by ``TemplatePopulator.populate`` before processing either.
    """

    template_columns: Mapping[str, str]
    placeholder_columns: Mapping[str, str]
    job_posting_column: str = "Text"
