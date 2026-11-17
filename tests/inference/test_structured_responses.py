"""Provider-schema transport tested with real EDSL and a network-free provider."""

import asyncio
import json

import pytest
from edsl import Cache, Jobs
from edsl.coop import Coop
from pydantic import BaseModel, ConfigDict

from llm_auditkit.inference import (
    EDSLAdapter, InferenceConfig, InferenceOrchestrator, InferenceRequest,
    InferenceRequestValidationError, ModelConfig, StructuredResponseFormat,
)
from llm_auditkit.inference import edsl_adapter as adapter_module
from llm_auditkit.inference.batching import group_requests_by_compatibility
from llm_auditkit.inference.validation import validate_inference_requests
from llm_auditkit.templates.parts import template_parts_model


def response_model():
    return template_parts_model(1, ("name", "qualification"))


def request(identity="one", model=None):
    return InferenceRequest(
        identity, f"Create resume {identity}. Keep {{{{name}}}} and {{{{qualification}}}} as references.",
        "model", system_prompt="Do not fill controlled attributes.",
        response_format=StructuredResponseFormat(model or response_model()),
    )


def config():
    return InferenceConfig([ModelConfig("model", "openai", "gpt-5.5")], batch_size=5)


def payload():
    return {"templates": [{"parts": [
        {"field": "name"}, {"text": "\nEXPERIENCE\n"}, {"field": "qualification"},
    ]}]}


def test_validated_schema_is_grouped_by_structure_not_python_identity():
    class First(BaseModel):
        model_config = ConfigDict(extra="forbid")
        answer: str

    class Second(BaseModel):
        model_config = ConfigDict(extra="forbid")
        count: int

    identical = type("First", (First,), {})
    requests = [request("a", First), request("b", identical), request("c", Second)]
    validate_inference_requests(requests, config())
    groups = group_requests_by_compatibility(requests, {"model": config().models[0]})
    assert [[r.request_id for r in g.requests] for g in groups] == [["a", "b"], ["c"]]


@pytest.mark.parametrize("bad", [dict, {}, None, response_model()(templates=payload()["templates"])])
def test_invalid_schema_model_is_rejected_before_execution(bad):
    req = request()
    req.response_format.response_model = bad
    with pytest.raises(InferenceRequestValidationError, match="BaseModel subclass"):
        validate_inference_requests([req], config())


def test_no_silent_fallback_for_unsupported_provider():
    configuration = config()
    configuration.models[0].provider = "test"
    with pytest.raises(InferenceRequestValidationError, match="prompt-only fallback"):
        validate_inference_requests([request()], configuration)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_real_edsl_transports_nested_schema_and_normalizes_results(monkeypatch, offline_edsl, mode):
    from edsl.caching.cache_handler import CacheHandler
    monkeypatch.setattr(CacheHandler, "gen_cache", lambda self: pytest.fail("must use isolated test cache"))
    monkeypatch.setattr(Coop, "fetch_prices", lambda *a, **kw: {})
    monkeypatch.setattr(Coop, "edsl_settings", property(lambda self: {}))
    original_model = adapter_module.Model
    original_run, original_async = Jobs.run, Jobs.run_async
    cache = Cache()
    observed = []

    def make_model(*args, **kwargs):
        # Use EDSL's local test transport while retaining OpenAI request config.
        model = original_model("test", service_name="test")

        async def provider(user_prompt, system_prompt, **options):
            observed.append(options)
            assert "{{name}}" in user_prompt
            return {"message": [{"text": json.dumps(payload(), indent=2)}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        monkeypatch.setattr(model, "async_execute_model_call", provider)
        return model

    options = dict(cache=cache, disable_remote_cache=True, use_api_proxy=False,
                   check_api_keys=False, progress_bar=False)

    def run(job, **kwargs):
        return original_run(job, **{**kwargs, **options})

    async def run_async(job, **kwargs):
        return await original_async(job, **{**kwargs, **options})

    monkeypatch.setattr(adapter_module, "Model", make_model)
    monkeypatch.setattr(Jobs, "run", run)
    monkeypatch.setattr(Jobs, "run_async", run_async)
    orchestrator = InferenceOrchestrator(EDSLAdapter())
    requests = [request("one"), request("two")]
    preview = orchestrator.preview_batch(requests, config())

    async def collect():
        return [b async for b in orchestrator.run_batches_async(requests, config())]

    def execute():
        return (list(orchestrator.run_batches(requests, config())) if mode == "sync"
                else asyncio.run(collect()))

    batches = execute()
    assert len(observed) == 2
    schema = response_model().model_json_schema()
    for observed_options in observed:
        assert observed_options["response_schema"] == schema
    assert [r.request_id for r in batches[0].results] == ["one", "two"]
    for result, rendered in zip(batches[0].results, preview.prompts, strict=True):
        assert result.error is None
        assert result.structured_content == payload()
        assert result.rendered_prompt == rendered
        assert json.loads(result.content) == payload()
    execute()
    assert len(observed) == 2  # EDSL cache, not a second AuditKit cache.


@pytest.mark.parametrize("invalid", [None, {"templates": []}, {"templates": "invalid"}])
def test_invalid_schema_outcomes_cannot_be_reported_as_success(invalid):
    from types import SimpleNamespace
    req = request()
    result = SimpleNamespace(answer={"response": invalid}, data={
        "generated_tokens": {"response": json.dumps(invalid)},
    })
    assert adapter_module._result_response(result, req) == (None, None, None)


def test_openai_service_enables_strict_schema_with_edsl():
    # Exercise EDSL's actual provider method with a fake SDK client: no API call.
    from edsl.inference_services.services.open_ai_service import OpenAIService
    from types import SimpleNamespace
    observed = {}

    async def create(**options):
        observed.update(options)
        return SimpleNamespace(model_dump=lambda: {"choices": []})

    model = OpenAIService.create_model("gpt-5.5")()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model.async_client = lambda: client
    model.sync_client = lambda: None
    schema = response_model().model_json_schema()
    asyncio.run(model.async_execute_model_call(
        user_prompt="Create a resume", system_prompt="Use slots",
        response_schema=schema, response_schema_name="ResumeTemplates",
    ))
    assert observed["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "ResumeTemplates", "strict": True, "schema": schema,
    }}


@pytest.mark.parametrize("finish_reason,refusal", [("length", None), ("content_filter", None), ("stop", "Refused")])
def test_incomplete_or_refused_responses_fail_even_if_json_matches(finish_reason, refusal):
    from types import SimpleNamespace
    result = SimpleNamespace(answer={"response": payload()}, data={
        "generated_tokens": {"response": json.dumps(payload())},
        "raw_model_response": {"response": {"choices": [{
            "finish_reason": finish_reason, "message": {"refusal": refusal},
        }]}},
    })
    assert adapter_module._result_response(result, request()) == (None, None, None)


def test_nested_model_survives_edsl_question_serialization_and_rejects_private_invalid_text():
    from edsl.questions.question_base import QuestionBase
    from edsl.questions.exceptions import QuestionAnswerValidationError
    question = adapter_module._SchemaQuestionPydantic(
        question_name="response", question_text="Generate a resume",
        pydantic_model=response_model(),
    )
    clone = QuestionBase.from_dict(question.to_dict())
    assert clone.user_pydantic_model is response_model()
    assert clone.get_response_schema() == response_model().model_json_schema()
    bad = {"templates": [{"parts": [{"field": "private_unconfigured_value"}]}]}
    with pytest.raises(QuestionAnswerValidationError) as captured:
        clone._validate_answer({"answer": {}, "generated_tokens": json.dumps(bad)})
    assert "private_unconfigured_value" not in str(captured.value)


def test_object_models_must_forbid_extra_keys_before_any_inference():
    class Loose(BaseModel):
        value: str

    class Nested(BaseModel):
        model_config = ConfigDict(extra="forbid")
        child: Loose

    for model in (Loose, Nested):
        with pytest.raises(InferenceRequestValidationError, match="extra='forbid'"):
            validate_inference_requests([request(model=model)], config())
