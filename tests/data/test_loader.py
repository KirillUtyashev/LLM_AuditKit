"""Canonical dataset loader, normalization, and identity tests."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from llm_auditkit.data import (
    DatasetIdentityError,
    DatasetLoader,
    DatasetNormalizationError,
    DatasetSchema,
    DatasetSourceError,
    DatasetValidationError,
    MissingOptionalColumnWarning,
)


@dataclass
class StaticSource:
    value: object

    def load(self) -> object:
        return self.value


def _loader() -> DatasetLoader:
    return DatasetLoader(
        DatasetSchema(
            required_columns=["job"],
            nonempty_columns=["job"],
        )
    )


def test_loader_normalizes_a_copy_and_adds_stable_ids() -> None:
    source_frame = pd.DataFrame(
        {"job": ["Posting"], "year": [1950], "missing": [None]},
        dtype=object,
    )
    source_frame.index = [99]

    output = _loader().load(StaticSource(source_frame))
    reordered = _loader().load(
        StaticSource(source_frame[["missing", "year", "job"]])
    )

    assert source_frame.index.tolist() == [99]
    assert "scenario_id" not in source_frame.columns
    assert output.index.tolist() == [0]
    assert output.loc[0, "year"] == "1950"
    assert pd.isna(output.loc[0, "missing"])
    assert all(str(dtype) == "string" for dtype in output.dtypes)
    assert output.loc[0, "scenario_id"].startswith("scenario:")
    assert output.loc[0, "scenario_id"] == reordered.loc[0, "scenario_id"]


def test_loader_preserves_supplied_string_ids() -> None:
    frame = pd.DataFrame(
        {"scenario_id": ["001"], "job": ["Posting"]},
        dtype="string",
    )

    output = _loader().load(StaticSource(frame))

    assert list(output.columns) == ["scenario_id", "job"]
    assert output["scenario_id"].tolist() == ["001"]


def test_duplicate_or_invalid_scenario_identity_is_rejected() -> None:
    duplicates = pd.DataFrame({"job": ["Same", "Same"]})
    with pytest.raises(DatasetIdentityError, match="stable replicate"):
        _loader().load(StaticSource(duplicates))

    supplied_duplicates = pd.DataFrame(
        {"scenario_id": ["same", "same"], "job": ["First", "Second"]}
    )
    with pytest.raises(DatasetIdentityError, match="must be unique"):
        _loader().load(StaticSource(supplied_duplicates))

    blank = pd.DataFrame({"scenario_id": [" "], "job": ["Posting"]})
    with pytest.raises(DatasetIdentityError, match="non-empty"):
        _loader().load(StaticSource(blank))


def test_non_dataframe_and_nested_cells_are_rejected() -> None:
    with pytest.raises(DatasetNormalizationError, match="pandas DataFrame"):
        _loader().load(StaticSource([{"job": "Posting"}]))

    nested = pd.DataFrame({"job": ["Posting"], "metadata": [["nested"]]})
    with pytest.raises(DatasetNormalizationError, match="scalar"):
        _loader().load(StaticSource(nested))

    invalid_columns = pd.DataFrame([["Posting"]], columns=[1])
    with pytest.raises(DatasetNormalizationError, match="column names"):
        _loader().load(StaticSource(invalid_columns))


def test_loader_applies_required_fields_and_optional_warnings() -> None:
    loader = DatasetLoader(
        DatasetSchema(
            required_columns=["job", "city"],
            nonempty_columns=["job"],
            optional_columns={"year": "historical behavior will be unavailable"},
        )
    )

    with pytest.raises(DatasetValidationError, match="'city'"):
        loader.load(StaticSource(pd.DataFrame({"job": ["Posting"]})))

    with pytest.warns(MissingOptionalColumnWarning, match="historical behavior"):
        output = loader.load(
            StaticSource(pd.DataFrame({"job": ["Posting"], "city": ["Toronto"]}))
        )
    assert len(output) == 1


def test_empty_dataset_with_required_columns_is_valid() -> None:
    frame = pd.DataFrame(columns=["job"])

    output = _loader().load(StaticSource(frame))

    assert output.empty
    assert list(output.columns) == ["job", "scenario_id"]


def test_unexpected_custom_source_failure_is_wrapped() -> None:
    class FailingSource:
        def load(self) -> pd.DataFrame:
            raise RuntimeError("custom failure")

    with pytest.raises(DatasetSourceError, match="RuntimeError: custom failure"):
        _loader().load(FailingSource())


def test_object_without_load_method_is_rejected() -> None:
    with pytest.raises(DatasetSourceError, match="implement"):
        _loader().load(object())  # type: ignore[arg-type]
