"""Dependency-free tabular format inference and parsing."""

from __future__ import annotations

import csv
import json
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

from .exceptions import DatasetConfigurationError, DatasetSourceError


SUPPORTED_FILE_FORMATS = frozenset({"csv", "tsv", "json", "jsonl"})
_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
}


class _DuplicateJSONKeyError(ValueError):
    pass


def normalize_file_format(value: object) -> str | None:
    """Validate and normalize an optional explicit file format."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DatasetConfigurationError(
            "file_format must be a supported non-empty string or None"
        )
    normalized = value.strip().lower()
    if normalized == "ndjson":
        normalized = "jsonl"
    if normalized not in SUPPORTED_FILE_FORMATS:
        choices = ", ".join(sorted(SUPPORTED_FILE_FORMATS))
        raise DatasetConfigurationError(
            f"unsupported file_format {value!r}; expected one of: {choices}"
        )
    return normalized


def infer_file_format(path: str | Path) -> str:
    """Infer a supported tabular format from one path suffix."""

    suffix = Path(path).suffix.lower()
    file_format = _FORMAT_BY_SUFFIX.get(suffix)
    if file_format is None:
        raise DatasetSourceError(
            f"cannot infer a supported dataset format from extension {suffix!r}"
        )
    return file_format


def has_supported_extension(path: Path) -> bool:
    """Whether a path suffix maps to one of the supported formats."""

    return path.suffix.lower() in _FORMAT_BY_SUFFIX


def read_tabular_bytes(
    data: bytes,
    file_format: str,
    *,
    source_label: str,
    expose_error_details: bool = True,
) -> pd.DataFrame:
    """Parse tabular bytes without exposing source-specific objects downstream."""

    try:
        if file_format == "csv":
            return _read_delimited(data, delimiter=",")
        if file_format == "tsv":
            return _read_delimited(data, delimiter="\t")
        if file_format == "json":
            return _read_json_records(data)
        if file_format == "jsonl":
            return _read_json_lines(data)
    except DatasetSourceError as error:
        if expose_error_details:
            raise
        raise DatasetSourceError(
            f"could not parse {source_label} as {file_format}: "
            f"{type(error).__name__}"
        ) from error
    except Exception as error:
        detail = f": {error}" if expose_error_details else ""
        raise DatasetSourceError(
            f"could not parse {source_label} as {file_format}: "
            f"{type(error).__name__}{detail}"
        ) from error
    raise DatasetSourceError(f"unsupported dataset format {file_format!r}")


def _read_delimited(data: bytes, *, delimiter: str) -> pd.DataFrame:
    text = data.decode("utf-8-sig")
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration as error:
        raise DatasetSourceError("delimited dataset must contain a header") from error
    _validate_header(header)
    for line_number, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(header):
            raise DatasetSourceError(
                f"delimited dataset row {line_number} has {len(row)} fields; "
                f"expected {len(header)}"
            )
    return pd.read_csv(
        BytesIO(data),
        sep=delimiter,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
    )


def _read_json_records(data: bytes) -> pd.DataFrame:
    decoded = json.loads(
        data.decode("utf-8-sig"),
        object_pairs_hook=_unique_json_object,
    )
    if not isinstance(decoded, list) or any(
        not isinstance(record, dict) for record in decoded
    ):
        raise DatasetSourceError("JSON dataset must be an array of record objects")
    return pd.DataFrame(decoded, dtype=object)


def _read_json_lines(data: bytes) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(data.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line, object_pairs_hook=_unique_json_object)
        if not isinstance(record, dict):
            raise DatasetSourceError(
                f"JSON Lines record at line {line_number} must be an object"
            )
        records.append(record)
    return pd.DataFrame(records, dtype=object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKeyError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _validate_header(header: list[str]) -> None:
    if not header:
        raise DatasetSourceError("delimited dataset header must not be empty")
    invalid = [
        name for name in header if not isinstance(name, str) or not name.strip()
    ]
    if invalid:
        raise DatasetSourceError(
            "delimited dataset column names must be non-empty strings"
        )
    if len(set(header)) != len(header):
        raise DatasetSourceError("delimited dataset column names must be unique")
