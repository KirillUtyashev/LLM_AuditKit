"""Tests for canonical experiment CSV checkpoint and resume storage."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentJobKey,
    ExperimentOutcome,
    ExperimentOutputRecord,
    ExperimentResultStore,
    ExperimentResultStoreError,
    Persona,
    build_experiment_request_id,
)
from llm_auditkit.experiments.planning import build_experiment_job_keys
from llm_auditkit.inference import InferenceConfig, ModelConfig


def _config() -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="experiment-1",
        dataset_schema=ExperimentDatasetSchema(
            scenario_id_column="scenario_id",
            job_posting_column="job_posting",
            resume_columns=["resume_1", "resume_2"],
        ),
        personas=[Persona("manager", "Manager", "Hiring manager persona")],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    "model-1",
                    "openai",
                    "test-model",
                    {"logprobs": True},
                )
            ],
            batch_size=2,
        ),
    )


def _dataset(*, scenario_ids: list[str] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": scenario_ids or ["scenario-1", "scenario-2"],
            "job_posting": ["Posting one", "Posting two"],
            "resume_1": ["Resume 1A", "Resume 1B"],
            "resume_2": ["Resume 2A", "Resume 2B"],
            "caller_metadata": ["keep-1", "keep-2"],
        }
    )


def _record(
    key: ExperimentJobKey,
    *,
    successful: bool = True,
) -> ExperimentOutputRecord:
    values = {
        "key": key,
        "request_id": build_experiment_request_id(key),
        "persona_name": "Manager",
        "persona_description": "Hiring manager persona",
        "user_prompt": f"Rendered prompt for {key.scenario_id}",
        "system_prompt": "Rendered system prompt",
    }
    if successful:
        return ExperimentOutputRecord(
            **values,
            outcome=ExperimentOutcome(
                picks=[1, 0],
                logprobs=[-0.2, -0.4],
                generated_response='{"Applicant 1":"Yes","Applicant 2":"No"}',
                comment="Interview the first applicant.",
            ),
        )
    return ExperimentOutputRecord(
        **values,
        error_type="ProviderError",
        error_message="request failed after retries",
    )


def test_initialize_creates_canonical_empty_output_in_memory(tmp_path: Path) -> None:
    output = ExperimentResultStore(tmp_path / "results.csv").initialize(
        _dataset(),
        _config(),
    )

    assert output.empty
    assert list(output.columns) == [
        "scenario_id",
        "job_posting",
        "resume_1",
        "resume_2",
        "caller_metadata",
        "experiment_id",
        "persona_id",
        "model_config_id",
        "request_id",
        "persona_name",
        "persona_description",
        "user_prompt",
        "system_prompt",
        "generated_response",
        "comment",
        "picks",
        "pick1",
        "pick2",
        "logprob1",
        "logprob2",
        "error_type",
        "error_message",
    ]


def test_apply_batch_repeats_source_rows_and_restores_canonical_order(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    keys = build_experiment_job_keys(dataset, config)

    updated = store.apply_batch(
        output,
        dataset,
        config,
        [_record(keys[1]), _record(keys[0])],
    )

    assert updated["scenario_id"].tolist() == ["scenario-1", "scenario-2"]
    assert updated["caller_metadata"].tolist() == ["keep-1", "keep-2"]
    assert updated["picks"].tolist() == ["[1,0]", "[1,0]"]
    assert updated[["pick1", "pick2"]].values.tolist() == [[1, 0], [1, 0]]
    assert updated[["logprob1", "logprob2"]].values.tolist() == [
        [-0.2, -0.4],
        [-0.2, -0.4],
    ]


def test_failed_record_remains_pending_and_is_replaced_by_success(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]

    failed = store.apply_batch(
        output,
        dataset,
        config,
        [_record(key, successful=False)],
    )
    assert store.completed_keys(failed, dataset, config) == set()
    assert failed.loc[0, "error_type"] == "ProviderError"

    succeeded = store.apply_batch(failed, dataset, config, [_record(key)])
    assert len(succeeded) == 1
    assert store.completed_keys(succeeded, dataset, config) == {key}
    assert pd.isna(succeeded.loc[0, "error_type"])


def test_save_and_resume_preserve_string_scenario_ids(tmp_path: Path) -> None:
    dataset = _dataset(scenario_ids=["001", "002"])
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]

    saved = store.save_batch(output, dataset, config, [_record(key)])
    resumed = store.initialize(dataset, config)

    assert resumed["scenario_id"].tolist() == ["001"]
    assert store.completed_keys(resumed, dataset, config) == {key}
    normalized_saved = saved.astype(object).where(saved.notna(), "<missing>")
    normalized_resumed = resumed.astype(object).where(resumed.notna(), "<missing>")
    pd.testing.assert_frame_equal(
        normalized_saved,
        normalized_resumed,
        check_dtype=False,
    )


def test_mapped_scenario_id_column_is_preserved_with_canonical_identity(
    tmp_path: Path,
) -> None:
    dataset = _dataset(scenario_ids=["001", "002"]).rename(
        columns={"scenario_id": "case_id"}
    )
    config = _config()
    config.dataset_schema.scenario_id_column = "case_id"
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]

    store.save_batch(output, dataset, config, [_record(key)])
    resumed = store.initialize(dataset, config)

    assert resumed.loc[0, "case_id"] == "001"
    assert resumed.loc[0, "scenario_id"] == "001"


def test_save_batch_performs_one_atomic_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]
    replacements: list[tuple[object, object]] = []
    original_replace = __import__("os").replace

    def counted_replace(source: object, destination: object) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr("llm_auditkit.experiments.store.os.replace", counted_replace)

    store.save_batch(output, dataset, config, [_record(key)])

    assert len(replacements) == 1
    assert Path(replacements[0][1]) == store.output_path


def test_atomic_write_failure_preserves_previous_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ExperimentResultStore(tmp_path / "results.csv")
    previous = pd.DataFrame({"value": ["previous"]})
    store.save(previous)
    previous_bytes = store.output_path.read_bytes()

    def fail_to_csv(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ExperimentResultStoreError, match="atomically save"):
        store.save(pd.DataFrame({"value": ["new"]}))

    assert store.output_path.read_bytes() == previous_bytes
    assert list(tmp_path.iterdir()) == [store.output_path]


@pytest.mark.parametrize("column", ["persona_id", "picks", "pick1", "logprob20"])
def test_source_columns_must_not_collide_with_result_columns(
    tmp_path: Path,
    column: str,
) -> None:
    dataset = _dataset()
    dataset[column] = "caller-owned"

    with pytest.raises(ExperimentResultStoreError, match="conflicts"):
        ExperimentResultStore(tmp_path / "results.csv").initialize(dataset, _config())


def test_record_job_key_must_belong_to_current_plan(tmp_path: Path) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    unknown = ExperimentJobKey(
        "experiment-1",
        "unknown-scenario",
        "manager",
        "model-1",
    )

    with pytest.raises(ExperimentResultStoreError, match="current experiment plan"):
        store.apply_batch(output, dataset, config, [_record(unknown)])


def test_existing_duplicate_or_mismatched_identity_is_rejected(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]
    valid = store.apply_batch(output, dataset, config, [_record(key)])

    duplicate = pd.concat([valid, valid], ignore_index=True)
    store.save(duplicate)
    with pytest.raises(ExperimentResultStoreError, match="duplicate"):
        store.initialize(dataset, config)

    invalid_request = valid.copy()
    invalid_request.loc[0, "request_id"] = "wrong-request"
    store.save(invalid_request)
    with pytest.raises(ExperimentResultStoreError, match="request ID"):
        store.initialize(dataset, config)

    missing_request = valid.copy()
    missing_request.loc[0, "request_id"] = None
    store.save(missing_request)
    with pytest.raises(ExperimentResultStoreError, match="request ID"):
        store.initialize(dataset, config)


def test_incomplete_success_fields_remain_pending(tmp_path: Path) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]
    output = store.apply_batch(output, dataset, config, [_record(key)])
    output.loc[0, "logprob2"] = None

    assert store.completed_keys(output, dataset, config) == set()


def test_completed_record_cannot_be_overwritten(tmp_path: Path) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]
    output = store.apply_batch(output, dataset, config, [_record(key)])

    with pytest.raises(ExperimentResultStoreError, match="cannot be replaced"):
        store.apply_batch(
            output,
            dataset,
            config,
            [_record(key, successful=False)],
        )


def test_invalid_record_outcome_is_rejected_cleanly(tmp_path: Path) -> None:
    dataset = _dataset()
    config = _config()
    store = ExperimentResultStore(tmp_path / "results.csv")
    output = store.initialize(dataset, config)
    key = build_experiment_job_keys(dataset, config)[0]
    record = _record(key)
    record.outcome = {"picks": [1, 0]}  # type: ignore[assignment]

    with pytest.raises(ExperimentResultStoreError, match="ExperimentOutcome"):
        store.apply_batch(output, dataset, config, [record])
