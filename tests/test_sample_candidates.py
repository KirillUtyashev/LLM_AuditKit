"""Offline regression coverage for the editable candidate-sampling example."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
import yaml

from llm_auditkit.templates.population import (
    TemplatePopulationConfig, TemplatePopulationPlaceholderError, TemplatePopulator,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "candidate_sampling_example", ROOT / "examples/template_population/sample_candidates.py",
)
example = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example)


@pytest.fixture
def population():
    return TemplatePopulationConfig(
        template_columns={"layout-a": "template_1", "layout-b": "template_2"},
        placeholder_columns={"name": "full_name", "qualification": "qualification"},
    )


@pytest.fixture
def templates():
    return pd.DataFrame({
        "scenario_id": ["job-b", "job-a"], "Text": ["Clerk.", "Assistant."],
        "template_1": ["{{name}}: {{qualification}}"] * 2,
        "template_2": ["{{name}} — {{qualification}}"] * 2,
        "city": ["Synthetic City"] * 2,
    })


@pytest.fixture
def sampling():
    return {
        "pools": {"full_name": ["Alex Rowan", "Casey Brook", "Jamie Vale"],
                  "qualification": ["Exact text including {{literal}} and 003."]},
        "unique_columns": ["full_name"], "seed": 42,
        "assignment_namespace": "synthetic-test-v1",
    }


def test_assignments_populate_without_changing_templates(templates, population, sampling):
    original = templates.copy(deep=True)
    assignments = example.sample_candidates(templates, population, **sampling)
    populated = TemplatePopulator().populate(templates, assignments, population)
    pd.testing.assert_frame_equal(templates, original)
    assert len(assignments) == 4 and assignments.candidate_id.nunique() == 4
    assert populated.scenario_id.tolist() == templates.scenario_id.tolist()
    assert populated.city.tolist() == templates.city.tolist()
    for scenario_id, rows in assignments.groupby("scenario_id"):
        assert rows.full_name.nunique() == 2
        assert set(rows.candidate_order) == {1, 2}
        assert set(rows.template_id) == set(population.template_columns)
        result = populated.set_index("scenario_id").loc[scenario_id]
        for row in rows.itertuples():
            slot = row.candidate_order
            assert result[f"candidate_{slot}_id"] == row.candidate_id
            assert row.full_name in result[f"resume_{slot}"]
            assert row.qualification in result[f"resume_{slot}"]
            assert result[f"candidate_{slot}_template_id"] == row.template_id


def test_reproducible_across_reordering_and_adding_scenarios(templates, population, sampling):
    expected = example.sample_candidates(templates, population, **sampling)
    reordered = templates.iloc[::-1]
    pd.testing.assert_frame_equal(expected, example.sample_candidates(reordered, population, **sampling))
    extra = templates.iloc[:1].assign(scenario_id="job-new")
    expanded = example.sample_candidates(pd.concat([extra, reordered]), population, **sampling)
    pd.testing.assert_frame_equal(expected, expanded[expanded.scenario_id != "job-new"].reset_index(drop=True))


@pytest.mark.parametrize("change", [{"seed": 7}, {"assignment_namespace": "other-study"}])
def test_changed_design_has_new_candidate_ids(templates, population, sampling, change):
    before = example.sample_candidates(templates, population, **sampling)
    after = example.sample_candidates(templates, population, **(sampling | change))
    assert set(before.candidate_id).isdisjoint(after.candidate_id)


def test_arbitrary_template_count(templates, sampling):
    templates = templates.assign(template_3="Third: {{name}}")
    population = TemplatePopulationConfig(
        template_columns={f"label-{i}": f"template_{i}" for i in (1, 2, 3)},
        placeholder_columns={"name": "full_name", "qualification": "qualification"},
    )
    assignments = example.sample_candidates(templates, population, **sampling)
    populated = TemplatePopulator().populate(templates, assignments, population)
    assert len(assignments) == 6 and populated.candidate_count.eq(3).all()


@pytest.mark.parametrize("change", [
    {"seed": True}, {"assignment_namespace": " "},
    {"pools": {"full_name": ["Only one"], "qualification": ["Experience"]}},
    {"pools": {"full_name": ["Alex", "Alex"], "qualification": ["Experience"]}},
    {"pools": {"full_name": ["Alex", "Casey"], "qualification": [3]}},
    {"pools": {"full_name": ["Alex", "Casey"]}},
    {"unique_columns": ["unknown"]},
    {"pools": {"candidate_id": ["Do not replace identity"]}},
])
def test_invalid_sampling_is_rejected(templates, population, sampling, change):
    with pytest.raises(ValueError):
        example.sample_candidates(templates, population, **(sampling | change))


@pytest.mark.parametrize("identities", [["duplicate", "duplicate"], ["", "valid"], [1, "valid"]])
def test_invalid_scenario_identity_is_rejected(templates, population, sampling, identities):
    with pytest.raises(ValueError, match="scenario_id"):
        example.sample_candidates(templates.assign(scenario_id=identities), population, **sampling)


def make_config(tmp_path):
    config = yaml.safe_load((ROOT / "configs/template_population/sample_candidates.yaml").read_text())
    config["dataset_path"] = str(ROOT / "examples/template_population/sampling_templates.csv")
    config["output"] = {"candidates_path": "saved/candidates.csv", "populated_path": "saved/populated.csv"}
    path = tmp_path / "sampling.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path, config


def test_cli_loads_templates_once_and_saves_both_tables(tmp_path, monkeypatch, capsys):
    path, config = make_config(tmp_path)
    loads = []
    original = example.LocalDatasetSource.load

    def record_load(source):
        loads.append(source)
        return original(source)

    monkeypatch.setattr(example.LocalDatasetSource, "load", record_load)
    monkeypatch.chdir(tmp_path)  # Paths resolve from YAML, not working directory.
    monkeypatch.setattr("sys.argv", ["sample_candidates.py", "--config", str(path)])
    example.main()
    assert len(loads) == 1
    assert "4 candidate assignments and 2 populated scenarios" in capsys.readouterr().out
    candidates_path = tmp_path / config["output"]["candidates_path"]
    populated_path = tmp_path / config["output"]["populated_path"]
    before = (candidates_path.read_bytes(), populated_path.read_bytes())
    replacements, populated = example.run(path)
    pd.testing.assert_frame_equal(replacements, pd.read_csv(candidates_path))
    # CSV records values, not pandas extension-dtype metadata.
    pd.testing.assert_frame_equal(populated, pd.read_csv(populated_path), check_dtype=False)
    assert before == (candidates_path.read_bytes(), populated_path.read_bytes())


@pytest.mark.parametrize("target", ["dataset_path", "config", "same_output"])
def test_outputs_cannot_clobber_input_config_or_each_other(tmp_path, target):
    path, config = make_config(tmp_path)
    config["output"]["candidates_path"] = (
        config["dataset_path"] if target == "dataset_path" else str(path) if target == "config"
        else config["output"]["populated_path"]
    )
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Outputs must be distinct"):
        example.run(path)
    assert not (tmp_path / "saved").exists()


def test_population_error_does_not_write_either_file(tmp_path):
    path, config = make_config(tmp_path)
    del config["population"]["placeholder_columns"]["qualification"]
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(TemplatePopulationPlaceholderError):
        example.run(path)
    assert not (tmp_path / "saved").exists()


def test_atomic_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "existing.csv"
    target.write_text("old content", encoding="utf-8")

    def fail_replace(*args):
        raise OSError("Simulated replacement failure")

    monkeypatch.setattr(example.os, "replace", fail_replace)
    with pytest.raises(OSError):
        example._write_csv(pd.DataFrame({"value": ["new content"]}), target)
    assert target.read_text() == "old content"
    assert list(tmp_path.iterdir()) == [target]
