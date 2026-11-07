"""Real EDSL scheduling and prompt rendering with an offline provider double."""

import asyncio
import json

import pytest
from edsl import Cache, Jobs
from edsl.coop import Coop

from llm_auditkit.inference import (
    DictResponseFormat, EDSLAdapter, InferenceRequest, ModelConfig, ResponseField,
)
from llm_auditkit.inference import edsl_adapter as adapter_module


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("structured", [False, True])
def test_real_edsl_pairs_concurrently_and_preserves_literals_before_caching(
    monkeypatch, mode, structured,
):
    monkeypatch.setattr(Coop, "fetch_prices", lambda *args, **kwargs: {})
    monkeypatch.setattr(Coop, "edsl_settings", property(lambda self: {}))
    cache = Cache()
    observed = []
    all_started = None
    model_factory = adapter_module.Model
    literal = "{{request_id}} {{dict}} {{True}} {{response}} {{name}} {% if True %}text{% endif %}"
    requests = [
        InferenceRequest(
            f"request-{i}", f"Row {i}: preserve {literal}", "test-model",
            system_prompt=f"Instruction {i}: {literal}",
            persona=f"Persona {i}: {literal}",
            response_format=(
                DictResponseFormat(
                    [ResponseField("template_1", "string", "A resume template")],
                    include_comment=False, include_type_hints=False,
                ) if structured else None
            ),
        )
        for i in range(3)
    ]

    def create_model(*args, **kwargs):
        model = model_factory(*args, **kwargs)

        async def provider(user_prompt, system_prompt, **kwargs):
            nonlocal all_started
            if all_started is None:
                all_started = asyncio.Event()
            observed.append((user_prompt, system_prompt))
            if len(observed) == len(requests):
                all_started.set()
            # Serial execution cannot pass this barrier. EDSL must schedule all
            # interviews before any provider response can complete.
            await asyncio.wait_for(all_started.wait(), timeout=5)
            return {
                "message": [{"text": (
                    json.dumps({"template_1": literal}) if structured else "offline answer"
                )}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        monkeypatch.setattr(model, "async_execute_model_call", provider)
        return model

    monkeypatch.setattr(adapter_module, "Model", create_model)
    original_run, original_async = Jobs.run, Jobs.run_async
    offline_options = dict(
        cache=cache, disable_remote_cache=True, use_api_proxy=False,
        check_api_keys=False, progress_bar=False,
    )

    def run(job, **kwargs):
        return original_run(job, **kwargs, **offline_options)

    async def run_async(job, **kwargs):
        return await original_async(job, **kwargs, **offline_options)

    monkeypatch.setattr(Jobs, "run", run)
    monkeypatch.setattr(Jobs, "run_async", run_async)
    models = {"test-model": ModelConfig("test-model", "test", "test")}
    adapter = EDSLAdapter()
    preview = adapter.render_batch(requests, models)
    execute = (
        lambda: adapter.execute_batch(requests, models)
        if mode == "sync"
        else asyncio.run(adapter.execute_batch_async(requests, models))
    )
    results = execute()

    assert len(observed) == len(requests)
    assert [result.request_id for result in results] == [r.request_id for r in requests]
    for request, rendered, result in zip(requests, preview, results, strict=True):
        assert result.error is None
        if structured:
            assert result.structured_content == {"template_1": literal}
        else:
            assert result.content == "offline answer"
        assert result.rendered_prompt == rendered
        assert request.prompt in rendered.user_prompt
        assert request.system_prompt in rendered.system_prompt
        assert repr({"persona": request.persona}) in rendered.system_prompt
        assert (rendered.user_prompt, rendered.system_prompt) in observed

    assert len(cache) == len(requests)
    assert {entry.user_prompt for entry in cache.values()} == {p.user_prompt for p in preview}
    cached_results = execute()
    assert all(result.error is None for result in cached_results)
    assert len(observed) == len(requests)  # Cached jobs do not re-call the provider.
