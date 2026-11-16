"""Credential-free tests of the user-facing phase runner and its review gates."""

import importlib.util
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from llm_auditkit.inference import InferenceResult, RenderedPrompt, TokenLogprob


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("auditkit_pipeline_script", ROOT / "scripts/run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def write_yaml(path, value):
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


class OfflineAdapter:
    def __init__(self):
        self.calls = []

    def render_batch(self, requests, models):
        return [RenderedPrompt(request.request_id, request.prompt, request.system_prompt) for request in requests]

    def results(self, requests, mode):
        self.calls.extend((mode, request.model_config_id) for request in requests)
        results = []
        for request in requests:
            tokens = []
            if request.model_config_id == "templates":
                answer = {field.name: field.name + ": Applicant {{name}}. Group: {{group}}."
                          for field in request.response_format.fields}
                content = json.dumps(answer)
            else:
                number = int(re.search(r"SN(\d+)", request.prompt)[1])
                groups = [int(group) for group in re.findall(r"Group: ([01])", request.prompt)]
                answer = {}
                tokens.append(TokenLogprob("{", 0.0))
                for slot, group in enumerate(groups, 1):
                    selected = (number % 4 != 0) if group else (number % 4 == 1)
                    decision = "Yes" if selected else "No"
                    answer[f"Applicant {slot}"] = decision
                    tokens.extend([
                        TokenLogprob(f'"Applicant {slot}":"', 0.0),
                        TokenLogprob(decision, math.log(0.995 if selected else 0.98)),
                        TokenLogprob('",' if slot < len(groups) else '"}', 0.0),
                    ])
                content = "".join(token.token for token in tokens)
            results.append(InferenceResult(
                request.request_id, request.model_config_id, content, request.metadata.copy(),
                structured_content=answer, token_logprobs=tokens,
                rendered_prompt=RenderedPrompt(request.request_id, request.prompt, request.system_prompt),
            ))
        return results

    def execute_batch(self, requests, models):
        return self.results(requests, "sync")

    async def execute_batch_async(self, requests, models):
        return self.results(requests, "async")


@pytest.fixture
def workflow(tmp_path, runner, monkeypatch):
    (tmp_path / "template.txt").write_text(
        "For {job_posting} in {city}, generate {templates_per_scenario} layouts using {required_placeholders}.",
        encoding="utf-8",
    )
    (tmp_path / "question.txt").write_text(
        "{job_posting}\nApplicant 1: {resume_1}\nApplicant 2: {resume_2}", encoding="utf-8"
    )
    (tmp_path / "trait.txt").write_text("You hire in {city}.", encoding="utf-8")
    (tmp_path / "instruction.txt").write_text("Review applicants.", encoding="utf-8")
    jobs, replacements = [], []
    for number in range(1, 17):
        scenario = f"{number:03d}"
        jobs.append({"scenario_id": scenario, "Text": f"SN{number:04d} Office clerk.",
                     "metadata_json": json.dumps({"city": "SyntheticCity", "year": 2010})})
        for slot in (1, 2):
            replacements.append({"scenario_id": scenario, "template_id": f"layout-{slot}",
                                 "candidate_id": f"assigned-person-{scenario}-{slot}", "candidate_order": slot,
                                 "name": f"Person {scenario}-{slot}", "group": slot - 1, "treatment": slot - 1})
    pd.DataFrame(jobs).to_csv(tmp_path / "jobs.csv", index=False)
    pd.DataFrame(replacements).iloc[::-1].to_csv(tmp_path / "replacements.csv", index=False)
    model = lambda name: [{"config_id": name, "provider": "test", "model": "test",
                           "parameters": {"logprobs": True} if name == "review" else {}}]
    templates = {
        "dataset": {"path": "jobs.csv", "job_posting_column": "Text", "context_columns": {"city": "city"}},
        "prompt": {"template_path": "template.txt"}, "output": {"path": "templates.csv"},
        "generation": {"templates_per_scenario": 2, "required_placeholders": ["name", "group"], "model_config_id": "templates"},
        "execution": {"mode": "async", "batch_size": 5, "save_after_each_result": True},
        "inference": {"models": model("templates")},
    }
    experiments = {
        "experiment_id": "runner-fixture", "dataset": {"path": "populated.csv", "job_posting_column": "Text",
            "resume_columns": ["resume_1", "resume_2"], "context_columns": {"city": "city"}},
        "prompt": {"template_path": "question.txt"}, "output": {"path": "experiments.csv"},
        "execution": {"mode": "async", "batch_size": 5, "save_after_each_batch": True},
        "personas": [{"id": "reviewer", "name": "Reviewer", "trait_template_path": "trait.txt",
                      "instruction_path": "instruction.txt"}], "inference": {"models": model("review")},
    }
    preparation = {"input_format": "auditkit", "input_paths": ["experiments.csv"], "output_path": "ready.csv",
                   "audit_id": "researcher-assigned-runner-fixture", "candidate_covariates": ["treatment"]}
    estimation = {"data_path": "ready.csv", "dataset_id": "inspected-fixture", "model_id": "treatment-fe",
                  "outcome_variable": "pick", "explanatory_variables": ["treatment"], "control_variables": [],
                  "fixed_effects": ["scenario_id"], "cluster_variables": ["scenario_id"],
                  "estimation_group_variables": ["city", "year"], "output_directory": "regression"}
    rendering = {"results_paths": ["regression/regression_results.csv"], "output_path": "regression.png",
                 "outcome_variable": "pick", "term": "treatment", "period_variable": "year",
                 "y_limits": [-0.1, 1.0], "width": 6, "height": 4, "dpi": 100}
    root = {"templates": "templates.yaml", "experiments": "experiments.yaml",
            "metadata_columns": {"city": "city", "year": "year"},
            "population": {"replacements_path": "replacements.csv", "output_path": "populated.csv",
                           "template_columns": {"layout-1": "template_1", "layout-2": "template_2"},
                           "placeholder_columns": {"name": "name", "group": "group"}},
            "regression": {"preparation": "prepare.yaml", "estimation": "estimate.yaml", "rendering": "render.yaml"}}
    configs = {"pipeline": root, "templates": templates, "experiments": experiments,
               "prepare": preparation, "estimate": estimation, "render": rendering}
    for name, value in configs.items():
        write_yaml(tmp_path / f"{name}.yaml", value)
    adapter = OfflineAdapter()
    monkeypatch.setattr(runner, "EDSLAdapter", lambda: adapter)
    from llm_auditkit.experiments import cli as experiment_cli
    monkeypatch.setattr(experiment_cli, "EDSLAdapter", lambda: adapter)
    real_r = runner._r_command
    real_which = shutil.which
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/fake/Rscript" if name == "Rscript" else real_which(name))
    r_calls = []
    monkeypatch.setattr(runner, "_r_command", lambda script, path: r_calls.append((script, path)))
    return SimpleNamespace(path=tmp_path / "pipeline.yaml", directory=tmp_path, configs=configs,
                           adapter=adapter, r_calls=r_calls, real_r=real_r, real_which=real_which)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_real_python_stages_stop_at_review_gates_and_resume(runner, workflow, mode, capsys):
    for stage in ("templates", "experiments"):
        workflow.configs[stage]["execution"]["mode"] = mode
        write_yaml(workflow.directory / f"{stage}.yaml", workflow.configs[stage])
    command = ["--config", str(workflow.path)]
    assert runner.main(command + ["--check"]) == 0
    assert not workflow.adapter.calls and not workflow.r_calls
    assert runner.main(command + ["--phase", "templates"]) == 0
    assert not (workflow.directory / "populated.csv").exists()
    assert not (workflow.directory / "experiments.csv").exists()
    assert runner.main(command + ["--phase", "population"]) == 0
    populated = pd.read_csv(workflow.directory / "populated.csv", dtype={"scenario_id": str})
    assert populated.scenario_id.iloc[0] == "001"
    assert populated.candidate_1_id.iloc[0] == "assigned-person-001-1"
    assert populated.resume_2.iloc[0] == "template_2: Applicant Person 001-2. Group: 1."
    assert not workflow.r_calls
    assert runner.main(command + ["--phase", "experiments"]) == 0
    assert [call[0] for call in workflow.r_calls] == ["prepare_regression_data.R"]
    native = pd.read_csv(workflow.directory / "experiments.csv")
    assert len(native) == 16 and native.error_type.isna().all()
    assert native.pick1.sum() == 4 and native.pick2.sum() == 12
    assert len(workflow.adapter.calls) == 32
    assert {call[0] for call in workflow.adapter.calls} == {mode}
    # Completion remains owned by the existing stores, not a second workflow cache.
    for phase in ("templates", "population", "experiments"):
        assert runner.main(command + ["--phase", phase]) == 0
    assert len(workflow.adapter.calls) == 32
    assert runner.main(command + ["--phase", "analysis"]) == 0
    assert [call[0] for call in workflow.r_calls][-2:] == ["run_regression.R", "render_regression_plot.R"]
    captured = capsys.readouterr()
    assert "Inspect" in captured.out
    assert "Office clerk" not in captured.out


@pytest.mark.parametrize("change", ["population_link", "ocr_link", "candidate_order", "model_scope", "r_format",
                                   "r_input", "r_estimate", "r_render", "overwrite_source", "overwrite_prompt", "placeholders"])
def test_bad_wiring_stops_before_any_provider_call(runner, workflow, change):
    root, configs = workflow.configs["pipeline"], workflow.configs
    if change == "population_link":
        root["population"]["output_path"] = "wrong.csv"
    elif change == "placeholders":
        root["population"]["placeholder_columns"].pop("name")
    elif change == "candidate_order":
        configs["experiments"]["dataset"]["resume_columns"].reverse()
    elif change == "model_scope":
        configs["experiments"]["inference"]["models"].append(
            {"config_id": "other", "provider": "test", "model": "test", "parameters": {"logprobs": True}})
    elif change == "r_format":
        configs["prepare"]["input_format"] = "canonical"
    elif change == "r_input":
        configs["prepare"]["input_paths"] = ["wrong.csv"]
    elif change == "r_estimate":
        configs["estimate"]["data_path"] = "wrong.csv"
    elif change == "r_render":
        configs["render"]["results_paths"] = ["wrong.csv"]
    elif change == "overwrite_source":
        configs["templates"]["output"]["path"] = "replacements.csv"
    elif change == "overwrite_prompt":
        configs["render"]["output_path"] = "question.txt"
    else:
        root["ocr"] = str(ROOT / "configs/ocr/newspaper.yaml")
    for name, value in configs.items():
        write_yaml(workflow.directory / f"{name}.yaml", value)
    with pytest.raises(runner.PipelineError):
        runner.load_config(workflow.path)
    assert runner.main(["--config", str(workflow.path), "--phase", "templates"]) == 1
    assert not workflow.adapter.calls and not workflow.r_calls


def test_config_duplicates_and_unknown_keys_are_not_ignored(runner, workflow):
    with workflow.path.open("a", encoding="utf-8") as stream:
        stream.write("templates: another.yaml\n")
    with pytest.raises(runner.PipelineError, match="unique"):
        runner.load_config(workflow.path)
    workflow.configs["pipeline"]["surprise"] = True
    write_yaml(workflow.path, workflow.configs["pipeline"])
    with pytest.raises(runner.PipelineError, match="unknown"):
        runner.load_config(workflow.path)


def test_checked_in_newspaper_workflow_is_wired_without_loading_private_inputs(runner):
    config = runner.load_config(ROOT / "configs/pipeline/newspaper.yaml")
    assert config.ocr_path == ROOT / "configs/ocr/newspaper.yaml"
    assert config.templates.mode == config.experiments.mode == "async"
    assert config.population_path == config.experiments.dataset_path


@pytest.mark.parametrize("bad", ["overwrite", "missing_key", "not_object", "invalid_json", "missing_year_mapping"])
def test_metadata_extraction_fails_before_spending_tokens(runner, workflow, bad):
    jobs = pd.read_csv(workflow.directory / "jobs.csv", dtype=str)
    if bad == "overwrite":
        jobs["city"] = "existing value"
    elif bad == "missing_key":
        jobs.loc[0, "metadata_json"] = '{"year":2010}'
    elif bad == "not_object":
        jobs.loc[0, "metadata_json"] = '[]'
    elif bad == "missing_year_mapping":
        workflow.configs["pipeline"]["metadata_columns"].pop("year")
        write_yaml(workflow.path, workflow.configs["pipeline"])
    else:
        jobs.loc[0, "metadata_json"] = 'not json'
    jobs.to_csv(workflow.directory / "jobs.csv", index=False)
    assert runner.main(["--config", str(workflow.path), "--phase", "templates"]) == 1
    assert not workflow.adapter.calls


def test_invalid_assignment_order_cannot_replace_population(runner, workflow):
    config = runner.load_config(workflow.path)
    runner.run_phase(config, "templates")
    runner.run_phase(config, "population")
    original = config.population_path.read_bytes()
    replacements = pd.read_csv(config.replacements_path, dtype=str)
    replacements.loc[0, "candidate_order"] = "1.5"
    replacements.to_csv(config.replacements_path, index=False)
    assert runner.main(["--config", str(workflow.path), "--phase", "population"]) == 1
    assert config.population_path.read_bytes() == original


def test_ocr_phase_delegates_and_does_not_start_generation(runner, workflow, monkeypatch):
    config = runner.load_config(workflow.path)
    calls = []
    monkeypatch.setattr(runner, "ocr_main", lambda args: calls.append(args) or 0)
    with pytest.raises(runner.PipelineError, match="No OCR config"):
        runner.run_phase(config, "ocr")
    config.ocr_path = workflow.directory / "ocr.yaml"
    runner.run_phase(config, "ocr")
    assert calls == [["--config", str(config.ocr_path)]]
    assert not workflow.adapter.calls
    monkeypatch.setattr(runner, "ocr_main", lambda args: 1)
    with pytest.raises(runner.PipelineError, match="OCR failed"):
        runner.run_phase(config, "ocr")


def test_failed_experiment_never_prepares_or_estimates(runner, workflow, monkeypatch):
    monkeypatch.setattr(runner, "experiment_main", lambda args: 1)
    assert runner.main(["--config", str(workflow.path), "--phase", "experiments"]) == 1
    assert not workflow.r_calls
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner, "experiment_main", lambda args: pytest.fail("must check R before spending tokens"))
    assert runner.main(["--config", str(workflow.path), "--phase", "experiments"]) == 1


def test_failed_estimation_never_renders_and_does_not_echo_private_errors(runner, workflow, monkeypatch, capsys):
    calls = []
    def fail(script, path):
        calls.append(script)
        raise RuntimeError("private prompt or credential")
    monkeypatch.setattr(runner, "_r_command", fail)
    assert runner.main(["--config", str(workflow.path), "--phase", "analysis"]) == 1
    assert calls == ["run_regression.R"]
    assert "private prompt or credential" not in capsys.readouterr().err


def test_population_failure_preserves_previous_artifact(runner, workflow, monkeypatch):
    config = runner.load_config(workflow.path)
    runner.run_phase(config, "templates")
    runner.run_phase(config, "population")
    original = config.population_path.read_bytes()
    monkeypatch.setattr(runner.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("synthetic failure")))
    assert runner.main(["--config", str(workflow.path), "--phase", "population"]) == 1
    assert config.population_path.read_bytes() == original
    assert not list(workflow.directory.glob(".populated.csv.*"))


def test_r_commands_use_argument_lists_and_the_repository_environment(runner, workflow, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    workflow.real_r("run_regression.R", workflow.directory / "a config.yaml")
    assert calls == [((['Rscript', str(ROOT / 'scripts/run_regression.R'), '--config',
                        str(workflow.directory / 'a config.yaml')],), {"cwd": ROOT, "check": True})]


@pytest.mark.skipif(os.environ.get("LLM_AUDITKIT_RUN_R_INTEGRATION") != "1", reason="opt in to restored R environment")
def test_phase_runner_through_real_r_and_png(runner, workflow, monkeypatch):
    if not workflow.real_which("Rscript"):
        pytest.skip("Rscript is not installed")
    monkeypatch.setattr(runner, "_r_command", workflow.real_r)
    monkeypatch.setattr(runner.shutil, "which", workflow.real_which)
    for phase in ("templates", "population", "experiments"):
        assert runner.main(["--config", str(workflow.path), "--phase", phase]) == 0
    assert not (workflow.directory / "regression").exists()  # inspection gate
    ready = pd.read_csv(workflow.directory / "ready.csv")
    assert len(ready) == 32 and ready.pick.sum() == 16
    assert set(ready.audit_id) == {"researcher-assigned-runner-fixture"}
    assert runner.main(["--config", str(workflow.path), "--phase", "analysis"]) == 0
    coefficients = pd.read_csv(workflow.directory / "regression/regression_results.csv")
    assert coefficients.estimate.tolist() == pytest.approx([0.5] * 3)
    assert coefficients.n_used.eq(32).all()
    assert (workflow.directory / "regression.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
