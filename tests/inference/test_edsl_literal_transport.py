"""Exercise the real EDSL test service through native blocking and async jobs."""

import asyncio

import pytest
from edsl import Jobs, Model
from edsl.caching import Cache
from edsl.jobs.remote_inference import JobsRemoteInferenceHandler

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceBatchError,
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

    model = Model("test", service_name="test")
    model.func = respond
    monkeypatch.setattr(edsl_adapter, "Model", lambda *args, **kwargs: model)

    # Change EDSL's execution settings only. Both methods still run real jobs.
    local_options = dict(
        use_api_proxy=False, disable_remote_inference=True, disable_remote_cache=True,
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


@pytest.fixture
def ordinary_requests():
    return [
        InferenceRequest("clerk-set-a", "Clerk\n1. Casey Brook\n2. Alex Rowan", "local",
                         system_prompt="Clerk reviewer."),
        InferenceRequest("assistant-set-a", "Assistant\n1. Morgan Reed\n2. Jamie Vale", "local",
                         system_prompt="Assistant reviewer."),
    ]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_native_batch_executes_only_the_two_requested_pairs(
    model_calls, ordinary_requests, mode,
):
    adapter = EDSLAdapter()
    if mode == "sync":
        results = adapter.execute_batch(ordinary_requests, MODELS)
    else:
        results = asyncio.run(adapter.execute_batch_async(ordinary_requests, MODELS))

    assert len(model_calls) == len(ordinary_requests)
    for request, result in zip(ordinary_requests, results, strict=True):
        assert (request.prompt, request.system_prompt) in model_calls
        assert result.error is None
        assert result.request_id == request.request_id
        assert result.content == f"Read by {request.system_prompt}"
        assert result.rendered_prompt.user_prompt == request.prompt


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


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_whole_job_offload_refuses_literal_requests_before_upload(
    offline_edsl, monkeypatch, mode,
):
    # Simulate EDSL selecting full-job hosting; don't allow network I/O or
    # accept a silent fallback to local execution or a different provider.
    selected, uploads = [], []

    def select_hosted(handler, disabled):
        selected.append(True)
        return True

    def fake_upload(handler, **kwargs):
        uploads.append(True)
        raise RuntimeError("test stopped ordinary upload")

    monkeypatch.setattr(JobsRemoteInferenceHandler, "use_remote_inference", select_hosted)
    monkeypatch.setattr(JobsRemoteInferenceHandler, "create_remote_inference_job", fake_upload)
    native_run, native_run_async = Jobs.run, Jobs.run_async
    hosted = dict(use_api_proxy=False, offload_execution=True, disable_remote_cache=True)

    def run_with_cache(job, **kwargs):
        return native_run(job, cache=Cache(), **hosted, **kwargs)

    async def run_with_cache_async(job, **kwargs):
        return await native_run_async(job, cache=Cache(), **hosted, **kwargs)

    monkeypatch.setattr(Jobs, "run", run_with_cache)
    monkeypatch.setattr(Jobs, "run_async", run_with_cache_async)

    adapter = EDSLAdapter()
    for body in ("{{ 2+2 }}", "plain"):
        request = InferenceRequest("offload-check", body, "local")
        with pytest.raises(InferenceBatchError) as caught:
            if mode == "sync":
                adapter.execute_batch([request], MODELS)
            else:
                asyncio.run(adapter.execute_batch_async([request], MODELS))
        if body != "plain":
            assert not uploads
            assert "offload" in str(caught.value).lower()
            assert body not in str(caught.value)

    assert selected == [True, True]
    assert uploads == [True]  # Only the ordinary job reached the upload stub.


def test_unverified_edsl_version_rejects_only_jobs_requiring_literal_rendering(
    model_calls, monkeypatch,
):
    monkeypatch.setattr(edsl_adapter, "version", lambda name: "1.0.99")
    adapter = EDSLAdapter()
    plain = InferenceRequest("plain", "Review one application.", "local")
    assert adapter.render_batch([plain], MODELS)[0].user_prompt == plain.prompt
    literal = InferenceRequest("literal", "Review {{example}}.", "local")
    with pytest.raises(InferenceBatchError, match=r"requires EDSL 1\.0\.8 or 1\.0\.9"):
        adapter.render_batch([literal], MODELS)
    assert not model_calls
