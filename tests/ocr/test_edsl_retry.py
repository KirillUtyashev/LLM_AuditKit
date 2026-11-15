"""Explicit domain retries must reach the offline provider, not rejected cache."""

import asyncio
import json

import pytest
from edsl import Cache, Jobs
from edsl.coop import Coop

from llm_auditkit.inference import EDSLAdapter, InferenceOrchestrator
from llm_auditkit.inference import edsl_adapter as adapter_module
from llm_auditkit.ocr import NewspaperOCRPipeline, OCRException, OCRStore, SourceDocument

from .helpers import Backend, config, response_for


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("invalid", ["json", "nul", "surrogate"])
def test_explicit_resume_refreshes_only_failed_page_with_real_edsl_cache(tmp_path, monkeypatch, mode, invalid):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(Coop, "fetch_prices", lambda *args, **kwargs: {})
    monkeypatch.setattr(Coop, "edsl_settings", property(lambda self: {}))
    cache, calls = Cache(), []
    model_factory = adapter_module.Model

    def create_model(*args, **kwargs):
        model = model_factory(*args, **kwargs)
        async def provider(user_prompt, system_prompt, **kwargs):
            start = user_prompt.index('{"blocks"')
            payload, _ = json.JSONDecoder().raw_decode(user_prompt[start:])
            tag = payload["metadata"]["tag"]
            calls.append(tag)
            value = response_for(payload["blocks"])
            if tag == "retry" and calls.count("retry") == 1:
                if invalid == "json":
                    text = "not JSON"
                else:
                    value["ads"][0]["text"] += "\x00" if invalid == "nul" else "\ud800"
                    text = json.dumps(value)
            else:
                text = json.dumps(value)
            return {"message": [{"text": text}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        monkeypatch.setattr(model, "async_execute_model_call", provider)
        return model

    monkeypatch.setattr(adapter_module, "Model", create_model)
    original_run, original_async = Jobs.run, Jobs.run_async
    def options(kwargs):
        return {"cache": cache, "disable_remote_cache": True, "use_api_proxy": False,
                "check_api_keys": False, "progress_bar": False, **kwargs}
    monkeypatch.setattr(Jobs, "run", lambda job, **kwargs: original_run(job, **options(kwargs)))
    async def run_async(job, **kwargs):
        return await original_async(job, **options(kwargs))
    monkeypatch.setattr(Jobs, "run_async", run_async)

    documents = []
    for tag in ("first", "retry"):
        source = tmp_path / (tag + ".png")
        with Image.new("RGB", (20, 20)) as image:
            image.save(source)
        documents.append(SourceDocument(source, {"tag": tag}))
    cfg = config()
    cfg.inference.models[0].model = "test"
    pipeline = NewspaperOCRPipeline(Backend(), InferenceOrchestrator(EDSLAdapter()),
                                    OCRStore(tmp_path / "cache", tmp_path / "ads.csv"))
    execute = lambda: (pipeline.run(documents, cfg) if mode == "sync"
                       else asyncio.run(pipeline.run_async(documents, cfg)))
    with pytest.raises(OCRException, match="batch failed"):
        execute()
    records = [json.loads(path.read_text()) for path in pipeline.store.directory.glob("*.json")
               if path.name != "manifest.json"]
    failed_id = next(record["outcome"]["request_id"] for record in records if record["outcome"]["status"] == "failed")
    result = execute()
    assert calls == ["first", "retry", "retry"]
    assert failed_id in result.request_id.tolist()
    assert len(result) == 2
    assert len(execute()) == 2
    assert calls == ["first", "retry", "retry"]  # successful resume never calls a provider
