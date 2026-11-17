"""Real interfaces and cross-invocation failure boundaries; no live providers."""

import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource
from llm_auditkit.inference import InferenceOrchestrator
from llm_auditkit.ocr import NewspaperOCRPipeline, OCRException, OCRStore, SourceDocument
from llm_auditkit.ocr.reconstruction import parse_response

from .helpers import Adapter, Backend, config, page, response_for


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_mutated_pdf_cannot_poison_original_source_cache(tmp_path, monkeypatch, mode, interrupted):
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("pdf2image")
    if not shutil.which("pdftoppm") or not shutil.which("pdfinfo"):
        pytest.skip("optional system Poppler is not installed")
    source = tmp_path / "source.pdf"

    def make_pdf(colors):
        images = [Image.new("RGB", (30, 30), color) for color in colors]
        try:
            images[0].save(source, format="PDF", save_all=True, append_images=images[1:], resolution=72)
        finally:
            for image in images:
                image.close()

    make_pdf(["red", "blue"])
    original = source.read_bytes()
    from llm_auditkit.ocr import pipeline as module
    render = module.render_page
    snapshots = []
    def track_snapshot(plan, number, cfg):
        assert plan.snapshot_path is not None
        snapshots.append(plan.snapshot_path)
        return render(plan, number, cfg)
    monkeypatch.setattr(module, "render_page", track_snapshot)

    class MutatingBackend:
        calls = 0
        mutate = True

        def recognize(self, image, page_id, cfg):
            self.calls += 1
            with Image.open(io.BytesIO(image)) as raster:
                rgb = raster.convert("RGB").getpixel((10, 10))
            color = ["red", "green", "blue"][max(range(3), key=lambda index: rgb[index])]
            if self.mutate and self.calls == 1:
                make_pdf(["yellow", "green"])
            if self.mutate and interrupted and self.calls == 2:
                raise OSError("synthetic interruption before source recheck")
            return page(page_id, texts=(color,))

        async def recognize_async(self, *args):
            return self.recognize(*args)

    backend = MutatingBackend()
    pipeline = NewspaperOCRPipeline(backend, InferenceOrchestrator(Adapter()),
                                    OCRStore(tmp_path / "cache", tmp_path / "ads.csv"))
    execute = lambda: (pipeline.run([SourceDocument(source)], config(dpi=72)) if mode == "sync"
                       else asyncio.run(pipeline.run_async([SourceDocument(source)], config(dpi=72))))
    with pytest.raises(OSError if interrupted else OCRException):
        execute()
    assert snapshots and all(not snapshot.exists() for snapshot in snapshots)
    source.write_bytes(original)
    backend.calls, backend.mutate = 0, False
    result = execute()
    assert result.Text.tolist() == ["red", "blue"]
    assert backend.calls == (1 if interrupted else 0)


def test_output_reservation_survives_nonoverlapping_runs(tmp_path):
    output = tmp_path / "ads.csv"
    first = OCRStore(tmp_path / "a", output)
    second = OCRStore(tmp_path / "b", output)
    with first.locked():
        first.initialize("run-a", [], True)
    # A failed before its first CSV, but its destination is still reserved.
    with second.locked(), pytest.raises(OCRException, match="owned"):
        second.initialize("run-b", [], True)
    with first.locked():
        first.initialize("run-a", [], True)
        first.export([{"Text": "A"}])
    assert "A" in output.read_text()


def test_missing_ownership_does_not_let_old_manifest_overwrite_new_run(tmp_path):
    output = tmp_path / "ads.csv"
    first = OCRStore(tmp_path / "a", output)
    second = OCRStore(tmp_path / "b", output)
    with first.locked():
        first.initialize("run-a", [], True)
    first.owner_path.unlink()  # damaged/absent destination claim, manifest remains
    with second.locked():
        second.initialize("run-b", [], True)
        second.export([{"Text": "Dataset B"}])
    saved = output.read_bytes()
    with first.locked(), pytest.raises(OCRException, match="owned"):
        first.initialize("run-a", [], True)
    assert output.read_bytes() == saved


def test_own_interrupted_csv_export_can_be_recovered(tmp_path, monkeypatch):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    store.initialize("run", [], True)
    original_replace = os.replace
    def fail_csv(source, destination):
        if Path(destination) == store.output_path:
            raise OSError("synthetic CSV interruption")
        return original_replace(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr("llm_auditkit.ocr.store.os.replace", fail_csv)
        with pytest.raises(OSError):
            store.export([{"Text": "A"}])
    store.initialize("run", [], True)
    store.export([{"Text": "Recovered A"}])
    assert "Recovered A" in store.output_path.read_text()


@pytest.mark.parametrize("invalid,reason", [("\x00", "NUL"), ("\ud800", "UTF-8")])
def test_invalid_raw_ocr_stops_before_inference_and_corrected_source_can_resume(tmp_path, invalid, reason):
    Image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    with Image.new("RGB", (20, 20)) as image:
        image.save(source)
    class InvalidBackend(Backend):
        corrupt = True
        def recognize(self, *args):
            result = super().recognize(*args)
            if self.corrupt:
                bad_block = replace(result.blocks[0], text=result.blocks[0].text + invalid)
                return replace(result, blocks=(bad_block, *result.blocks[1:]))
            return result
    backend, adapter = InvalidBackend(), Adapter()
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    pipeline = NewspaperOCRPipeline(backend, InferenceOrchestrator(adapter), store)
    with pytest.raises(OCRException, match=reason):
        pipeline.run([SourceDocument(source)], config())
    assert not adapter.sync_calls
    backend.corrupt = False
    pipeline.run([SourceDocument(source)], config())
    loaded = DatasetLoader(DatasetSchema(["Text"], ["Text"])).load(LocalDatasetSource(store.output_path))
    assert len(loaded) == 1


def test_v1_checkpoint_cannot_reuse_unverified_source_records(tmp_path):
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    store.initialize("run", [], True)
    manifest = store.directory / "manifest.json"
    old = json.loads(manifest.read_text())
    old["version"] = 1
    manifest.write_text(json.dumps(old))
    with pytest.raises(OCRException, match="differ"):
        store.initialize("run", [], True)


def test_output_claim_does_not_break_dataset_directory_loading(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    with Image.new("RGB", (20, 20)) as image:
        image.save(source)
    pipeline = NewspaperOCRPipeline(Backend(), InferenceOrchestrator(Adapter()),
                                    OCRStore(tmp_path / "cache", tmp_path / "ads.csv"))
    pipeline.run([SourceDocument(source)], config())
    result = DatasetLoader(DatasetSchema(["Text"], ["Text"])).load(LocalDatasetSource(tmp_path))
    assert len(result) == 1


@pytest.mark.parametrize("original,cleaned", [
    ("Wages $1.75 per hour.", "Wages $175 per hour."),
    ("Wages $100 per week.", "Wages £100 per week."),
    ("Wages $1,000 per week.", "Wages $1.000 per week."),
    ("Age 18–25.", "Age 1825."),
    ("Bonus 10%.", "Bonus 10."),
])
def test_numeric_and_currency_changes_require_review_but_do_not_block_output(original, cleaned):
    source = page(texts=(original,))
    response = response_for([asdict(block) for block in source.blocks])
    response["ads"][0]["text"] = cleaned
    result = parse_response(json.dumps(response), source)
    assert result[0]["raw_text"] == original
    assert result[0]["Text"] == cleaned


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("invalid", ["\x00", "\ud800"])
def test_invalid_csv_text_fails_before_success_and_corrected_retry_loads(tmp_path, mode, invalid):
    Image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    with Image.new("RGB", (20, 20)) as image:
        image.save(source)
    def corrupt(request, result):
        value = json.loads(result.content)
        value["ads"][0]["text"] += invalid
        result.content = json.dumps(value)
        return result
    adapter = Adapter(corrupt)
    store = OCRStore(tmp_path / "cache", tmp_path / "ads.csv")
    pipeline = NewspaperOCRPipeline(Backend(), InferenceOrchestrator(adapter), store)
    execute = lambda: (pipeline.run([SourceDocument(source)], config()) if mode == "sync"
                       else asyncio.run(pipeline.run_async([SourceDocument(source)], config())))
    with pytest.raises(OCRException, match="batch failed"):
        execute()
    checkpoint = next(path for path in store.directory.glob("*.json") if path.name != "manifest.json")
    assert json.loads(checkpoint.read_text())["outcome"]["status"] == "failed"
    adapter.callback = None
    result = execute()
    loaded = DatasetLoader(DatasetSchema(["Text"], ["Text"])).load(LocalDatasetSource(store.output_path))
    assert len(result) == len(loaded) == 1
    assert (adapter.sync_calls or adapter.async_calls)[-1][0].use_cache is False


def test_cli_import_and_main_keep_shell_credentials(tmp_path):
    # Fresh process: importing the CLI must not let EDSL's import-time dotenv
    # override the environment before our own load_dotenv(override=False).
    (tmp_path / ".env").write_text(
        "GOOGLE_APPLICATION_CREDENTIALS=/synthetic/dotenv.json\n"
        "GOOGLE_VISION_API_KEY=dotenv-vision-sentinel\n"
        "OPENAI_API_KEY=dotenv-sentinel\nOCR_DOTENV_ONLY=loaded\n"
    )
    environment = os.environ.copy()
    environment.update({"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
                        "GOOGLE_APPLICATION_CREDENTIALS": "/synthetic/shell.json",
                        "GOOGLE_VISION_API_KEY": "shell-vision-sentinel",
                        "OPENAI_API_KEY": "shell-sentinel"})
    environment.pop("PYTHON_DOTENV_DISABLED", None)
    environment.pop("OCR_DOTENV_ONLY", None)
    code = '''
import os
from llm_auditkit.ocr.cli import main
assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/synthetic/shell.json"
assert os.environ["GOOGLE_VISION_API_KEY"] == "shell-vision-sentinel"
assert os.environ["OPENAI_API_KEY"] == "shell-sentinel"
assert os.environ["OCR_DOTENV_ONLY"] == "loaded"
assert main(["--config", "missing.yaml"]) == 1
assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/synthetic/shell.json"
assert os.environ["GOOGLE_VISION_API_KEY"] == "shell-vision-sentinel"
'''
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=environment,
                   check=True, capture_output=True, text=True, timeout=30)
