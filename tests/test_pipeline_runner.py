"""Credential-free tests of the user-facing phase runner and its review gates."""

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from llm_auditkit.inference import InferenceResult, RenderedPrompt, TokenLogprob


ROOT = Path(__file__).resolve().parents[1]


def test_repository_launcher_works_without_editable_import_path(tmp_path):
    source = str(ROOT / "src")
    script = str(ROOT / "scripts/run_pipeline.py")
    configuration = str(ROOT / "tests/manual/newspaper_pipeline/pipeline.yaml")
    code = f'''
import runpy
import socket
import sys

source = {source!r}
sys.path[:] = [entry for entry in sys.path if entry != source]

class MissingEditableImport:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "llm_auditkit" and source not in sys.path:
            raise ModuleNotFoundError("Simulated missing editable import path")

def forbid_network(*args, **kwargs):
    raise AssertionError("Configuration check must not contact a service")

socket.getaddrinfo = forbid_network
socket.socket.connect = forbid_network
sys.meta_path.insert(0, MissingEditableImport())
sys.argv = [{script!r}, "--config", {configuration!r}, "--check"]
runpy.run_path({script!r}, run_name="__main__")
'''
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update({"PYTHON_DOTENV_DISABLED": "1", "EDSL_FETCH_TOKEN_PRICES": "False"})
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "configuration wiring is valid" in result.stdout


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
        root["ocr"] = str(ROOT / "tests/manual/newspaper_pipeline/ocr.yaml")
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
    config = runner.load_config(ROOT / "tests/manual/newspaper_pipeline/pipeline.yaml")
    assert config.ocr_path == ROOT / "tests/manual/newspaper_pipeline/ocr.yaml"
    assert config.templates.mode == config.experiments.mode == "async"
    assert config.population_path == config.experiments.dataset_path
    ocr = runner.load_ocr_run_config(config.ocr_path)
    assert len(ocr.documents) == 1
    document = ocr.documents[0]
    assert document.path.suffix == ".pdf"
    assert document.metadata["newspaper"] == "Chicago Daily Tribune"
    assert document.metadata["city"] == "Chicago"
    assert document.metadata["year"] == 1950
    assert document.metadata["publication_date"] == "1950-04-02"
    assert document.metadata["archive_page"] == "A6"
    assert document.metadata["source_document"] == "Classified Ad 36 -- No Title"
    assert "ProQuest" in document.metadata["source_collection"]
    assert "source_region" not in document.metadata  # Complete PDF, not a crop.
    output = ROOT / "tests/manual/newspaper_pipeline/local/chicago-1950-smoke"
    assert document.path.parent == output / "source"
    assert ocr.output_path.parent == config.templates.output_path.parent == output
    assert config.templates.output_path == output / "templates-gpt55-medium-parts.csv"
    assert config.templates.generation_config.response_mode == "parts"
    template_model, = config.templates.generation_config.inference.models
    assert template_model.model == "gpt-5.5"
    assert template_model.parameters == {
        "reasoning_effort": "medium", "max_tokens": 16000,
    }
    assert config.population_path.parent == config.prepared_path.parent == output
    assert config.sampling["unique_columns"] == ["name"]
    assert all("advertised work" in value for value in config.sampling["pools"]["qualification"])


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


def enable_sampling(workflow):
    population = workflow.configs["pipeline"]["population"]
    population["replacements_path"] = "sampled.csv"
    population["sampling"] = {
        "assignment_namespace": "synthetic-continuous-test-v1", "seed": 42,
        "unique_columns": ["name", "group"],
        "pools": {"name": ["Synthetic Alex", "Synthetic Casey", "Synthetic Jamie"],
                  "group": ["0", "1"], "treatment": ["0", "1"]},
    }
    write_yaml(workflow.path, workflow.configs["pipeline"])


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_continuous_sampling_real_python_stages_and_checkpoint_resume(runner, workflow, monkeypatch, mode):
    enable_sampling(workflow)
    for stage in ("templates", "experiments"):
        workflow.configs[stage]["execution"]["mode"] = mode
        write_yaml(workflow.directory / f"{stage}.yaml", workflow.configs[stage])
    loads = []
    original_load = runner._load_dataset

    def record_load(path, required):
        loads.append(path)
        return original_load(path, required)

    monkeypatch.setattr(runner, "_load_dataset", record_load)
    command = ["--config", str(workflow.path), "--run"]
    assert runner.main(command) == 0
    assert loads == [workflow.directory / "jobs.csv"]  # No CSV handoffs after generation.
    assert len(workflow.adapter.calls) == 32
    assert {call[0] for call in workflow.adapter.calls} == {mode}
    assert [call[0] for call in workflow.r_calls] == ["prepare_regression_data.R"]
    assignments = pd.read_csv(workflow.directory / "sampled.csv", dtype={"scenario_id": str})
    populated = pd.read_csv(workflow.directory / "populated.csv", dtype={"scenario_id": str})
    native = pd.read_csv(workflow.directory / "experiments.csv", dtype={"scenario_id": str})
    assert assignments.candidate_id.nunique() == 32 and len(populated) == len(native) == 16
    for assignment in assignments.itertuples():
        job = native.set_index("scenario_id").loc[assignment.scenario_id]
        assert job[f"candidate_{assignment.candidate_order}_id"] == assignment.candidate_id
        assert assignment.name in job[f"resume_{assignment.candidate_order}"]
    paths = [workflow.directory / name for name in ("sampled.csv", "populated.csv", "experiments.csv")]
    before = [path.read_bytes() for path in paths]
    assert runner.main(command) == 0
    assert [path.read_bytes() for path in paths] == before
    assert len(workflow.adapter.calls) == 32  # Stage-owned resume; no new model requests.
    assert [call[0] for call in workflow.r_calls] == ["prepare_regression_data.R"] * 2
    assert not (workflow.directory / "regression").exists()


def test_continuous_mode_supports_supplied_assignments(runner, workflow):
    assert runner.main(["--config", str(workflow.path), "--run"]) == 0
    native = pd.read_csv(workflow.directory / "experiments.csv")
    assert native.candidate_1_id.iloc[0] == "assigned-person-001-1"
    assert len(workflow.adapter.calls) == 32
    assert [call[0] for call in workflow.r_calls] == ["prepare_regression_data.R"]


def test_continuous_mode_runs_configured_ocr_first(runner, workflow, monkeypatch):
    enable_sampling(workflow)
    config = runner.load_config(workflow.path)
    # Mock only the external OCR command boundary. Its output is then consumed
    # by the real loader, generation, sampling, population and experiment APIs.
    jobs = (workflow.directory / "jobs.csv").read_bytes()
    (workflow.directory / "jobs.csv").unlink()
    config.ocr_path = workflow.directory / "ocr.yaml"
    calls = []

    def ocr(args):
        assert not workflow.adapter.calls
        calls.append(args)
        (workflow.directory / "jobs.csv").write_bytes(jobs)
        return 0

    monkeypatch.setattr(runner, "ocr_main", ocr)
    runner.run_continuous(config)
    assert calls == [["--config", str(config.ocr_path)]]
    assert len(workflow.adapter.calls) == 32 and len(workflow.r_calls) == 1


@pytest.mark.parametrize("missing", ["Rscript", "assignments"])
def test_continuous_preflight_stops_before_paid_work(runner, workflow, monkeypatch, missing):
    if missing == "Rscript":
        monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    else:
        (workflow.directory / "replacements.csv").unlink()
    monkeypatch.setattr(runner, "ocr_main", lambda args: pytest.fail("OCR must not run"))
    assert runner.main(["--config", str(workflow.path), "--run"]) == 1
    assert not workflow.adapter.calls and not workflow.r_calls


@pytest.mark.parametrize("bad", ["pool", "seed", "missing_pool", "overwrite_source", "overwrite_stage", "unknown"])
def test_sampling_configuration_is_checked_before_loading_data(runner, workflow, bad):
    enable_sampling(workflow)
    population = workflow.configs["pipeline"]["population"]
    if bad == "pool":
        population["sampling"]["pools"]["name"] = ["Only one"]
    elif bad == "seed":
        population["sampling"]["seed"] = True
    elif bad == "missing_pool":
        del population["sampling"]["pools"]["name"]
    elif bad == "overwrite_source":
        population["replacements_path"] = "jobs.csv"
    elif bad == "overwrite_stage":
        population["replacements_path"] = "templates.csv"
    else:
        population["sampling"]["typo"] = True
    write_yaml(workflow.path, workflow.configs["pipeline"])
    assert runner.main(["--config", str(workflow.path), "--check"]) == 1
    assert not workflow.adapter.calls and not workflow.r_calls


@pytest.mark.parametrize("change", ["seed", "payload", "order"])
def test_changed_sampled_assignments_are_not_silently_overwritten(runner, workflow, change):
    enable_sampling(workflow)
    command = ["--config", str(workflow.path), "--run"]
    assert runner.main(command) == 0
    assignments = workflow.directory / "sampled.csv"
    if change == "seed":
        workflow.configs["pipeline"]["population"]["sampling"]["seed"] = 17
        write_yaml(workflow.path, workflow.configs["pipeline"])
    else:
        values = pd.read_csv(assignments, dtype=str)
        if change == "payload":
            values.loc[0, "name"] = "Intentionally changed"
        else:
            values.loc[0, "candidate_order"] = "9"
        values.to_csv(assignments, index=False)
    before = assignments.read_bytes()
    populated = (workflow.directory / "populated.csv").read_bytes()
    assert runner.main(command) == 1
    assert assignments.read_bytes() == before
    assert (workflow.directory / "populated.csv").read_bytes() == populated
    assert len(workflow.adapter.calls) == 32 and len(workflow.r_calls) == 1


@pytest.mark.parametrize("stage", ["ocr", "templates", "population", "experiments", "preparation"])
def test_continuous_failure_never_runs_a_later_stage(runner, workflow, monkeypatch, stage):
    config = runner.load_config(workflow.path)
    config.ocr_path = workflow.directory / "ocr.yaml"
    calls = []

    def step(name, result):
        def execute(*args, **kwargs):
            calls.append(name)
            if name == stage:
                raise RuntimeError("private input and secret token")
            return result
        return execute

    monkeypatch.setattr(runner, "ocr_main", step("ocr", 0))
    monkeypatch.setattr(runner, "_templates", step("templates", pd.DataFrame()))
    monkeypatch.setattr(runner, "_populate", step("population", pd.DataFrame()))
    async def experiment(*args):
        return step("experiments", pd.DataFrame({"error_type": [None], "error_message": [None]}))()

    monkeypatch.setattr(runner, "ExperimentRunner", lambda *args: SimpleNamespace(run_async=experiment))
    monkeypatch.setattr(runner, "_r_command", step("preparation", None))
    with pytest.raises(RuntimeError):
        runner.run_continuous(config)
    order = ["ocr", "templates", "population", "experiments", "preparation"]
    assert calls == order[:order.index(stage) + 1]


def test_continuous_failed_job_does_not_start_r_preparation(runner, workflow, monkeypatch):
    original = workflow.adapter.results

    def fail_one(requests, mode):
        results = original(requests, mode)
        if requests[0].model_config_id == "review":
            # Structurally valid inference, but a domain-invalid decision.
            results[0].structured_content["Applicant 1"] = "Maybe"
            results[0].content = json.dumps(results[0].structured_content)
        return results

    monkeypatch.setattr(workflow.adapter, "results", fail_one)
    assert runner.main(["--config", str(workflow.path), "--run"]) == 1
    assert not workflow.r_calls
    assert pd.read_csv(workflow.directory / "experiments.csv").error_type.notna().any()


def test_continuous_failed_template_does_not_start_population(runner, workflow, monkeypatch):
    enable_sampling(workflow)
    original = workflow.adapter.results

    def invalid_template(requests, mode):
        results = original(requests, mode)
        results[0].structured_content = {"template_1": "Missing placeholders", "template_2": "Also missing"}
        results[0].content = json.dumps(results[0].structured_content)
        return results

    monkeypatch.setattr(workflow.adapter, "results", invalid_template)
    assert runner.main(["--config", str(workflow.path), "--run"]) == 1
    assert not (workflow.directory / "sampled.csv").exists()
    assert not (workflow.directory / "populated.csv").exists()
    assert not workflow.r_calls
    assert {call[1] for call in workflow.adapter.calls} == {"templates"}


def test_reordered_sampled_assignment_csv_is_reused(runner, workflow):
    enable_sampling(workflow)
    command = ["--config", str(workflow.path), "--run"]
    assert runner.main(command) == 0
    path = workflow.directory / "sampled.csv"
    saved = pd.read_csv(path, dtype=str)
    saved.iloc[::-1, ::-1].to_csv(path, index=False)
    before = path.read_bytes()
    assert runner.main(command) == 0
    assert path.read_bytes() == before
    assert len(workflow.adapter.calls) == 32


def test_population_resumes_after_assignment_save_but_population_write_failure(runner, workflow, monkeypatch):
    enable_sampling(workflow)
    config = runner.load_config(workflow.path)
    templates = runner._templates(config)
    original_write = runner._atomic_csv

    def fail_population(table, path):
        if path == config.population_path:
            raise OSError("Synthetic interruption after assignment save")
        original_write(table, path)

    monkeypatch.setattr(runner, "_atomic_csv", fail_population)
    with pytest.raises(OSError):
        runner._populate(config, templates)
    saved = config.replacements_path.read_bytes()
    assert not config.population_path.exists()
    monkeypatch.setattr(runner, "_atomic_csv", original_write)
    populated = runner._populate(config, templates)
    assert len(populated) == 16
    assert config.replacements_path.read_bytes() == saved
    assert len(workflow.adapter.calls) == 16 and not workflow.r_calls


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


@pytest.mark.skipif(os.environ.get("LLM_AUDITKIT_RUN_R_INTEGRATION") != "1", reason="opt in to restored R environment")
def test_continuous_sampled_workflow_through_real_r_preparation(runner, workflow, monkeypatch):
    if not workflow.real_which("Rscript"):
        pytest.skip("Rscript is not installed")
    enable_sampling(workflow)
    monkeypatch.setattr(runner, "_r_command", workflow.real_r)
    monkeypatch.setattr(runner.shutil, "which", workflow.real_which)
    assert runner.main(["--config", str(workflow.path), "--run"]) == 0
    prepared = pd.read_csv(workflow.directory / "ready.csv", dtype={"scenario_id": str})
    assignments = pd.read_csv(workflow.directory / "sampled.csv", dtype={"scenario_id": str})
    assert len(prepared) == 32
    assert set(prepared.candidate_id) == set(assignments.candidate_id)
    assert set(prepared.audit_id) == {"researcher-assigned-runner-fixture"}
    assert not (workflow.directory / "regression").exists()
