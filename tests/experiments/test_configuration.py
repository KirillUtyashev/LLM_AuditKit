"""Tests for strict YAML-backed experiment run configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_auditkit.experiments import (
    ExperimentConfigurationError,
    load_experiment_run_config,
)


_VALID_YAML = """\
experiment_id: real-experiment-v1

dataset:
  path: ../data/populated.csv
  scenario_id_column: scenario_id
  job_posting_column: job_posting
  resume_columns:
    - resume_1
    - resume_2
  context_columns:
    city: city

output:
  path: ../results/experiment.csv

execution:
  mode: async
  batch_size: 10
  save_after_each_batch: true

personas:
  - id: manager-v1
    name: Hiring manager
    description: You are the hiring manager responsible for this role.

inference:
  models:
    - config_id: openai-model-v1
      provider: openai
      model: gpt-4.1-nano
      parameters:
        temperature: 0
        logprobs: true
"""


def _write_config(tmp_path: Path, contents: str = _VALID_YAML) -> Path:
    config_directory = tmp_path / "configs"
    config_directory.mkdir()
    config_path = config_directory / "experiment.yaml"
    config_path.write_text(contents, encoding="utf-8")
    return config_path


def test_yaml_loads_run_paths_mode_and_typed_experiment_config(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path)

    run_config = load_experiment_run_config(config_path)

    assert run_config.dataset_path == (tmp_path / "data/populated.csv").resolve()
    assert run_config.output_path == (
        tmp_path / "results/experiment.csv"
    ).resolve()
    assert run_config.mode == "async"
    experiment = run_config.experiment_config
    assert experiment.experiment_id == "real-experiment-v1"
    assert experiment.dataset_schema.resume_columns == ["resume_1", "resume_2"]
    assert experiment.dataset_schema.context_columns == {"city": "city"}
    assert experiment.inference.batch_size == 10
    assert experiment.inference.models[0].parameters == {
        "temperature": 0,
        "logprobs": True,
    }
    assert experiment.save_after_each_batch is True


@pytest.mark.parametrize("rendered_mode", ["parallel", "ASYNC", "1", "[async]"])
def test_execution_mode_must_be_explicit_sync_or_async(
    tmp_path: Path,
    rendered_mode: str,
) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace("mode: async", f"mode: {rendered_mode}"),
    )

    with pytest.raises(ExperimentConfigurationError, match="execution.mode"):
        load_experiment_run_config(config_path)


def test_unknown_yaml_field_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "  batch_size: 10",
            "  batch_size: 10\n  max_retries: 5",
        ),
    )

    with pytest.raises(ExperimentConfigurationError, match="max_retries"):
        load_experiment_run_config(config_path)


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "  batch_size: 10",
            "  batch_size: 10\n  batch_size: 20",
        ),
    )

    with pytest.raises(ExperimentConfigurationError, match="duplicate key"):
        load_experiment_run_config(config_path)


def test_missing_required_yaml_field_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace("  save_after_each_batch: true\n", ""),
    )

    with pytest.raises(ExperimentConfigurationError, match="save_after_each_batch"):
        load_experiment_run_config(config_path)


def test_yaml_uses_existing_domain_validation(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace("        logprobs: true", "        logprobs: false"),
    )

    with pytest.raises(ExperimentConfigurationError, match="logprobs"):
        load_experiment_run_config(config_path)


def test_dataset_and_output_paths_cannot_collide(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "../results/experiment.csv",
            "../data/populated.csv",
        ),
    )

    with pytest.raises(ExperimentConfigurationError, match="different files"):
        load_experiment_run_config(config_path)


def test_configuration_path_must_be_an_existing_yaml_file(tmp_path: Path) -> None:
    with pytest.raises(ExperimentConfigurationError, match="does not exist"):
        load_experiment_run_config(tmp_path / "missing.yaml")

    text_path = tmp_path / "experiment.txt"
    text_path.write_text(_VALID_YAML, encoding="utf-8")
    with pytest.raises(ExperimentConfigurationError, match=".yaml"):
        load_experiment_run_config(text_path)


def test_repository_example_configuration_is_loadable() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    run_config = load_experiment_run_config(
        repository_root / "examples/experiment_execution.yaml"
    )

    assert run_config.mode == "async"
    assert run_config.dataset_path.is_file()
    assert run_config.output_path == (
        repository_root / "examples/output/synthetic_experiment_results.csv"
    ).resolve()
