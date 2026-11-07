"""Tests for YAML-configured experiment command dispatch."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentConfigurationError,
    ExperimentDatasetError,
    ExperimentDatasetSchema,
    ExperimentRunConfig,
    Persona,
)
from llm_auditkit.experiments import cli
from llm_auditkit.inference import (
    InferenceBatchPreview,
    InferenceConfig,
    ModelConfig,
    RenderedPrompt,
)


class FakeRunner:
    def __init__(self) -> None:
        self.preview_calls: list[int] = []
        self.sync_calls = 0
        self.async_calls = 0

    def preview(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
        batch_number: int = 1,
    ) -> InferenceBatchPreview:
        del dataset, config
        self.preview_calls.append(batch_number)
        return InferenceBatchPreview(
            batch_number=batch_number,
            total_batches=2,
            prompts=[RenderedPrompt("request-1", "user", "system")],
        )

    def run(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        del dataset, config
        self.sync_calls += 1
        return pd.DataFrame({"result": ["sync"]})

    async def run_async(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        del dataset, config
        self.async_calls += 1
        return pd.DataFrame({"result": ["async"]})


def _run_config(tmp_path: Path, mode: str) -> ExperimentRunConfig:
    return ExperimentRunConfig(
        dataset_path=tmp_path / "dataset.csv",
        output_path=tmp_path / "output.csv",
        mode=mode,  # type: ignore[arg-type]
        experiment_config=ExperimentConfig(
            experiment_id="experiment-1",
            dataset_schema=ExperimentDatasetSchema(
                job_posting_column="job_posting",
                resume_columns=["resume_1"],
            ),
            prompt_template="Applicant 1: {resume_1}",
            personas=[
                Persona(
                    "manager",
                    "Manager",
                    "Hiring manager",
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
                batch_size=1,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("mode", "expected_sync_calls", "expected_async_calls"),
    [("sync", 1, 0), ("async", 0, 1)],
)
def test_command_dispatches_configured_execution_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    expected_sync_calls: int,
    expected_async_calls: int,
) -> None:
    run_config = _run_config(tmp_path, mode)
    runner = FakeRunner()
    monkeypatch.setattr(cli, "load_experiment_run_config", lambda path: run_config)
    monkeypatch.setattr(cli, "_load_experiment_dataset", lambda config: pd.DataFrame())
    monkeypatch.setattr(cli, "_build_runner", lambda config: runner)

    exit_code = cli.main(["--config", "experiment.yaml"])

    assert exit_code == 0
    assert runner.sync_calls == expected_sync_calls
    assert runner.async_calls == expected_async_calls
    assert "Completed experiment rows: 1" in capsys.readouterr().out


def test_preview_only_renders_selected_batch_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_config = _run_config(tmp_path, "async")
    runner = FakeRunner()
    monkeypatch.setattr(cli, "load_experiment_run_config", lambda path: run_config)
    monkeypatch.setattr(cli, "_load_experiment_dataset", lambda config: pd.DataFrame())
    monkeypatch.setattr(cli, "_build_runner", lambda config: runner)

    exit_code = cli.main(
        [
            "--config",
            "experiment.yaml",
            "--preview-only",
            "--preview-batch",
            "2",
        ]
    )

    assert exit_code == 0
    assert runner.preview_calls == [2]
    assert runner.sync_calls == 0
    assert runner.async_calls == 0
    assert "System prompt:\nsystem" in capsys.readouterr().out


def test_command_csv_loader_preserves_string_scenario_ids(tmp_path: Path) -> None:
    run_config = _run_config(tmp_path, "sync")
    run_config.dataset_path.write_text(
        "scenario_id,job_posting,resume_1\n001,Posting,Resume\n",
        encoding="utf-8",
    )

    dataset = cli._load_experiment_dataset(run_config)

    assert dataset["scenario_id"].tolist() == ["001"]


def test_command_csv_loader_preserves_all_literal_strings(tmp_path: Path) -> None:
    run_config = _run_config(tmp_path, "sync")
    run_config.dataset_path.write_text(
        "scenario_id,job_posting,resume_1,case_id\n"
        "001,NA,00007,00009\n",
        encoding="utf-8",
    )

    dataset = cli._load_experiment_dataset(run_config)

    assert dataset.loc[0, "scenario_id"] == "001"
    assert dataset.loc[0, "job_posting"] == "NA"
    assert dataset.loc[0, "resume_1"] == "00007"
    assert dataset.loc[0, "case_id"] == "00009"


def test_command_csv_loader_does_not_require_scenario_ids(tmp_path: Path) -> None:
    run_config = _run_config(tmp_path, "sync")
    run_config.dataset_path.write_text(
        "job_posting,resume_1\nPosting,Resume\n",
        encoding="utf-8",
    )

    dataset = cli._load_experiment_dataset(run_config)

    assert list(dataset.columns) == ["job_posting", "resume_1", "scenario_id"]
    assert dataset.loc[0, "scenario_id"].startswith("scenario:")


def test_command_rejects_missing_or_non_csv_dataset(tmp_path: Path) -> None:
    missing = _run_config(tmp_path, "sync")
    with pytest.raises(ExperimentDatasetError, match="does not exist"):
        cli._load_experiment_dataset(missing)

    unsupported = _run_config(tmp_path, "sync")
    unsupported.dataset_path = tmp_path / "dataset.parquet"
    unsupported.dataset_path.write_text("not parquet", encoding="utf-8")
    with pytest.raises(ExperimentDatasetError, match="supports CSV"):
        cli._load_experiment_dataset(unsupported)


def test_execute_rejects_an_unvalidated_mode(tmp_path: Path) -> None:
    run_config = _run_config(tmp_path, "parallel")

    with pytest.raises(ExperimentConfigurationError, match="sync.*async"):
        cli._execute(FakeRunner(), pd.DataFrame(), run_config)
