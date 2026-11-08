import subprocess
import sys

import pandas as pd
import pytest
import yaml

from llm_auditkit.ocr import OCRException, OCRStore
from llm_auditkit.ocr.cli import main

from .helpers import page
from .test_configuration import values


def test_atomic_replacement_failure_keeps_existing_export(tmp_path, monkeypatch):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    store.export([])
    original = store.output_path.read_bytes()
    def fail(*args):
        raise OSError("synthetic replace failure")
    monkeypatch.setattr("llm_auditkit.ocr.store.os.replace", fail)
    with pytest.raises(OSError):
        store.export([])
    assert store.output_path.read_bytes() == original
    assert not list(tmp_path.glob(".ads.csv.*"))


@pytest.mark.parametrize("shared", ["directory", "output"])
def test_concurrent_store_or_output_writers_are_rejected(tmp_path, shared):
    first = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    second = OCRStore(tmp_path / ("cache" if shared == "directory" else "other"),
                      tmp_path / ("other.csv" if shared == "directory" else "ads.csv"))
    with first.locked():
        with pytest.raises(OCRException, match="locked"):
            with second.locked():
                pytest.fail("second writer was allowed")
    with second.locked():
        pass


def test_checkpoint_roundtrip_and_reject_bad_schema(tmp_path):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    source = page()
    record = {"version": 1, "page": source, "outcome": None}
    store.save(record)
    assert store.load(source.page_id) == record
    checkpoint = next(store.directory.glob("*.json"))
    checkpoint.write_text('{"version": 99}')
    with pytest.raises(OCRException):
        store.load(source.page_id)


def test_no_checkpoint_path_traversal(tmp_path):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    with pytest.raises(OCRException):
        store.load("../../outside")


def test_existing_unowned_output_not_overwritten(tmp_path):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    store.output_path.write_text("existing research output")
    with store.locked(), pytest.raises(OCRException, match="refusing to overwrite"):
        store.initialize("fingerprint", [], True)
    assert store.output_path.read_text() == "existing research output"


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_cli_dispatch_and_resource_cleanup(tmp_path, monkeypatch, mode, capsys):
    value = values()
    value["execution"]["mode"] = mode
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(value))
    calls = []
    class Backend:
        def close(self):
            calls.append("close")
        async def close_async(self):
            calls.append("close_async")
    class Pipeline:
        def __init__(self, *args):
            pass
        def run(self, *args):
            calls.append("sync")
            return pd.DataFrame([{"Text": "ad"}])
        async def run_async(self, *args):
            calls.append("async")
            return pd.DataFrame([{"Text": "ad"}])
    monkeypatch.setattr("llm_auditkit.ocr.cli.GoogleVisionOCRBackend", Backend)
    monkeypatch.setattr("llm_auditkit.ocr.cli.NewspaperOCRPipeline", Pipeline)
    assert main(["--config", str(path)]) == 0
    assert calls[0] == mode
    assert calls[-1] == "close"
    assert ("close_async" in calls) == (mode == "async")
    assert "Extracted 1 ads" in capsys.readouterr().out


def test_cli_failure_does_not_leak_provider_data(tmp_path, monkeypatch, capsys):
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(values()))
    class Pipeline:
        def __init__(self, *args):
            raise RuntimeError("private text / secret token")
    monkeypatch.setattr("llm_auditkit.ocr.cli.NewspaperOCRPipeline", Pipeline)
    assert main(["--config", str(path)]) == 1
    captured = capsys.readouterr()
    assert "private text" not in captured.err and "secret token" not in captured.err
    assert "partial" in captured.err


def test_import_needs_no_optional_sdks_or_credentials():
    code = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(("google.cloud", "PIL", "pdf2image")):
        raise AssertionError("optional dependency imported eagerly: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import llm_auditkit.ocr
'''
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
