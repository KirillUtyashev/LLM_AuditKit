"""Offline tests for the Expected Parrot EDSL adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import product

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
from llm_auditkit.inference.batching import AdapterJobGroup


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
            traits_presentation_template: str | None = None,
            **kwargs: object,
        ) -> None:
            self.traits = traits
            self.traits_presentation_template = traits_presentation_template
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
        def __init__(self, interview: FakeInterview) -> None:
            self.scenario = interview.scenario
            self.agent = interview.agent

    class FakeExceptionEntry:
        def __init__(self, interview: FakeInterview, exception: Exception) -> None:
            self.invigilator = FakeInvigilator(interview)
            self.exception = exception
            self.exception_type = type(exception).__name__

    class FakeTaskHistory:
        def __init__(self, interviews: list[FakeInterview]) -> None:
            entries = [
                FakeExceptionEntry(
                    interview,
                    runtime.exceptions[
                        interview.scenario[adapter_module._REQUEST_ID_FIELD]
                    ],
                )
                for interview in interviews
                if interview.scenario[adapter_module._REQUEST_ID_FIELD]
                in runtime.exceptions
            ]
            self.exceptions = [{"response": entries}] if entries else []

    class FakeResult:
        def __init__(
            self,
            scenario: FakeScenario,
            answer: object,
            data: dict[str, object],
            agent: FakeAgent,
        ) -> None:
            self.scenario = scenario
            self.answer = answer
            self.data = data
            self.agent = agent

    class FakeResults(list[FakeResult]):
        def __init__(
            self,
            results: list[FakeResult],
            scenarios: list[FakeScenario],
        ) -> None:
            super().__init__(results)
            self.task_history = FakeTaskHistory(scenarios)

    class FakeJob:
        def __init__(
            self,
            *,
            survey: FakeSurvey,
            agents: FakeAgentList,
            scenarios: FakeScenarioList,
            models: list[FakeModel],
        ) -> None:
            self.agents = agents
            self.scenarios = scenarios
            self.models = models
            self.interviews = [
                FakeInterview(
                    agent=agent,
                    survey=survey,
                    scenario=scenario,
                    model=model,
                )
                for agent, scenario, model in product(agents, scenarios, models)
            ]
            self.question = survey.questions[0]
            self.model = models[0]
            runtime.jobs.append(self)

        @staticmethod
        def _system_prompt(agent: FakeAgent) -> str:
            parts = []
            if "instruction" in agent.kwargs:
                parts.append(f"instruction:{agent.kwargs['instruction']}")
            persona = agent.traits.get("persona")
            if persona is not None:
                parts.append(f"persona:{persona}")
            return "" if not parts else f"EDSL system:{'|'.join(parts)}"

        def prompts(self) -> FakeDataset:
            if runtime.prompt_error is not None:
                raise runtime.prompt_error
            runtime.events.append(("prompts", self.model.model_name, {}))
            rows = [
                {
                    "agent_index": self.agents.index(interview.agent),
                    "scenario_index": self.scenarios.index(interview.scenario),
                    "user_prompt": FakePrompt(
                        "EDSL user:"
                        f"{interview.scenario[adapter_module._PROMPT_FIELD]}"
                    ),
                    "system_prompt": FakePrompt(
                        self._system_prompt(interview.agent)
                    ),
                }
                for interview in self.interviews
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
                request_id = interview.scenario[adapter_module._REQUEST_ID_FIELD]
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
                            "EDSL user:"
                            f"{interview.scenario[adapter_module._PROMPT_FIELD]}"
                        ),
                        "response_system_prompt": FakePrompt(
                            self._system_prompt(interview.agent)
                        ),
                    },
                }
                result_items.append(
                    FakeResult(
                        scenario,
                        {"response": response},
                        data,
                        interview.agent,
                    )
                )
            return FakeResults(
                result_items,
                self.interviews,
            )

    class FakeJobs:
        def __new__(
            cls,
            *,
            survey: FakeSurvey,
            agents: FakeAgentList,
            scenarios: FakeScenarioList,
            models: list[FakeModel],
        ) -> FakeJob:
            return FakeJob(
                survey=survey,
                agents=agents,
                scenarios=scenarios,
                models=models,
            )

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
    monkeypatch.setattr(adapter_module, "Jobs", FakeJobs)
    monkeypatch.setattr(adapter_module, "Model", FakeModel)
    monkeypatch.setattr(adapter_module, "QuestionFreeText", FakeQuestionFreeText)
    monkeypatch.setattr(adapter_module, "_RecoverableQuestionDict", FakeQuestionDict)
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


def test_real_edsl_job_has_one_interview_per_request() -> None:
    requests = tuple(
        InferenceRequest(
            request_id=f"request-{index}",
            prompt=f"Prompt {index}",
            model_config_id="model",
            system_prompt="Shared instruction",
            persona="Shared persona",
        )
        for index in range(5)
    )
    group = AdapterJobGroup(
        model_config=ModelConfig("model", "test", "test"),
        response_format=None,
        requests=requests,
    )

    job = adapter_module._build_job(group)

    assert len(job.agents) == 1
    assert len(job.scenarios) == 5
    assert len(job.models) == 1
    assert job.num_interviews == 5
    assert len(job.prompts().to_dicts()) == 5


def test_five_compatible_requests_execute_as_exactly_five_interviews_sync_and_async(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = [
        InferenceRequest(
            request_id=f"request-{index}",
            prompt=f"Prompt {index}",
            model_config_id="model-1",
            system_prompt="Shared instruction",
            persona="Shared persona",
        )
        for index in range(5)
    ]

    sync_results = EDSLAdapter().execute_batch(requests, _models())
    async_results = asyncio.run(
        EDSLAdapter().execute_batch_async(requests, _models())
    )

    assert len(fake_edsl.jobs) == 2
    assert all(len(job.agents) == 1 for job in fake_edsl.jobs)
    assert all(len(job.scenarios) == 5 for job in fake_edsl.jobs)
    assert all(len(job.interviews) == 5 for job in fake_edsl.jobs)
    expected_request_ids = [f"request-{index}" for index in range(5)]
    assert [result.request_id for result in sync_results] == expected_request_ids
    assert [result.request_id for result in async_results] == expected_request_ids


def test_real_edsl_job_preserves_literal_request_ids_and_prompts() -> None:
    request = InferenceRequest(
        request_id="id:{{name}}",
        prompt='Nested JSON: {"outer":{"inner":1}}',
        model_config_id="model",
        system_prompt="Keep the request literal.",
    )
    group = AdapterJobGroup(
        model_config=ModelConfig("model", "test", "test"),
        response_format=None,
        requests=(request,),
    )

    job = adapter_module._build_job(group)
    interview = job.interviews()[0]
    prompt_row = job.prompts().to_dicts()[0]

    assert interview.scenario[adapter_module._REQUEST_ID_FIELD] == request.request_id
    assert interview.scenario[adapter_module._PROMPT_FIELD] == request.prompt
    assert request.prompt in prompt_row["user_prompt"].text


def test_real_edsl_job_preserves_system_prompt_without_persona() -> None:
    request = InferenceRequest(
        request_id="request-1",
        prompt="Evaluate this request.",
        model_config_id="model",
        system_prompt="Follow this system instruction exactly.",
    )
    group = AdapterJobGroup(
        model_config=ModelConfig("model", "test", "test"),
        response_format=None,
        requests=(request,),
    )

    prompt_row = adapter_module._build_job(group).prompts().to_dicts()[0]

    assert prompt_row["system_prompt"].text == request.system_prompt
    assert adapter_module._AGENT_MARKER_FIELD not in prompt_row["system_prompt"].text


def test_recoverable_question_survives_edsl_serialization_and_validation() -> None:
    from edsl.questions.question_base import QuestionBase

    generated_content = """```json
{
  "Applicant 1": "Yes",
  "Applicant 2": "No"
}
```
Applicant 1 has more relevant experience."""
    question = adapter_module._RecoverableQuestionDict(
        question_name="response",
        question_text="Choose applicants.",
        answer_keys=["Applicant 1", "Applicant 2"],
        value_types=None,
        value_descriptions=["Yes or No", "Yes or No"],
        include_comment=True,
    )

    restored = QuestionBase.from_dict(question.to_dict())
    validated = restored._validate_answer(
        {
            "answer": "```json",
            "comment": generated_content.split("\n", 1)[1],
            "generated_tokens": generated_content,
        }
    )

    assert isinstance(restored, adapter_module._RecoverableQuestionDict)
    assert validated["answer"] == {
        "Applicant 1": "Yes",
        "Applicant 2": "No",
    }
    assert validated["comment"] == "Applicant 1 has more relevant experience."
    assert validated["generated_tokens"] == generated_content


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
        ("prompts", "first-model", {}),
    ]


def test_job_construction_uses_one_shared_agent_and_request_scenarios(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = _requests()

    results = EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 3
    assert [scenario[adapter_module._REQUEST_ID_FIELD] for scenario in fake_edsl.jobs[0].scenarios] == [
        "request-1"
    ]
    assert [scenario[adapter_module._REQUEST_ID_FIELD] for scenario in fake_edsl.jobs[1].scenarios] == [
        "request-2"
    ]
    assert [scenario[adapter_module._REQUEST_ID_FIELD] for scenario in fake_edsl.jobs[2].scenarios] == [
        "request-3"
    ]
    assert [
        interview.scenario[adapter_module._REQUEST_ID_FIELD]
        for interview in fake_edsl.jobs[0].interviews
    ] == ["request-1"]
    assert [
        interview.scenario[adapter_module._PROMPT_FIELD]
        for interview in fake_edsl.jobs[0].interviews
    ] == ["First prompt"]
    assert all(
        adapter_module._REQUEST_ID_FIELD not in interview.agent.traits
        and adapter_module._PROMPT_FIELD not in interview.agent.traits
        for interview in fake_edsl.jobs[0].interviews
    )
    assert fake_edsl.jobs[0].agents[0].traits["persona"] == "persona-a"
    assert fake_edsl.agents[0].kwargs == {"instruction": "instruction-a"}
    assert fake_edsl.agents[1].kwargs == {}
    assert "persona" not in fake_edsl.agents[1].traits
    assert fake_edsl.agents[2].kwargs == {"instruction": "instruction-a"}
    assert fake_edsl.agents[2].traits["persona"] == "persona-c"
    assert fake_edsl.models[0].model_name == "first-model"
    assert fake_edsl.models[0].service_name == "provider-1"
    assert fake_edsl.models[0].parameters == {"temperature": 0.2}
    assert fake_edsl.questions[0].question_name == "response"
    assert (
        fake_edsl.questions[0].question_text
        == "{{ llm_auditkit_prompt }}"
    )
    assert fake_edsl.events == [
        ("run", "first-model", {"print_exceptions": False}),
        ("run", "second-model", {"print_exceptions": False}),
        ("run", "first-model", {"print_exceptions": False}),
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
        ("run_async", "first-model", {"print_exceptions": False}),
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


def test_none_and_empty_system_prompts_preserve_edsl_instruction_behavior(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = [
        InferenceRequest("request-1", "Prompt one", "model-1", None),
        InferenceRequest("request-2", "Prompt two", "model-1", ""),
    ]

    EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 2
    assert fake_edsl.agents[0].traits == {
        adapter_module._AGENT_MARKER_FIELD: True
    }
    assert fake_edsl.agents[0].kwargs == {}
    assert fake_edsl.agents[1].traits == {
        adapter_module._AGENT_MARKER_FIELD: True
    }
    assert fake_edsl.agents[1].kwargs == {"instruction": ""}
    assert all(
        agent.traits_presentation_template == "" for agent in fake_edsl.agents
    )


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


def test_dictionary_recovery_rejects_conflicting_schema_matching_answers(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = InferenceRequest(
        request_id="structured-recovery-conflict",
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
        '{"Applicant 1":"Yes","Applicant 2":"No"}\n'
        'Correction: {"Applicant 1":"No","Applicant 2":"Yes"}'
    )
    fake_edsl.exceptions[request.request_id] = ValueError("ambiguous response")

    result = EDSLAdapter().execute_batch([request], _models())[0]

    assert result.content is None
    assert result.structured_content is None
    assert result.error is not None
    assert result.error.message == "ambiguous response"


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
