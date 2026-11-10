"""Exercise the real EDSL test service through native blocking and async jobs."""

import asyncio

import pytest
from edsl import Jobs, Model
from edsl.caching import Cache

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceRequest,
    ModelConfig,
    edsl_adapter,
)


MODELS = {"local": ModelConfig("local", "test", "test")}


@pytest.fixture
def model_calls(monkeypatch, offline_edsl):
    calls = []

    def respond(user_prompt, system_prompt, files):
        calls.append((user_prompt, system_prompt))
        return f"Read by {system_prompt}"

    def create_model(*args, **kwargs):
        model = Model(*args, **kwargs)
        model.func = respond
        return model

    monkeypatch.setattr(edsl_adapter, "Model", create_model)

    # Change EDSL's execution settings only. Both methods still run real jobs.
    local_options = dict(
        use_api_proxy=False, disable_remote_cache=True,
        stop_on_exception=True,
    )
    native_run, native_run_async = Jobs.run, Jobs.run_async
    cache = Cache()

    def run_locally(job, **kwargs):
        return native_run(job, cache=cache, **local_options, **kwargs)

    async def run_locally_async(job, **kwargs):
        return await native_run_async(job, cache=cache, **local_options, **kwargs)

    monkeypatch.setattr(Jobs, "run", run_locally)
    monkeypatch.setattr(Jobs, "run_async", run_locally_async)
    return calls


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("body", [
    "Transcribe:\r\n{% if true %}text{% endif %}, {{ 2+2 }} and {#note#}.\n",
    "  Transcribe π, including unmatched {{ or {%\r\n",
])
def test_native_jobs_preserve_literal_jinja_text(model_calls, mode, body):
    request = InferenceRequest("literal", body, "local", system_prompt="Reviewer.")
    adapter = EDSLAdapter()
    if mode == "sync":
        (result,) = adapter.execute_batch([request], MODELS)
    else:
        (result,) = asyncio.run(adapter.execute_batch_async([request], MODELS))

    assert result.error is None
    assert result.request_id == request.request_id
    ((user_prompt, system_prompt),) = model_calls
    assert system_prompt == request.system_prompt
    assert result.rendered_prompt.user_prompt == user_prompt
    assert user_prompt == body


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_interleaved_reviewers_keep_literal_roles_pairings_and_return_order(model_calls, mode):
    reviewer = "Day }} %} #}"  # Closing delimiters alone are data in a persona.
    requests = [
        InferenceRequest("first", "Review {{case_A}}.", "local", persona="Day",
                         system_prompt="Inspect the work."),
        InferenceRequest("second", "Review case B.", "local", persona=reviewer,
                         system_prompt="Check the report."),
        InferenceRequest("third", "Review case C.", "local", persona="Day",
                         system_prompt="Inspect the work."),
    ]
    adapter = EDSLAdapter()
    preview = adapter.render_batch(requests, MODELS)
    assert not model_calls
    if mode == "sync":
        results = adapter.execute_batch(requests, MODELS)
    else:
        results = asyncio.run(adapter.execute_batch_async(requests, MODELS))
    assert len(model_calls) == len(requests)
    for request, shown, result in zip(requests, preview, results, strict=True):
        assert result.error is None
        assert shown.request_id == result.request_id == request.request_id
        assert result.rendered_prompt == shown
        assert shown.user_prompt == request.prompt
        assert shown.system_prompt.startswith(request.system_prompt)
        assert shown.system_prompt.endswith("Your traits: " + str({"persona": request.persona}))
        assert (shown.user_prompt, shown.system_prompt) in model_calls


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_cache_keeps_distinct_literal_bodies_and_reuses_exact_replays(model_calls, mode):
    bodies = ["{{ 2+2 }}", "{{ 3+1 }}", "4"]
    requests = [
        InferenceRequest(f"r-{i}", body, "local", system_prompt="Reviewer.")
        for i, body in enumerate(bodies)
    ]
    adapter = EDSLAdapter()
    for _ in range(2):
        if mode == "sync":
            results = adapter.execute_batch(requests, MODELS)
        else:
            results = asyncio.run(adapter.execute_batch_async(requests, MODELS))
        assert [r.request_id for r in results] == [r.request_id for r in requests]
        assert all(r.error is None for r in results)
        assert [r.rendered_prompt.user_prompt for r in results] == bodies
        assert sorted(model_calls) == sorted((s, "Reviewer.") for s in bodies)
