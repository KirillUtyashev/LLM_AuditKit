"""Shared deterministic scenario identity for DataFrame pipeline stages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import pandas as pd


SCENARIO_ID_COLUMN = "scenario_id"


def build_scenario_id(row: Mapping[str, object]) -> str:
    """Return a stable content-derived ID for one complete source row."""

    canonical_row = [
        [column, _canonical_value(row[column])]
        for column in sorted(row)
    ]
    encoded_row = json.dumps(
        canonical_row,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"scenario:{hashlib.sha256(encoded_row).hexdigest()}"


def derive_scenario_ids(dataset: pd.DataFrame) -> list[str]:
    """Return supplied or content-derived IDs in existing row order."""

    if SCENARIO_ID_COLUMN in dataset.columns:
        return dataset[SCENARIO_ID_COLUMN].tolist()

    return [
        build_scenario_id(row)
        for row in dataset.to_dict(orient="records")
    ]


def _canonical_value(value: object) -> str | None:
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return str(value)
