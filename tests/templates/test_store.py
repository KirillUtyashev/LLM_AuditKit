"""Atomic template checkpoint and resume storage tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.templates import (
    TemplateOutputRecord,
    TemplateStore,
    TemplateStoreError,
    build_template_request_id,
)
from llm_auditkit.templates.identity import build_generation_fingerprint

from .helpers import config, dataset, template_text


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA])
@pytest.mark.parametrize("reverse", [False, True])
def test_rendered_input_fingerprint_rejects_missing_empty_drift(tmp_path, missing, reverse):
    source = dataset(1)
    source["city_name"] = pd.Series(["" if reverse else missing], dtype=object)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    saved = store.save_result(store.initialize(source, generation), source,
                              generation, _record("scenario-1"))
    unchanged = store.initialize(source, generation)
    assert store.completed_scenario_ids(unchanged, source, generation) == {"scenario-1"}
    changed = source.copy()
    changed["city_name"] = pd.Series([missing if reverse else ""], dtype=object)
    with pytest.raises(TemplateStoreError, match="source or generation metadata"):
        store.initialize(changed, generation)
    with pytest.raises(TemplateStoreError, match="input fingerprint"):
        store.completed_scenario_ids(saved, changed, generation)


def test_legacy_checkpoint_without_input_fingerprint_cannot_be_reused(tmp_path):
    source, generation = dataset(1), config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)
    output = output.drop(columns="template_generation_input_fingerprint")
    output.to_csv(store.output_path, index=False)
    with pytest.raises(TemplateStoreError, match="cannot safely resume.*older checkpoint"):
        store.initialize(source, generation)


def test_nul_save_leaves_existing_checkpoint_intact(tmp_path):
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)
    store.save(output)
    original = store.output_path.read_bytes()
    output.loc[0, "template_1"] = "{{name}} {{address}} before\x00after"
    with pytest.raises(TemplateStoreError, match="NUL"):
        store.save(output)
    assert store.output_path.read_bytes() == original


def test_nul_in_external_checkpoint_is_rejected_before_csv_parsing(tmp_path):
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.apply_result(store.initialize(source, generation), source,
                                generation, _record("scenario-1"))
    output.loc[0, "template_1"] += " before\x00after"
    output.to_csv(store.output_path, index=False)
    with pytest.raises(TemplateStoreError, match="NUL"):
        store.initialize(source, generation)


def _record(
    scenario_id: str,
    *,
    generation=None,
    successful: bool = True,
) -> TemplateOutputRecord:
    generation = generation or config()
    fingerprint = build_generation_fingerprint(generation)
    values = {
        "scenario_id": scenario_id,
        "request_id": build_template_request_id(scenario_id, fingerprint),
        "generation_fingerprint": fingerprint,
        "model_config_id": generation.model_config_id,
    }
    if successful:
        return TemplateOutputRecord(
            **values,
            templates=[
                template_text(scenario_id, position)
                for position in range(1, generation.templates_per_scenario + 1)
            ],
        )
    return TemplateOutputRecord(
        **values,
        error_type="ProviderError",
        error_message="request failed after retries",
    )


def test_initialize_creates_full_pending_output_with_internal_ids(
    tmp_path: Path,
) -> None:
    source = dataset(2, supplied_ids=False)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")

    output = store.initialize(source, generation)

    assert len(output) == len(source)
    assert "scenario_id" in output
    assert output["scenario_id"].str.startswith("scenario:").all()
    assert output["template_1"].isna().all()
    assert output["template_generation_error_type"].isna().all()
    assert output["template_generation_fingerprint"].nunique() == 1


def test_successful_and_failed_results_have_distinct_completion_state(
    tmp_path: Path,
) -> None:
    source = dataset(2)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)

    output = store.apply_result(
        output,
        source,
        generation,
        _record("scenario-1"),
    )
    output = store.apply_result(
        output,
        source,
        generation,
        _record("scenario-2", successful=False),
    )

    assert store.completed_scenario_ids(output, source, generation) == {"scenario-1"}
    failed = output[output["scenario_id"] == "scenario-2"].iloc[0]
    assert pd.isna(failed["template_1"])
    assert failed["template_generation_error_type"] == "ProviderError"


def test_checkpoint_round_trip_preserves_source_values_and_current_order(
    tmp_path: Path,
) -> None:
    source = dataset(2)
    source["numeric_value"] = [7, 8]
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)
    output = store.apply_result(output, source, generation, _record("scenario-1"))
    store.save(output)

    reordered = source.iloc[::-1].reset_index(drop=True)
    restored = store.initialize(reordered, generation)

    assert restored["scenario_id"].tolist() == ["scenario-2", "scenario-1"]
    assert restored["code"].tolist() == ["002", "001"]
    assert restored["numeric_value"].tolist() == [8, 7]
    assert store.completed_scenario_ids(restored, reordered, generation) == {
        "scenario-1"
    }


def test_failed_checkpoint_is_retried_and_replaced_by_success(tmp_path: Path) -> None:
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)
    output = store.save_result(
        output,
        source,
        generation,
        _record("scenario-1", successful=False),
    )
    assert store.completed_scenario_ids(output, source, generation) == set()

    restored = store.initialize(source, generation)
    completed = store.save_result(
        restored,
        source,
        generation,
        _record("scenario-1"),
    )
    assert store.completed_scenario_ids(completed, source, generation) == {
        "scenario-1"
    }
    assert completed.loc[0, "template_generation_error_type"] is None


def test_completed_result_cannot_be_overwritten(tmp_path: Path) -> None:
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.apply_result(
        store.initialize(source, generation),
        source,
        generation,
        _record("scenario-1"),
    )
    with pytest.raises(TemplateStoreError, match="cannot be overwritten"):
        store.apply_result(
            output,
            source,
            generation,
            _record("scenario-1"),
        )


def test_changed_generation_contract_rejects_old_checkpoint(tmp_path: Path) -> None:
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    store.save(store.initialize(source, generation))

    changed = deepcopy(generation)
    changed.prompt_template += " Use concise language."
    with pytest.raises(TemplateStoreError, match="metadata does not match"):
        store.initialize(source, changed)


def test_source_drift_and_output_column_collisions_fail_cleanly(tmp_path: Path) -> None:
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    store.save(store.initialize(source, generation))

    changed_source = source.copy()
    changed_source.loc[0, "job_text"] = "Changed job"
    with pytest.raises(TemplateStoreError, match="source or generation metadata"):
        store.initialize(changed_source, generation)

    conflicting = source.copy()
    conflicting["template_1"] = "caller value"
    with pytest.raises(TemplateStoreError, match="conflicts"):
        store.initialize(conflicting, generation)


def test_partial_checkpoint_rows_are_rejected(tmp_path: Path) -> None:
    source = dataset(1)
    generation = config()
    store = TemplateStore(tmp_path / "templates.csv")
    output = store.initialize(source, generation)
    output.loc[0, "template_1"] = template_text("scenario-1", 1)
    store.save(output)

    with pytest.raises(TemplateStoreError, match="pending, failed, or completely"):
        store.initialize(source, generation)


def test_output_path_must_be_a_csv_file(tmp_path: Path) -> None:
    with pytest.raises(TemplateStoreError, match=".csv"):
        TemplateStore(tmp_path / "templates.json")
