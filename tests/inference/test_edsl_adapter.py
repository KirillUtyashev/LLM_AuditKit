"""Offline tests for the Expected Parrot EDSL adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from llm_auditkit.inference import (
    DictResponseFormat,
    EDSLAdapter,
    InferenceAdapter,
    InferenceBatchError,
    InferenceBatchResult,
    InferenceConfig,
    InferenceOrchestrator,
    InferenceRequest,
    ModelConfig,
    ResponseField,
    TokenLogprob,
)
from llm_auditkit.inference import edsl_adapter as adapter_module


@dataclass
class FakeEDSLRuntime:
    responses: dict[str, object] = field(default_factory=dict)
    generated_content: dict[str, object] = field(default_factory=dict)
    comments: dict[str, object] = field(default_factory=dict)
    raw_model_responses: dict[str, object] = field(default_factory=dict)
    exceptions: dict[str, Exception] = field(default_factory=dict)
    omitted_request_ids: set[str] = field(default_factory=set)
    prompt_error: Exception | None = None
    sync_error: Exception | None = None
    async_error: Exception | None = None
    questions: list[object] = field(default_factory=list)
    agents: list[object] = field(default_factory=list)
    models: list[object] = field(default_factory=list)
    jobs: list[object] = field(default_factory=list)
    events: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)


@pytest.fixture
def fake_edsl(monkeypatch: pytest.MonkeyPatch) -> FakeEDSLRuntime:
    runtime = FakeEDSLRuntime()

    class FakePrompt(str):
        def __new__(cls, text: str) -> FakePrompt:
            prompt = super().__new__(cls, text)
            prompt.text = text
            return prompt

    class FakeDataset:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = rows

        def to_dicts(self) -> list[dict[str, object]]:
            return list(self.rows)

    class FakeScenario(dict[str, object]):
        pass

    class FakeScenarioList(list[FakeScenario]):
        pass

    class FakeAgentList(list[object]):
        pass

    class FakeAgent:
        def __init__(
            self,
            traits: dict[str, object] | None = None,
            **kwargs: object,
        ) -> None:
            self.traits = traits
            self.kwargs = kwargs
            runtime.agents.append(self)

    class FakeModel:
        def __init__(
            self,
            model_name: str,
            *,
            service_name: str,
            **parameters: object,
        ) -> None:
            self.model_name = model_name
            self.service_name = service_name
            self.parameters = parameters
            runtime.models.append(self)

    class FakeSurvey:
        def __init__(self, questions: list[object]) -> None:
            self.questions = questions

    class FakeInterview:
        def __init__(
            self,
            *,
            agent: FakeAgent,
            survey: FakeSurvey,
            scenario: FakeScenario,
            model: FakeModel,
        ) -> None:
            self.agent = agent
            self.survey = survey
            self.scenario = scenario
            self.model = model

    class FakeInvigilator:
        def __init__(self, scenario: FakeScenario) -> None:
            self.scenario = scenario

    class FakeExceptionEntry:
        def __init__(self, scenario: FakeScenario, exception: Exception) -> None:
            self.invigilator = FakeInvigilator(scenario)
            self.exception = exception
            self.exception_type = type(exception).__name__

    class FakeTaskHistory:
        def __init__(self, scenarios: list[FakeScenario]) -> None:
            entries = [
                FakeExceptionEntry(scenario, runtime.exceptions[scenario["request_id"]])
                for scenario in scenarios
                if scenario["request_id"] in runtime.exceptions
            ]
            self.exceptions = [{"response": entries}] if entries else []

    class FakeResult:
        def __init__(
            self,
            scenario: FakeScenario,
            answer: object,
            data: dict[str, object],
        ) -> None:
            self.scenario = scenario
            self.answer = answer
            self.data = data

    class FakeResults(list[FakeResult]):
        def __init__(
            self,
            results: list[FakeResult],
            scenarios: list[FakeScenario],
        ) -> None:
            super().__init__(results)
            self.task_history = FakeTaskHistory(scenarios)

    class FakeJob:
        def __init__(self, interviews: list[FakeInterview]) -> None:
            self.interviews = interviews
            self.question = interviews[0].survey.questions[0]
            self.scenarios = FakeScenarioList()
            self.agents = FakeAgentList()
            self.model = interviews[0].model
            runtime.jobs.append(self)

        @staticmethod
        def _system_prompt(agent: FakeAgent) -> str:
            parts = []
            if "instruction" in agent.kwargs:
                parts.append(f"instruction:{agent.kwargs['instruction']}")
            if agent.traits is not None:
                parts.append(f"persona:{agent.traits['persona']}")
            return "" if not parts else f"EDSL system:{'|'.join(parts)}"

        def prompts(self) -> FakeDataset:
            if runtime.prompt_error is not None:
                raise runtime.prompt_error
            runtime.events.append(("prompts", self.model.model_name, {}))
            rows = [
                {
                    "scenario_index": index,
                    "user_prompt": FakePrompt(
                        f"EDSL user:{interview.scenario['prompt']}"
                    ),
                    "system_prompt": FakePrompt(
                        self._system_prompt(interview.agent)
                    ),
                }
                for index, interview in enumerate(self.interviews)
            ]
            return FakeDataset(list(reversed(rows)))

        def run(self, **kwargs: object) -> FakeResults:
            if runtime.sync_error is not None:
                raise runtime.sync_error
            runtime.events.append(("run", self.model.model_name, kwargs))
            return self._results()

        async def run_async(self, **kwargs: object) -> FakeResults:
            if runtime.async_error is not None:
                raise runtime.async_error
            runtime.events.append(("run_async", self.model.model_name, kwargs))
            return self._results()

        def _results(self) -> FakeResults:
            result_items = []
            for interview in reversed(self.interviews):
                scenario = interview.scenario
                request_id = scenario["request_id"]
                if request_id in runtime.omitted_request_ids:
                    continue
                if request_id in runtime.responses:
                    response = runtime.responses[request_id]
                elif isinstance(self.question, FakeQuestionDict):
                    response = {key: "Yes" for key in self.question.answer_keys}
                else:
                    response = f"answer:{request_id}"

                data = {
                    "generated_tokens": {
                        "response_generated_tokens": runtime.generated_content.get(
                            request_id,
                            str(response),
                        )
                    },
                    "comments_dict": {
                        "response_comment": runtime.comments.get(request_id)
                    },
                    "raw_model_response": {
                        "response_raw_model_response": runtime.raw_model_responses.get(
                            request_id
                        )
                    },
                    "prompt": {
                        "response_user_prompt": FakePrompt(
                            f"EDSL user:{scenario['prompt']}"
                        ),
                        "response_system_prompt": FakePrompt(
                            self._system_prompt(interview.agent)
                        ),
                    },
                }
                result_items.append(
                    FakeResult(scenario, {"response": response}, data)
                )
            return FakeResults(
                result_items,
                [interview.scenario for interview in self.interviews],
            )

    class FakeJobs:
        @classmethod
        def from_interviews(
            cls,
            interviews: list[FakeInterview],
        ) -> FakeJob:
            return FakeJob(interviews)

    class FakeQuestionFreeText:
        def __init__(self, *, question_name: str, question_text: str) -> None:
            self.question_name = question_name
            self.question_text = question_text
            runtime.questions.append(self)

    class FakeQuestionDict(FakeQuestionFreeText):
        def __init__(
            self,
            *,
            question_name: str,
            question_text: str,
            answer_keys: list[str],
            value_types: list[str] | None,
            value_descriptions: list[str],
            include_comment: bool,
        ) -> None:
            super().__init__(
                question_name=question_name,
                question_text=question_text,
            )
            self.answer_keys = answer_keys
            self.value_types = value_types
            self.value_descriptions = value_descriptions
            self.include_comment = include_comment

    monkeypatch.setattr(adapter_module, "Agent", FakeAgent)
    monkeypatch.setattr(adapter_module, "AgentList", FakeAgentList)
    monkeypatch.setattr(adapter_module, "Interview", FakeInterview)
    monkeypatch.setattr(adapter_module, "Jobs", FakeJobs)
    monkeypatch.setattr(adapter_module, "Model", FakeModel)
    monkeypatch.setattr(adapter_module, "QuestionFreeText", FakeQuestionFreeText)
    monkeypatch.setattr(adapter_module, "QuestionDict", FakeQuestionDict)
    monkeypatch.setattr(adapter_module, "Scenario", FakeScenario)
    monkeypatch.setattr(adapter_module, "ScenarioList", FakeScenarioList)
    monkeypatch.setattr(adapter_module, "Survey", FakeSurvey)
    return runtime


def _models() -> dict[str, ModelConfig]:
    first = ModelConfig(
        config_id="model-1",
        provider="provider-1",
        model="first-model",
        parameters={"temperature": 0.2},
    )
    second = ModelConfig(
        config_id="model-2",
        provider="provider-2",
        model="second-model",
    )
    return {first.config_id: first, second.config_id: second}


def _requests() -> list[InferenceRequest]:
    return [
        InferenceRequest(
            request_id="request-1",
            prompt="First prompt",
            model_config_id="model-1",
            system_prompt="instruction-a",
            metadata={"position": 1},
            persona="persona-a",
        ),
        InferenceRequest(
            request_id="request-2",
            prompt="Second prompt",
            model_config_id="model-2",
            metadata={"position": 2},
        ),
        InferenceRequest(
            request_id="request-3",
            prompt="Third prompt",
            model_config_id="model-1",
            system_prompt="instruction-a",
            metadata={"position": 3},
            persona="persona-c",
        ),
    ]


def test_edsl_adapter_implements_the_generic_protocol() -> None:
    assert isinstance(EDSLAdapter(), InferenceAdapter)


def test_public_orchestrator_api_integrates_with_edsl_adapter(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = _requests()
    config = InferenceConfig(models=list(_models().values()), batch_size=2)
    inference = InferenceOrchestrator(EDSLAdapter())

    preview = inference.preview_batch(requests, config)
    sync_batches = list(inference.run_batches(requests, config))

    async def collect_async_batches() -> list[InferenceBatchResult]:
        return [
            batch
            async for batch in inference.run_batches_async(requests, config)
        ]

    async_batches = asyncio.run(collect_async_batches())

    assert preview.batch_number == 1
    assert preview.total_batches == 2
    assert [prompt.request_id for prompt in preview.prompts] == [
        "request-1",
        "request-2",
    ]
    assert [batch.batch_number for batch in sync_batches] == [1, 2]
    assert [batch.batch_number for batch in async_batches] == [1, 2]
    assert [
        result.request_id for batch in sync_batches for result in batch.results
    ] == ["request-1", "request-2", "request-3"]
    assert [
        result.request_id for batch in async_batches for result in batch.results
    ] == ["request-1", "request-2", "request-3"]


def test_render_batch_uses_effective_edsl_prompts_without_inference(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    rendered = EDSLAdapter().render_batch(_requests(), _models())

    assert [prompt.request_id for prompt in rendered] == [
        "request-1",
        "request-2",
        "request-3",
    ]
    assert [prompt.user_prompt for prompt in rendered] == [
        "EDSL user:First prompt",
        "EDSL user:Second prompt",
        "EDSL user:Third prompt",
    ]
    assert [prompt.system_prompt for prompt in rendered] == [
        "EDSL system:instruction:instruction-a|persona:persona-a",
        "",
        "EDSL system:instruction:instruction-a|persona:persona-c",
    ]
    assert all(type(prompt.user_prompt) is str for prompt in rendered)
    assert all(type(prompt.system_prompt) is str for prompt in rendered)
    assert fake_edsl.events == [
        ("prompts", "first-model", {}),
        ("prompts", "second-model", {}),
    ]


def test_job_construction_uses_explicitly_paired_edsl_interviews(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = _requests()

    results = EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 2
    assert [scenario["request_id"] for scenario in fake_edsl.jobs[0].scenarios] == [
        "request-1",
        "request-3",
    ]
    assert all(
        set(scenario) == {"request_id", "prompt"}
        for job in fake_edsl.jobs
        for scenario in job.scenarios
    )
    assert [
        interview.scenario["request_id"]
        for interview in fake_edsl.jobs[0].interviews
    ] == ["request-1", "request-3"]
    assert [
        interview.agent.traits for interview in fake_edsl.jobs[0].interviews
    ] == [{"persona": "persona-a"}, {"persona": "persona-c"}]
    assert fake_edsl.agents[0].kwargs == {"instruction": "instruction-a"}
    assert fake_edsl.agents[1].kwargs == {"instruction": "instruction-a"}
    assert fake_edsl.agents[2].traits is None
    assert fake_edsl.models[0].model_name == "first-model"
    assert fake_edsl.models[0].service_name == "provider-1"
    assert fake_edsl.models[0].parameters == {"temperature": 0.2}
    assert fake_edsl.questions[0].question_name == "response"
    assert fake_edsl.questions[0].question_text == "{{ prompt }}"
    assert fake_edsl.events == [
        ("run", "first-model", {"print_exceptions": False}),
        ("run", "second-model", {"print_exceptions": False}),
    ]
    assert [result.request_id for result in results] == [
        "request-1",
        "request-2",
        "request-3",
    ]
    assert results[0].metadata == requests[0].metadata
    assert results[0].metadata is not requests[0].metadata
    assert results[0].rendered_prompt is not None
    assert results[0].rendered_prompt.user_prompt == "EDSL user:First prompt"


def test_async_execution_uses_only_sequential_run_async_calls(
    fake_edsl: FakeEDSLRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[list[str]] = []

    async def record_cleanup(
        requests: list[InferenceRequest],
        models: dict[str, ModelConfig],
    ) -> None:
        del models
        cleanup_calls.append([request.request_id for request in requests])

    monkeypatch.setattr(adapter_module, "_close_edsl_async_clients", record_cleanup)

    results = asyncio.run(EDSLAdapter().execute_batch_async(_requests(), _models()))

    assert [result.request_id for result in results] == [
        "request-1",
        "request-2",
        "request-3",
    ]
    assert fake_edsl.events == [
        ("run_async", "first-model", {"print_exceptions": False}),
        ("run_async", "second-model", {"print_exceptions": False}),
    ]
    assert cleanup_calls == [["request-1", "request-2", "request-3"]]


def test_async_cleanup_failure_preserves_successful_batch_outcome(
    fake_edsl: FakeEDSLRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cleanup_error = RuntimeError("cleanup broke")

    class FailingService:
        @staticmethod
        async def close_async_clients() -> None:
            raise cleanup_error

    class FailingRegistry:
        @staticmethod
        def get_service_class(provider_name: str) -> type[FailingService]:
            del provider_name
            return FailingService

    monkeypatch.setattr(adapter_module, "GLOBAL_REGISTRY", FailingRegistry())
    requests = _requests()
    config = InferenceConfig(models=list(_models().values()), batch_size=3)
    inference = InferenceOrchestrator(EDSLAdapter())

    async def collect_batches() -> list[InferenceBatchResult]:
        return [
            batch
            async for batch in inference.run_batches_async(requests, config)
        ]

    with caplog.at_level("WARNING", logger=adapter_module.__name__):
        batches = asyncio.run(collect_batches())

    assert [result.request_id for result in batches[0].results] == [
        "request-1",
        "request-2",
        "request-3",
    ]
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
    assert caplog.records[0].exc_info[1] is cleanup_error


def test_async_cleanup_failure_preserves_original_execution_error(
    fake_edsl: FakeEDSLRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    execution_error = RuntimeError("async execution broke")
    cleanup_error = RuntimeError("cleanup broke")
    fake_edsl.async_error = execution_error

    class FailingService:
        @staticmethod
        async def close_async_clients() -> None:
            raise cleanup_error

    class FailingRegistry:
        @staticmethod
        def get_service_class(provider_name: str) -> type[FailingService]:
            del provider_name
            return FailingService

    monkeypatch.setattr(adapter_module, "GLOBAL_REGISTRY", FailingRegistry())
    requests = _requests()
    config = InferenceConfig(models=list(_models().values()), batch_size=3)
    inference = InferenceOrchestrator(EDSLAdapter())

    async def collect_batches() -> None:
        async for _ in inference.run_batches_async(requests, config):
            pass

    with caplog.at_level("WARNING", logger=adapter_module.__name__):
        with pytest.raises(
            InferenceBatchError,
            match="async execution broke",
        ) as reported_error:
            asyncio.run(collect_batches())

    assert reported_error.value.__cause__ is execution_error
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
    assert caplog.records[0].exc_info[1] is cleanup_error


def test_task_history_exception_is_used_for_a_missing_response(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.responses[request.request_id] = None
    fake_edsl.exceptions[request.request_id] = ValueError("provider rejected request")

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.content is None
    assert result.error is not None
    assert result.error.type == "ValueError"
    assert result.error.message == "provider rejected request"


def test_missing_response_without_task_history_uses_generic_terminal_error(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.responses[request.request_id] = None

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.content is None
    assert result.error is not None
    assert result.error.type == "EDSLInferenceError"
    assert result.error.message == "EDSL returned no response content"


def test_successful_response_ignores_a_prior_task_history_exception(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.responses[request.request_id] = "eventual success"
    fake_edsl.exceptions[request.request_id] = RuntimeError("earlier attempt failed")

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.content == "eventual success"
    assert result.error is None


def test_none_and_empty_system_prompts_create_distinct_interview_agents(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = [
        InferenceRequest("request-1", "Prompt one", "model-1", None),
        InferenceRequest("request-2", "Prompt two", "model-1", ""),
    ]

    EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 1
    assert fake_edsl.agents[0].traits is None
    assert fake_edsl.agents[0].kwargs == {}
    assert fake_edsl.agents[1].traits is None
    assert fake_edsl.agents[1].kwargs == {"instruction": ""}


def test_non_string_edsl_response_is_a_systemic_failure(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.responses[request.request_id] = {"unexpected": "object"}

    with pytest.raises(InferenceBatchError, match="non-string"):
        EDSLAdapter().execute_batch([request], _models())


def test_dictionary_response_and_openai_logprobs_are_normalized(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-1",
        prompt="Choose applicants.",
        model_config_id="model-1",
        system_prompt="evaluate applicants",
        persona="hiring manager",
        response_format=DictResponseFormat(
            fields=[
                ResponseField("Applicant 1", "string", "Yes or No"),
                ResponseField("Applicant 2", "string", "Yes or No"),
            ],
            include_comment=True,
        ),
    )
    fake_edsl.responses[request.request_id] = {
        "Applicant 1": "Yes",
        "Applicant 2": "No",
    }
    fake_edsl.generated_content[request.request_id] = (
        '{"Applicant 1": "Yes", "Applicant 2": "No"}'
    )
    fake_edsl.comments[request.request_id] = "Applicant 1 is stronger."
    fake_edsl.raw_model_responses[request.request_id] = {
        "choices": [
            {
                "logprobs": {
                    "content": [
                        {"token": "Yes", "logprob": -0.1},
                        {"token": "No", "logprob": -0.2},
                    ]
                }
            }
        ]
    }

    result = EDSLAdapter().execute_batch([request], _models())[0]

    question = fake_edsl.questions[0]
    assert question.answer_keys == ["Applicant 1", "Applicant 2"]
    assert question.value_types == ["str", "str"]
    assert question.value_descriptions == ["Yes or No", "Yes or No"]
    assert question.include_comment is True
    assert result.content == '{"Applicant 1": "Yes", "Applicant 2": "No"}'
    assert result.structured_content == {
        "Applicant 1": "Yes",
        "Applicant 2": "No",
    }
    assert result.comment == "Applicant 1 is stronger."
    assert result.token_logprobs == [
        TokenLogprob("Yes", -0.1),
        TokenLogprob("No", -0.2),
    ]
    assert result.rendered_prompt is not None
    assert result.rendered_prompt.system_prompt == (
        "EDSL system:instruction:evaluate applicants|persona:hiring manager"
    )


def test_dictionary_response_is_recovered_from_complete_generated_content(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-recovery",
        prompt="Choose applicants.",
        model_config_id="model-1",
        response_format=DictResponseFormat(
            fields=[
                ResponseField("Applicant 1", "string", "Yes or No"),
                ResponseField("Applicant 2", "string", "Yes or No"),
            ],
            include_comment=True,
        ),
    )
    fake_edsl.responses[request.request_id] = None
    fake_edsl.generated_content[request.request_id] = """```json
{
  "Applicant 2": "No",
  "Applicant 1": "Yes because the note contains {relevant experience}"
}
```
Applicant 1 is stronger overall."""
    fake_edsl.comments[request.request_id] = "The response was not valid."
    fake_edsl.exceptions[request.request_id] = ValueError(
        "EDSL split the dictionary at its first newline"
    )

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.error is None
    assert result.content == fake_edsl.generated_content[request.request_id]
    assert result.structured_content == {
        "Applicant 1": "Yes because the note contains {relevant experience}",
        "Applicant 2": "No",
    }
    assert result.comment == "Applicant 1 is stronger overall."


def test_dictionary_recovery_rejects_content_that_does_not_match_schema(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-recovery-invalid",
        prompt="Choose applicants.",
        model_config_id="model-1",
        response_format=DictResponseFormat(
            fields=[
                ResponseField("Applicant 1", "string", "Yes or No"),
                ResponseField("Applicant 2", "string", "Yes or No"),
            ]
        ),
    )
    fake_edsl.responses[request.request_id] = None
    fake_edsl.generated_content[request.request_id] = (
        '{"Applicant 1": "Yes", "unexpected": "No"}'
    )
    fake_edsl.exceptions[request.request_id] = ValueError("EDSL validation failed")

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.content is None
    assert result.structured_content is None
    assert result.comment is None
    assert result.error is not None
    assert result.error.type == "ValueError"
    assert result.error.message == "EDSL validation failed"


def test_dictionary_response_value_types_are_mapped_to_edsl(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-types",
        prompt="Return typed values.",
        model_config_id="model-1",
        response_format=DictResponseFormat(
            fields=[
                ResponseField("text", "string", "Text"),
                ResponseField("count", "integer", "Count"),
                ResponseField("score", "number", "Score"),
                ResponseField("selected", "boolean", "Selected"),
            ]
        ),
    )

    EDSLAdapter().render_batch([request], _models())

    assert fake_edsl.questions[0].value_types == ["str", "int", "float", "bool"]


def test_dictionary_response_can_omit_edsl_type_hints(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-without-type-hints",
        prompt="Return a decision.",
        model_config_id="model-1",
        response_format=DictResponseFormat(
            fields=[ResponseField("decision", "string", "Yes or No")],
            include_type_hints=False,
        ),
    )

    EDSLAdapter().render_batch([request], _models())

    assert fake_edsl.questions[0].value_types is None


def test_parallel_token_logprobs_are_normalized(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.raw_model_responses[request.request_id] = {
        "choices": [
            {
                "logprobs": {
                    "tokens": [" answer", " Yes"],
                    "token_logprobs": [-0.4, -0.05],
                }
            }
        ]
    }

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.token_logprobs == [
        TokenLogprob(" answer", -0.4),
        TokenLogprob(" Yes", -0.05),
    ]


def test_malformed_parallel_token_logprobs_are_a_systemic_failure(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.raw_model_responses[request.request_id] = {
        "choices": [
            {
                "logprobs": {
                    "tokens": ["Yes", "No"],
                    "token_logprobs": [-0.1],
                }
            }
        ]
    }

    with pytest.raises(InferenceBatchError, match="cardinality"):
        EDSLAdapter().execute_batch([request], _models())


def test_missing_edsl_result_is_a_systemic_failure(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.omitted_request_ids.add(request.request_id)

    with pytest.raises(InferenceBatchError, match="cardinality"):
        EDSLAdapter().execute_batch([request], _models())


def test_edsl_job_errors_are_wrapped_with_group_context(
    fake_edsl: FakeEDSLRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _requests()[0]
    fake_edsl.prompt_error = RuntimeError("preview broke")

    with pytest.raises(InferenceBatchError, match="preview broke") as preview_error:
        EDSLAdapter().render_batch([request], _models())
    assert isinstance(preview_error.value.__cause__, RuntimeError)

    fake_edsl.prompt_error = None
    fake_edsl.sync_error = RuntimeError("sync broke")
    with pytest.raises(InferenceBatchError, match="sync broke") as sync_error:
        EDSLAdapter().execute_batch([request], _models())
    assert isinstance(sync_error.value.__cause__, RuntimeError)

    fake_edsl.sync_error = None
    fake_edsl.async_error = RuntimeError("async broke")
    cleanup_calls = 0

    async def record_cleanup(
        requests: list[InferenceRequest],
        models: dict[str, ModelConfig],
    ) -> None:
        nonlocal cleanup_calls
        del requests, models
        cleanup_calls += 1

    monkeypatch.setattr(adapter_module, "_close_edsl_async_clients", record_cleanup)

    async def exercise() -> None:
        with pytest.raises(InferenceBatchError, match="async broke") as async_error:
            await EDSLAdapter().execute_batch_async([request], _models())
        assert isinstance(async_error.value.__cause__, RuntimeError)

    asyncio.run(exercise())
    assert cleanup_calls == 1
