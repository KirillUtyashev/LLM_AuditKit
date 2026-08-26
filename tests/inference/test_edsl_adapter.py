"""Offline tests for the Expected Parrot EDSL adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceAdapter,
    InferenceBatchError,
    InferenceRequest,
    ModelConfig,
)
from llm_auditkit.inference import edsl_adapter as adapter_module


@dataclass
class FakeEDSLRuntime:
    responses: dict[str, object] = field(default_factory=dict)
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
        def __init__(self, scenario: FakeScenario, answer: object) -> None:
            self.scenario = scenario
            self.answer = answer

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
            question: object,
            scenarios: FakeScenarioList,
        ) -> None:
            self.question = question
            self.scenarios = scenarios
            self.agent: FakeAgent | None = None
            self.model: FakeModel | None = None
            runtime.jobs.append(self)

        def by(self, value: object) -> FakeJob:
            if isinstance(value, FakeAgent):
                self.agent = value
            elif isinstance(value, FakeModel):
                self.model = value
            else:
                raise AssertionError(f"unexpected EDSL job binding: {value!r}")
            return self

        def prompts(self) -> FakeDataset:
            if runtime.prompt_error is not None:
                raise runtime.prompt_error
            assert self.agent is not None
            assert self.model is not None
            runtime.events.append(("prompts", self.model.model_name, {}))
            system_prompt = (
                ""
                if self.agent.traits is None
                else f"EDSL system:{self.agent.traits['persona']}"
            )
            rows = [
                {
                    "scenario_index": index,
                    "user_prompt": FakePrompt(
                        f"EDSL user:{scenario['prompt']}"
                    ),
                    "system_prompt": FakePrompt(system_prompt),
                }
                for index, scenario in enumerate(self.scenarios)
            ]
            return FakeDataset(list(reversed(rows)))

        def run(self, **kwargs: object) -> FakeResults:
            if runtime.sync_error is not None:
                raise runtime.sync_error
            assert self.model is not None
            runtime.events.append(("run", self.model.model_name, kwargs))
            return self._results()

        async def run_async(self, **kwargs: object) -> FakeResults:
            if runtime.async_error is not None:
                raise runtime.async_error
            assert self.model is not None
            runtime.events.append(("run_async", self.model.model_name, kwargs))
            return self._results()

        def _results(self) -> FakeResults:
            result_items = [
                FakeResult(
                    scenario,
                    {
                        "response": runtime.responses.get(
                            scenario["request_id"],
                            f"answer:{scenario['request_id']}",
                        )
                    },
                )
                for scenario in reversed(self.scenarios)
                if scenario["request_id"] not in runtime.omitted_request_ids
            ]
            return FakeResults(result_items, list(self.scenarios))

    class FakeQuestionFreeText:
        def __init__(self, *, question_name: str, question_text: str) -> None:
            self.question_name = question_name
            self.question_text = question_text
            runtime.questions.append(self)

        def by(self, scenarios: FakeScenarioList) -> FakeJob:
            return FakeJob(self, scenarios)

    monkeypatch.setattr(adapter_module, "Agent", FakeAgent)
    monkeypatch.setattr(adapter_module, "Model", FakeModel)
    monkeypatch.setattr(adapter_module, "QuestionFreeText", FakeQuestionFreeText)
    monkeypatch.setattr(adapter_module, "Scenario", FakeScenario)
    monkeypatch.setattr(adapter_module, "ScenarioList", FakeScenarioList)
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
            system_prompt="persona-a",
            metadata={"position": 1},
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
            system_prompt="persona-a",
            metadata={"position": 3},
        ),
    ]


def test_edsl_adapter_implements_the_generic_protocol() -> None:
    assert isinstance(EDSLAdapter(), InferenceAdapter)


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
        "EDSL system:persona-a",
        "",
        "EDSL system:persona-a",
    ]
    assert all(type(prompt.user_prompt) is str for prompt in rendered)
    assert all(type(prompt.system_prompt) is str for prompt in rendered)
    assert fake_edsl.events == [
        ("prompts", "first-model", {}),
        ("prompts", "second-model", {}),
    ]


def test_job_construction_uses_standard_edsl_agent_model_and_scenarios(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = _requests()

    results = EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 2
    assert [scenario["request_id"] for scenario in fake_edsl.jobs[0].scenarios] == [
        "request-1",
        "request-3",
    ]
    assert all(set(scenario) == {"request_id", "prompt"} for job in fake_edsl.jobs for scenario in job.scenarios)
    assert fake_edsl.agents[0].traits == {"persona": "persona-a"}
    assert fake_edsl.agents[0].kwargs == {}
    assert fake_edsl.agents[1].traits is None
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


def test_async_execution_uses_only_sequential_run_async_calls(
    fake_edsl: FakeEDSLRuntime,
) -> None:
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


def test_none_and_empty_system_prompts_create_distinct_standard_agents(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    requests = [
        InferenceRequest("request-1", "Prompt one", "model-1", None),
        InferenceRequest("request-2", "Prompt two", "model-1", ""),
    ]

    EDSLAdapter().execute_batch(requests, _models())

    assert len(fake_edsl.jobs) == 2
    assert fake_edsl.agents[0].traits is None
    assert fake_edsl.agents[1].traits == {"persona": ""}


def test_non_string_edsl_response_is_a_systemic_failure(
    fake_edsl: FakeEDSLRuntime,
) -> None:
    request = _requests()[0]
    fake_edsl.responses[request.request_id] = {"unexpected": "object"}

    with pytest.raises(InferenceBatchError, match="non-string"):
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

    async def exercise() -> None:
        with pytest.raises(InferenceBatchError, match="async broke") as async_error:
            await EDSLAdapter().execute_batch_async([request], _models())
        assert isinstance(async_error.value.__cause__, RuntimeError)

    asyncio.run(exercise())
