"""End-to-end unit tests for experiment execution orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentResultStore,
    ExperimentRunner,
    Persona,
)
from llm_auditkit.experiments.planning import build_experiment_job_keys
from llm_auditkit.inference import (
    InferenceBatchError,
    InferenceConfig,
    InferenceError,
    InferenceOrchestrator,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
    TokenLogprob,
)


class RecordingAdapter:
    def __init__(
        self,
        *,
        failure_scenarios: set[str] | None = None,
        parse_error_scenarios: set[str] | None = None,
        systemic_failure_call: int | None = None,
    ) -> None:
        self.failure_scenarios = failure_scenarios or set()
        self.parse_error_scenarios = parse_error_scenarios or set()
        self.systemic_failure_call = systemic_failure_call
        self.render_calls: list[list[str]] = []
        self.sync_calls: list[list[str]] = []
        self.async_calls: list[list[str]] = []

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        del models
        self.render_calls.append(_scenario_ids(requests))
        return list(
            reversed(
                [
                    RenderedPrompt(
                        request_id=request.request_id,
                        user_prompt=f"rendered:{request.prompt}",
                        system_prompt=f"rendered:{request.system_prompt}",
                    )
                    for request in requests
                ]
            )
        )

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        del models
        self.sync_calls.append(_scenario_ids(requests))
        return self._results(requests, len(self.sync_calls))

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        del models
        self.async_calls.append(_scenario_ids(requests))
        return self._results(requests, len(self.async_calls))

    def _results(
        self,
        requests: Sequence[InferenceRequest],
        call_number: int,
    ) -> list[InferenceResult]:
        results = [_result_for_request(request, self) for request in requests]
        if self.systemic_failure_call == call_number:
            results[0].request_id = "unknown-request"
        return list(reversed(results))


def _scenario_ids(requests: Sequence[InferenceRequest]) -> list[str]:
    return [str(request.metadata["scenario_id"]) for request in requests]


def _result_for_request(
    request: InferenceRequest,
    adapter: RecordingAdapter,
) -> InferenceResult:
    scenario_id = str(request.metadata["scenario_id"])
    rendered_prompt = RenderedPrompt(
        request_id=request.request_id,
        user_prompt=f"rendered:{request.prompt}",
        system_prompt=f"rendered:{request.system_prompt}",
    )
    if scenario_id in adapter.failure_scenarios:
        return InferenceResult(
            request_id=request.request_id,
            model_config_id=request.model_config_id,
            content=None,
            metadata={},
            error=InferenceError("ProviderError", "request failed after retries"),
            rendered_prompt=rendered_prompt,
        )

    token_logprobs = [
        TokenLogprob("Yes", -0.2),
        TokenLogprob("No", -0.4),
    ]
    if scenario_id in adapter.parse_error_scenarios:
        token_logprobs = [
            TokenLogprob("No", -0.2),
            TokenLogprob("No", -0.4),
        ]
    return InferenceResult(
        request_id=request.request_id,
        model_config_id=request.model_config_id,
        content='{"Applicant 1":"Yes","Applicant 2":"No"}',
        metadata={},
        structured_content={"Applicant 1": "Yes", "Applicant 2": "No"},
        comment="Interview the first applicant.",
        token_logprobs=token_logprobs,
        rendered_prompt=rendered_prompt,
    )


def _dataset(count: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": [f"scenario-{position}" for position in range(1, count + 1)],
            "job_posting": [f"Posting {position}" for position in range(1, count + 1)],
            "resume_1": [f"Resume {position}A" for position in range(1, count + 1)],
            "resume_2": [f"Resume {position}B" for position in range(1, count + 1)],
            "caller_metadata": [f"keep-{position}" for position in range(1, count + 1)],
        }
    )


def _config(
    *,
    batch_size: int = 2,
    save_after_each_batch: bool = True,
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="experiment-1",
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column="job_posting",
            resume_columns=["resume_1", "resume_2"],
        ),
        prompt_template="Applicant 1: {resume_1}\nApplicant 2: {resume_2}",
        personas=[
            Persona(
                "manager",
                "Manager",
                "Hiring manager persona",
                "Evaluate applicants",
            )
        ],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    "model-1",
                    "openai",
                    "test-model",
                    {"logprobs": True},
                )
            ],
            batch_size=batch_size,
        ),
        save_after_each_batch=save_after_each_batch,
    )


def _runner(
    tmp_path: Path,
    adapter: RecordingAdapter,
    *,
    filename: str = "results.csv",
) -> tuple[ExperimentRunner, ExperimentResultStore]:
    store = ExperimentResultStore(tmp_path / filename)
    runner = ExperimentRunner(InferenceOrchestrator(adapter), store)
    return runner, store


def _track_writes(
    store: ExperimentResultStore,
    monkeypatch: pytest.MonkeyPatch,
) -> list[pd.DataFrame]:
    writes: list[pd.DataFrame] = []
    original_write = store._atomic_write

    def tracked_write(output_dataset: pd.DataFrame) -> None:
        writes.append(output_dataset.copy(deep=True))
        original_write(output_dataset)

    monkeypatch.setattr(store, "_atomic_write", tracked_write)
    return writes


def _normalize_missing(dataset: pd.DataFrame) -> pd.DataFrame:
    return dataset.astype(object).where(dataset.notna(), "<missing>")


def test_preview_renders_only_the_selected_pending_batch(tmp_path: Path) -> None:
    adapter = RecordingAdapter()
    runner, _ = _runner(tmp_path, adapter)

    preview = runner.preview(_dataset(), _config(), batch_number=2)

    assert preview.batch_number == 2
    assert preview.total_batches == 2
    assert adapter.render_calls == [["scenario-3"]]
    assert adapter.sync_calls == []
    assert adapter.async_calls == []
    assert len(preview.prompts) == 1
    assert preview.prompts[0].system_prompt == "rendered:Evaluate applicants"


def test_sync_run_checkpoints_each_batch_in_canonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingAdapter()
    runner, store = _runner(tmp_path, adapter)
    writes = _track_writes(store, monkeypatch)

    output = runner.run(_dataset(), _config())

    assert adapter.sync_calls == [
        ["scenario-1", "scenario-2"],
        ["scenario-3"],
    ]
    assert adapter.async_calls == []
    assert [len(checkpoint) for checkpoint in writes] == [2, 3]
    assert output["scenario_id"].tolist() == [
        "scenario-1",
        "scenario-2",
        "scenario-3",
    ]
    assert output["picks"].tolist() == ["[1,0]", "[1,0]", "[1,0]"]
    assert output[["logprob1", "logprob2"]].values.tolist() == [
        [-0.2, -0.4],
        [-0.2, -0.4],
        [-0.2, -0.4],
    ]


def test_runner_derives_and_checkpoints_ids_without_mutating_input(
    tmp_path: Path,
) -> None:
    dataset = _dataset(count=2).drop(columns=["scenario_id"])
    config = _config()
    expected_ids = [
        key.scenario_id for key in build_experiment_job_keys(dataset, config)
    ]
    adapter = RecordingAdapter()
    runner, store = _runner(tmp_path, adapter)

    output = runner.run(dataset, config)
    resumed = store.initialize(dataset, config)

    assert "scenario_id" not in dataset.columns
    assert expected_ids == output["scenario_id"].tolist()
    assert expected_ids == resumed["scenario_id"].tolist()
    assert all(scenario_id.startswith("scenario:") for scenario_id in expected_ids)


def test_async_run_uses_native_async_batches_and_matches_sync_output(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    config = _config()
    sync_adapter = RecordingAdapter()
    async_adapter = RecordingAdapter()
    sync_runner, _ = _runner(tmp_path, sync_adapter, filename="sync.csv")
    async_runner, _ = _runner(tmp_path, async_adapter, filename="async.csv")

    sync_output = sync_runner.run(dataset, config)
    async_output = asyncio.run(async_runner.run_async(dataset, config))

    assert async_adapter.sync_calls == []
    assert async_adapter.async_calls == [
        ["scenario-1", "scenario-2"],
        ["scenario-3"],
    ]
    pd.testing.assert_frame_equal(
        _normalize_missing(sync_output),
        _normalize_missing(async_output),
        check_dtype=False,
    )


def test_disabled_incremental_saving_writes_only_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingAdapter()
    runner, store = _runner(tmp_path, adapter)
    writes = _track_writes(store, monkeypatch)

    output = runner.run(
        _dataset(),
        _config(save_after_each_batch=False),
    )

    assert len(adapter.sync_calls) == 2
    assert len(writes) == 1
    assert len(writes[0]) == 3
    assert len(output) == 3


def test_resume_retries_failures_skips_completed_jobs_and_noops_when_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(count=2)
    config = _config()
    first_adapter = RecordingAdapter(failure_scenarios={"scenario-1"})
    first_runner, store = _runner(tmp_path, first_adapter)
    first_output = first_runner.run(dataset, config)

    assert first_output["error_type"].tolist()[0] == "ProviderError"
    assert pd.isna(first_output["error_type"].tolist()[1])

    retry_adapter = RecordingAdapter()
    retry_runner = ExperimentRunner(InferenceOrchestrator(retry_adapter), store)
    retry_output = retry_runner.run(dataset, config)

    assert retry_adapter.sync_calls == [["scenario-1"]]
    assert retry_output["scenario_id"].tolist() == ["scenario-1", "scenario-2"]
    assert retry_output["error_type"].isna().all()
    assert len(store.completed_keys(retry_output, dataset, config)) == 2

    no_op_adapter = RecordingAdapter()
    no_op_runner = ExperimentRunner(InferenceOrchestrator(no_op_adapter), store)
    writes = _track_writes(store, monkeypatch)
    no_op_output = no_op_runner.run(dataset, config)

    assert no_op_adapter.sync_calls == []
    assert writes == []
    assert len(no_op_output) == 2


def test_domain_parse_error_is_recorded_and_later_batches_continue(
    tmp_path: Path,
) -> None:
    adapter = RecordingAdapter(parse_error_scenarios={"scenario-1"})
    runner, store = _runner(tmp_path, adapter)

    output = runner.run(_dataset(), _config())

    assert len(adapter.sync_calls) == 2
    assert output.loc[0, "error_type"] == "ExperimentResponseParseError"
    assert output.loc[1:, "error_type"].isna().all()
    assert len(store.completed_keys(output, _dataset(), _config())) == 2


def test_systemic_inference_failure_stops_before_a_later_batch(
    tmp_path: Path,
) -> None:
    adapter = RecordingAdapter(systemic_failure_call=2)
    runner, store = _runner(tmp_path, adapter)
    dataset = _dataset(count=5)
    config = _config()

    with pytest.raises(InferenceBatchError, match="unknown request ID"):
        runner.run(dataset, config)

    assert adapter.sync_calls == [
        ["scenario-1", "scenario-2"],
        ["scenario-3", "scenario-4"],
    ]
    checkpoint = store.initialize(dataset, config)
    assert checkpoint["scenario_id"].tolist() == ["scenario-1", "scenario-2"]


def test_empty_dataset_writes_header_without_calling_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingAdapter()
    runner, store = _runner(tmp_path, adapter)
    writes = _track_writes(store, monkeypatch)

    output = runner.run(_dataset().iloc[0:0], _config())

    assert output.empty
    assert store.output_path.exists()
    assert len(writes) == 1
    assert adapter.sync_calls == []
