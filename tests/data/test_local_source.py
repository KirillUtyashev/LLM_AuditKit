"""Local tabular source tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.data import (
    DatasetConfigurationError,
    DatasetSourceError,
    LocalDatasetSource,
)


def test_csv_and_tsv_preserve_literal_strings(tmp_path: Path) -> None:
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text(
        "job,code,missing\nNA,00007,\n",
        encoding="utf-8",
    )
    tsv_path = tmp_path / "jobs.tsv"
    tsv_path.write_text(
        "job\tcode\nPosting\t00008\n",
        encoding="utf-8",
    )

    csv_frame = LocalDatasetSource(csv_path).load()
    tsv_frame = LocalDatasetSource(tsv_path).load()

    assert csv_frame.iloc[0].to_dict() == {
        "job": "NA",
        "code": "00007",
        "missing": "",
    }
    assert tsv_frame.iloc[0].to_dict() == {"job": "Posting", "code": "00008"}


@pytest.mark.parametrize(
    ("filename", "contents", "expected"),
    [
        (
            "jobs.json",
            '[{"job":"First","year":1950},{"job":"Second","year":null}]',
            ["First", "Second"],
        ),
        (
            "jobs.jsonl",
            '{"job":"First","year":1950}\n\n{"job":"Second","year":1951}\n',
            ["First", "Second"],
        ),
        (
            "jobs.ndjson",
            '{"job":"First"}\n{"job":"Second"}\n',
            ["First", "Second"],
        ),
    ],
)
def test_json_record_formats_are_supported(
    tmp_path: Path,
    filename: str,
    contents: str,
    expected: list[str],
) -> None:
    path = tmp_path / filename
    path.write_text(contents, encoding="utf-8")

    frame = LocalDatasetSource(path).load()

    assert frame["job"].tolist() == expected
    if "year" in frame:
        assert frame.loc[0, "year"] == 1950


def test_explicit_format_supports_extensionless_file(tmp_path: Path) -> None:
    path = tmp_path / "download"
    path.write_text("job\nPosting\n", encoding="utf-8")

    frame = LocalDatasetSource(path, file_format="CSV").load()

    assert frame["job"].tolist() == ["Posting"]


def test_directory_load_is_sorted_and_aligns_column_order(tmp_path: Path) -> None:
    directory = tmp_path / "parts"
    directory.mkdir()
    (directory / "b.csv").write_text("city,job\nBoston,Second\n", encoding="utf-8")
    (directory / "a.jsonl").write_text(
        '{"job":"First","city":"Toronto"}\n',
        encoding="utf-8",
    )
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")
    (directory / "nested").mkdir()
    (directory / "nested" / "c.csv").write_text(
        "job,city\nIgnored,Chicago\n",
        encoding="utf-8",
    )

    frame = LocalDatasetSource(directory).load()

    assert list(frame.columns) == ["job", "city"]
    assert frame.values.tolist() == [
        ["First", "Toronto"],
        ["Second", "Boston"],
    ]


def test_directory_rejects_mismatched_schemas_and_explicit_format(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "parts"
    directory.mkdir()
    (directory / "a.csv").write_text("job\nFirst\n", encoding="utf-8")
    (directory / "b.csv").write_text("posting\nSecond\n", encoding="utf-8")

    with pytest.raises(DatasetSourceError, match="directory schema"):
        LocalDatasetSource(directory).load()
    with pytest.raises(DatasetConfigurationError, match="cannot be set"):
        LocalDatasetSource(directory, file_format="csv").load()


def test_missing_empty_unsupported_and_malformed_sources_fail_cleanly(
    tmp_path: Path,
) -> None:
    with pytest.raises(DatasetSourceError, match="does not exist"):
        LocalDatasetSource(tmp_path / "missing.csv").load()

    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()
    with pytest.raises(DatasetSourceError, match="no supported files"):
        LocalDatasetSource(empty_directory).load()

    unsupported = tmp_path / "jobs.xlsx"
    unsupported.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(DatasetSourceError, match="infer"):
        LocalDatasetSource(unsupported).load()

    duplicate_header = tmp_path / "duplicate.csv"
    duplicate_header.write_text("job,job\nFirst,Second\n", encoding="utf-8")
    with pytest.raises(DatasetSourceError, match="unique"):
        LocalDatasetSource(duplicate_header).load()

    uneven_row = tmp_path / "uneven.csv"
    uneven_row.write_text("job,city\nPosting,Toronto,extra\n", encoding="utf-8")
    with pytest.raises(DatasetSourceError, match="3 fields; expected 2"):
        LocalDatasetSource(uneven_row).load()

    malformed_json = tmp_path / "bad.json"
    malformed_json.write_text('{"job":"not an array"}', encoding="utf-8")
    with pytest.raises(DatasetSourceError, match="array of record objects"):
        LocalDatasetSource(malformed_json).load()


def test_empty_delimited_table_retains_its_columns(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("job,city\n", encoding="utf-8")

    frame = LocalDatasetSource(path).load()

    assert frame.empty
    assert list(frame.columns) == ["job", "city"]
    assert isinstance(frame, pd.DataFrame)
