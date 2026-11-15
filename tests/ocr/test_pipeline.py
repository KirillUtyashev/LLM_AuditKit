import asyncio
import json
from dataclasses import replace

import pandas as pd
import pytest

from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource
from llm_auditkit.inference import InferenceError, InferenceOrchestrator
from llm_auditkit.ocr import NewspaperOCRPipeline, OCRException, OCRStore, SourceDocument
from llm_auditkit.ocr.models import identity
from llm_auditkit.ocr.sources import DocumentPlan, file_hash

from .helpers import Adapter, Backend, config


@pytest.fixture
def documents(tmp_path, monkeypatch):
    result = []
    for index in range(3):
        path = tmp_path / f"source-{index}.png"
        path.write_bytes(f"synthetic image {index}".encode())
        result.append(SourceDocument(path, {"city": "Example", "date": "1950-06-15"}))

    def inspect(document, config):
        digest = file_hash(document.path)
        return DocumentPlan(document.path, identity("source", [digest, document.metadata]), digest, document.metadata, 1)
    monkeypatch.setattr("llm_auditkit.ocr.pipeline.inspect_document", inspect)
    monkeypatch.setattr("llm_auditkit.ocr.pipeline.render_page", lambda plan, number, config: plan.path.read_bytes())
    return result


def make_pipeline(tmp_path, backend=None, adapter=None, directory="checkpoints", output="ads.csv"):
    return NewspaperOCRPipeline(backend or Backend(), InferenceOrchestrator(adapter or Adapter()),
                                OCRStore(tmp_path / directory, tmp_path / output))


def test_sync_async_equivalent_and_native(documents, tmp_path):
    sync_backend, sync_adapter = Backend(), Adapter()
    sync = make_pipeline(tmp_path, sync_backend, sync_adapter)
    first = sync.run(documents, config())
    async_backend, async_adapter = Backend(), Adapter()
    asynchronous = make_pipeline(tmp_path, async_backend, async_adapter, "async-cache", "async.csv")
    second = asyncio.run(asynchronous.run_async(documents, config()))
    pd.testing.assert_frame_equal(first, second)
    assert sync_backend.sync_calls == 3 and sync_backend.async_calls == 0
    assert async_backend.async_calls == 3 and async_backend.sync_calls == 0
    assert len(sync_adapter.sync_calls) == len(async_adapter.async_calls) == 3
    assert not sync_adapter.async_calls and not async_adapter.sync_calls
    loaded = DatasetLoader(DatasetSchema(["Text"], ["Text"])).load(LocalDatasetSource(tmp_path / "ads.csv"))
    assert len(loaded) == 3
    assert loaded.scenario_id.is_unique
    assert all(first.review_required)


def test_resume_skips_ocr_and_inference_and_preserves_ids(documents, tmp_path):
    backend, adapter = Backend(), Adapter()
    pipeline = make_pipeline(tmp_path, backend, adapter)
    first = pipeline.run(documents, config())
    second = asyncio.run(pipeline.run_async(documents, config()))
    pd.testing.assert_frame_equal(first, second)
    assert backend.sync_calls == 3 and backend.async_calls == 0
    assert len(adapter.sync_calls) == 3 and not adapter.async_calls


def test_page_batch_size_not_ad_count(documents, tmp_path):
    adapter = Adapter()
    cfg = config()
    cfg.inference.batch_size = 2
    result = make_pipeline(tmp_path, adapter=adapter).run(documents, cfg)
    assert [len(batch) for batch in adapter.sync_calls] == [2, 1]
    assert len(result) == 3


def test_source_hashing_does_not_scale_with_llm_batch_count(documents, tmp_path, monkeypatch):
    checks = []
    monkeypatch.setattr("llm_auditkit.ocr.pipeline.check_source", lambda plan: checks.append(plan.source_id))
    make_pipeline(tmp_path).run(documents, config())
    # Before/after each document's acquisition, then once at final completion;
    # not every time the full CSV snapshot is exported.
    assert len(checks) == len(documents) * 3


@pytest.mark.parametrize("bad", ["parse", "provider"])
def test_fail_fast_retains_raw_and_failed_output_then_resume(documents, tmp_path, bad):
    seen = []
    def callback(request, result):
        seen.append(request.request_id)
        if len(seen) == 2:
            if bad == "parse":
                result.content = '{"ads":[],"blocks":[]}'
            else:
                result.content = None
                result.error = InferenceError("provider", "synthetic failure")
        return result
    adapter, backend = Adapter(callback), Backend()
    pipeline = make_pipeline(tmp_path, backend, adapter)
    with pytest.raises(OCRException, match="batch failed"):
        pipeline.run(documents, config())
    assert len(adapter.sync_calls) == 2  # third page never submitted
    assert backend.sync_calls == 3
    assert len(pd.read_csv(tmp_path / "ads.csv")) == 1
    checkpoints = [json.loads(path.read_text()) for path in (tmp_path / "checkpoints").glob("*.json") if path.name != "manifest.json"]
    assert all("raw_response" in record["page"] for record in checkpoints)
    assert any(record["outcome"] and record["outcome"]["status"] == "failed" for record in checkpoints)
    adapter.callback = None
    result = pipeline.run(documents, config())
    assert len(result) == 3
    assert backend.sync_calls == 3
    assert len(adapter.sync_calls) == 4  # retry failed page, then remaining page


def test_blank_pages_checkpoint_without_llm_calls(documents, tmp_path):
    backend, adapter = Backend(texts=()), Adapter()
    pipeline = make_pipeline(tmp_path, backend, adapter)
    first = pipeline.run(documents, config())
    assert first.empty and "Text" in first.columns
    assert pd.read_csv(tmp_path / "ads.csv").empty
    pipeline.run(documents, config())
    assert backend.sync_calls == 3 and not adapter.sync_calls


def test_rejected_non_job_pages_not_repeated(documents, tmp_path):
    def callback(request, result):
        response = json.loads(result.content)
        response["ads"] = []
        for block in response["blocks"]:
            block["segments"][0].update(ad_key=None, reason="non-ad material")
        result.content = json.dumps(response)
        return result
    adapter = Adapter(callback)
    pipeline = make_pipeline(tmp_path, adapter=adapter)
    assert pipeline.run(documents, config()).empty
    assert pipeline.run(documents, config()).empty
    assert len(adapter.sync_calls) == 3


@pytest.mark.parametrize("change", ["model", "metadata", "source", "dpi", "limit"])
def test_resume_refuses_incompatible_run(documents, tmp_path, change):
    backend, adapter = Backend(), Adapter()
    pipeline = make_pipeline(tmp_path, backend, adapter)
    cfg = config()
    pipeline.run(documents, cfg)
    if change == "model":
        cfg.inference.models[0].parameters["temperature"] = 1
    elif change == "metadata":
        documents[0].metadata["city"] = "Other"
    elif change == "source":
        documents[0].path.write_bytes(b"changed")
    elif change == "dpi":
        cfg = replace(cfg, dpi=150)
    else:
        cfg = replace(cfg, max_page_characters=50000)
    with pytest.raises(OCRException, match="differ"):
        pipeline.run(documents, cfg)
    assert backend.sync_calls == 3 and len(adapter.sync_calls) == 3


def test_incremental_disabled_writes_only_on_complete_success(documents, tmp_path):
    def callback(request, result):
        assert not (tmp_path / "ads.csv").exists()
        assert not list((tmp_path / "checkpoints").glob("*.json"))
        return result
    pipeline = make_pipeline(tmp_path, adapter=Adapter(callback))
    assert len(pipeline.run(documents, config(save_after_each_batch=False))) == 3
    assert len(pd.read_csv(tmp_path / "ads.csv")) == 3


def test_incremental_disabled_failure_does_not_write(documents, tmp_path):
    def callback(request, result):
        result.content = "not JSON"
        return result
    with pytest.raises(OCRException):
        make_pipeline(tmp_path, adapter=Adapter(callback)).run(documents, config(save_after_each_batch=False))
    assert not (tmp_path / "ads.csv").exists()
    assert not list((tmp_path / "checkpoints").glob("*.json"))


def test_corrupt_success_checkpoint_cannot_skip_validation(documents, tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.run(documents, config())
    checkpoint = next(path for path in pipeline.store.directory.glob("*.json") if path.name != "manifest.json")
    record = json.loads(checkpoint.read_text())
    record["outcome"]["response"] = '{"ads":[],"blocks":[]}'
    checkpoint.write_text(json.dumps(record))
    with pytest.raises(OCRException, match="omitted"):
        pipeline.run(documents, config())


def test_duplicate_sources_refused_before_paid_calls(documents, tmp_path):
    backend = Backend()
    with pytest.raises(OCRException, match="duplicate source"):
        make_pipeline(tmp_path, backend).run([documents[0], documents[0]], config())
    assert backend.sync_calls == 0


def test_repointed_output_cannot_overwrite_unrelated_csv(documents, tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.run(documents, config())
    unrelated = tmp_path / "unrelated.csv"
    unrelated.write_text("keep this research data")
    redirected = make_pipeline(tmp_path, output="unrelated.csv")
    with pytest.raises(OCRException, match="differ"):
        redirected.run(documents, config())
    assert unrelated.read_text() == "keep this research data"


def test_source_changes_during_acquisition_detected(documents, tmp_path):
    class MutatingBackend(Backend):
        def recognize(self, image, page_id, cfg):
            documents[0].path.write_bytes(b"mutated")
            return super().recognize(image, page_id, cfg)
    adapter = Adapter()
    with pytest.raises(OCRException, match="source changed"):
        make_pipeline(tmp_path, MutatingBackend(), adapter).run(documents, config())
    assert not adapter.sync_calls


def test_all_physical_pages_are_visited(documents, tmp_path, monkeypatch):
    original = __import__("llm_auditkit.ocr.pipeline", fromlist=["inspect_document"]).inspect_document
    monkeypatch.setattr("llm_auditkit.ocr.pipeline.inspect_document",
                        lambda document, cfg: replace(original(document, cfg), page_count=3))
    backend = Backend()
    result = make_pipeline(tmp_path, backend).run(documents[:1], config())
    assert result.page_number.tolist() == [1, 2, 3]
    assert result.ad_id.is_unique
    assert backend.sync_calls == 3
