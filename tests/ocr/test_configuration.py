from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from llm_auditkit.ocr import OCRException, load_ocr_run_config
from llm_auditkit.ocr.configuration import validate_config, validate_metadata, validate_paths

from .helpers import config


def values():
    return {
        "documents": [{"path": "scan.pdf", "metadata": {"publication_date": "1950-06-15", "city": "Example"}}],
        "output": {"path": "ads.csv", "checkpoint_directory": "checkpoints"},
        "execution": {"mode": "async", "batch_size": 5, "save_after_each_batch": True},
        "inference": {"model": {"config_id": "extract", "provider": "test", "model": "fake"}},
    }


def test_yaml_paths_and_explicit_metadata(tmp_path):
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(values()))
    run = load_ocr_run_config(path)
    assert run.documents[0].path == tmp_path / "scan.pdf"
    assert run.output_path == tmp_path / "ads.csv"
    assert run.mode == "async" and run.config.inference.batch_size == 5
    assert run.documents[0].metadata["publication_date"] == "1950-06-15"


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(unknown=True),
    lambda value: value["documents"][0].update(typo=True),
    lambda value: value.update(documents=[]),
    lambda value: value["output"].update(path="ads.json"),
    lambda value: value["output"].update(path="run.yaml"),
    lambda value: value["output"].update(path="checkpoints/ads.csv"),
    lambda value: value["output"].update(checkpoint_directory="."),
    lambda value: value["execution"].update(mode="background"),
    lambda value: value["execution"].update(batch_size=True),
    lambda value: value["execution"].update(save_after_each_batch="false"),
    lambda value: value.update(ocr={"dpi": False}),
    lambda value: value.update(ocr={"language_hints": "en"}),
    lambda value: value.update(ocr={"timeout": float("inf")}),
    lambda value: value["inference"]["model"].update(typo=True),
    lambda value: value["inference"]["model"].update(parameters={"temperature": float("nan")}),
])
def test_invalid_yaml_fails_before_calls(tmp_path, mutation):
    value = values()
    mutation(value)
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(ValueError):
        load_ocr_run_config(path)


@pytest.mark.parametrize("text", ["documents: []\ndocuments: []", "[]", "a: [", "? [a, b]\n: value"])
def test_duplicate_or_malformed_yaml(tmp_path, text):
    path = tmp_path / "run.yaml"
    path.write_text(text)
    with pytest.raises(OCRException):
        load_ocr_run_config(path)


@pytest.mark.parametrize("metadata", [{"date": [1950]}, {"city": {}}, {"": "x"}, {1: "x"}, {"value": float("nan")}])
def test_metadata_scalar_contract(metadata):
    with pytest.raises(OCRException):
        validate_metadata(metadata)


def test_unquoted_yaml_date_is_not_silently_serialized(tmp_path):
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(values()).replace("'1950-06-15'", "1950-06-15"))
    with pytest.raises(OCRException, match="quote dates"):
        load_ocr_run_config(path)


def test_refuses_multiple_model_configs():
    cfg = config()
    model = deepcopy(cfg.inference.models[0])
    model.config_id = "other"
    cfg.inference.models.append(model)
    with pytest.raises(OCRException, match="exactly one"):
        validate_config(cfg)


def test_output_cannot_overwrite_input_via_hardlink(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source bytes")
    output = tmp_path / "ads.csv"
    output.hardlink_to(source)
    with pytest.raises(OCRException, match="overwrite"):
        validate_paths(output, tmp_path / "checkpoints", [source])


def test_shipped_yaml_example_loads_without_reading_scans():
    root = Path(__file__).resolve().parents[2]
    run = load_ocr_run_config(root / "configs/ocr/newspaper.yaml")
    assert run.config.inference.models[0].model == "gpt-4o-2024-08-06"
