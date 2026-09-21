"""Tests for strict YAML-backed template-generation run configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_auditkit.templates import (
    TemplateGenerationConfigurationError,
    load_template_generation_run_config,
)


_VALID_YAML = """\
dataset:
  path: ../data/job_postings.csv
  job_posting_column: job_text
  context_columns:
    city: city_name

prompt:
  template_path: prompts/resume_templates.txt
  system_template_path: prompts/resume_system.txt

output:
  path: ../results/templates.csv

generation:
  templates_per_scenario: 4
  required_placeholders:
    - name
    - address
  model_config_id: openai-template-v1

execution:
  mode: async
  batch_size: 5
  save_after_each_result: true

inference:
  models:
    - config_id: openai-template-v1
      provider: openai
      model: gpt-4o-2024-08-06
      parameters:
        temperature: 0
        max_tokens: 6000
"""


def _write_config(tmp_path: Path, contents: str = _VALID_YAML) -> Path:
    config_directory = tmp_path / "configs"
    config_directory.mkdir()
    prompt_directory = config_directory / "prompts"
    prompt_directory.mkdir()
    (prompt_directory / "resume_templates.txt").write_text(
        "Generate {templates_per_scenario} templates for {job_posting} in {city}. "
        "Preserve {required_placeholders}.",
        encoding="utf-8",
    )
    (prompt_directory / "resume_system.txt").write_text(
        "You create realistic resumes in {city}.",
        encoding="utf-8",
    )
    config_path = config_directory / "template_generation.yaml"
    config_path.write_text(contents, encoding="utf-8")
    return config_path


def test_yaml_loads_paths_mode_prompts_and_typed_generation_config(
    tmp_path: Path,
) -> None:
    run_config = load_template_generation_run_config(_write_config(tmp_path))

    assert run_config.dataset_path == (tmp_path / "data/job_postings.csv").resolve()
    assert run_config.output_path == (tmp_path / "results/templates.csv").resolve()
    assert run_config.mode == "async"
    generation = run_config.generation_config
    assert generation.templates_per_scenario == 4
    assert generation.dataset_schema.job_posting_column == "job_text"
    assert generation.dataset_schema.context_columns == {"city": "city_name"}
    assert generation.prompt_template == (
        "Generate {templates_per_scenario} templates for {job_posting} in {city}. "
        "Preserve {required_placeholders}."
    )
    assert generation.system_prompt_template == (
        "You create realistic resumes in {city}."
    )
    assert generation.required_placeholders == ["name", "address"]
    assert generation.inference.batch_size == 5
    assert generation.inference.models[0].parameters == {
        "temperature": 0,
        "max_tokens": 6000,
    }
    assert generation.model_config_id == "openai-template-v1"
    assert generation.save_after_each_result is True


def test_system_prompt_path_is_optional(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "  system_template_path: prompts/resume_system.txt\n",
            "",
        ),
    )

    run_config = load_template_generation_run_config(config_path)

    assert run_config.generation_config.system_prompt_template is None


@pytest.mark.parametrize("rendered_mode", ["parallel", "ASYNC", "1", "[async]"])
def test_execution_mode_must_be_explicit_sync_or_async(
    tmp_path: Path,
    rendered_mode: str,
) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace("mode: async", f"mode: {rendered_mode}"),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="execution.mode",
    ):
        load_template_generation_run_config(config_path)


def test_unknown_yaml_field_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "  batch_size: 5",
            "  batch_size: 5\n  max_retries: 3",
        ),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="max_retries",
    ):
        load_template_generation_run_config(config_path)


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "  batch_size: 5",
            "  batch_size: 5\n  batch_size: 10",
        ),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="duplicate key",
    ):
        load_template_generation_run_config(config_path)


def test_missing_required_yaml_field_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace("  save_after_each_result: true\n", ""),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="save_after_each_result",
    ):
        load_template_generation_run_config(config_path)


def test_yaml_uses_existing_domain_validation(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "model_config_id: openai-template-v1",
            "model_config_id: missing-model",
        ),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="model_config_id",
    ):
        load_template_generation_run_config(config_path)


def test_dataset_and_output_paths_cannot_collide(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "../results/templates.csv",
            "../data/job_postings.csv",
        ),
    )

    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="different files",
    ):
        load_template_generation_run_config(config_path)


def test_output_path_must_be_a_csv_file(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            "../results/templates.csv",
            "../results/templates.json",
        ),
    )

    with pytest.raises(TemplateGenerationConfigurationError, match=".csv"):
        load_template_generation_run_config(config_path)


@pytest.mark.parametrize(
    ("field_name", "path", "message"),
    [
        ("template_path", "prompts/missing.txt", "does not exist"),
        ("system_template_path", "prompts/resume_system.md", ".txt"),
    ],
)
def test_prompt_paths_must_reference_existing_text_files(
    tmp_path: Path,
    field_name: str,
    path: str,
    message: str,
) -> None:
    original_path = (
        "prompts/resume_templates.txt"
        if field_name == "template_path"
        else "prompts/resume_system.txt"
    )
    config_path = _write_config(
        tmp_path,
        _VALID_YAML.replace(
            f"{field_name}: {original_path}",
            f"{field_name}: {path}",
        ),
    )

    with pytest.raises(TemplateGenerationConfigurationError, match=message):
        load_template_generation_run_config(config_path)


def test_configuration_path_must_be_an_existing_yaml_file(tmp_path: Path) -> None:
    with pytest.raises(
        TemplateGenerationConfigurationError,
        match="does not exist",
    ):
        load_template_generation_run_config(tmp_path / "missing.yaml")

    text_path = tmp_path / "template_generation.txt"
    text_path.write_text(_VALID_YAML, encoding="utf-8")
    with pytest.raises(TemplateGenerationConfigurationError, match=".yaml"):
        load_template_generation_run_config(text_path)


def test_repository_example_configuration_is_loadable() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    run_config = load_template_generation_run_config(
        repository_root
        / "configs/template_generation/synthetic_template_generation.yaml"
    )

    assert run_config.mode == "async"
    assert run_config.dataset_path.is_file()
    assert run_config.output_path == (
        repository_root / "examples/output/synthetic_template_generation.csv"
    ).resolve()
