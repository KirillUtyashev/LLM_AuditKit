"""Expected Parrot EDSL implementation of the inference adapter boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edsl import Agent, Model, QuestionFreeText, Scenario, ScenarioList
from edsl.inference_services.registry import GLOBAL_REGISTRY

from .batching import AdapterJobGroup, group_requests_by_model_and_system_prompt
from .exceptions import InferenceBatchError
from .models import (
    InferenceError,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)


_QUESTION_NAME = "response"
_REQUEST_ID_FIELD = "request_id"
_PROMPT_FIELD = "prompt"


class EDSLAdapter:
    """Translate generic inference batches to standard public EDSL jobs."""

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        """Render all compatible EDSL job groups without model inference."""

        rendered_prompts: list[RenderedPrompt] = []
        for group in group_requests_by_model_and_system_prompt(requests, models):
            try:
                job = _build_job(group)
                prompt_dataset = job.prompts()
                rendered_prompts.extend(_normalize_rendered_prompts(group, prompt_dataset))
            except InferenceBatchError:
                raise
            except Exception as error:
                raise _group_failure("render prompts", group, error) from error

        return _order_rendered_prompts(requests, rendered_prompts)

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        """Execute compatible EDSL job groups sequentially with ``run``."""

        normalized_results: list[InferenceResult] = []
        for group in group_requests_by_model_and_system_prompt(requests, models):
            try:
                job = _build_job(group)
                edsl_results = job.run(print_exceptions=False)
                normalized_results.extend(_normalize_results(group, edsl_results))
            except InferenceBatchError:
                raise
            except Exception as error:
                raise _group_failure("execute", group, error) from error

        return _order_results(requests, normalized_results)

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        """Execute compatible EDSL job groups sequentially with ``run_async``."""

        normalized_results: list[InferenceResult] = []
        try:
            for group in group_requests_by_model_and_system_prompt(requests, models):
                try:
                    job = _build_job(group)
                    edsl_results = await job.run_async(print_exceptions=False)
                    normalized_results.extend(_normalize_results(group, edsl_results))
                except InferenceBatchError:
                    raise
                except Exception as error:
                    raise _group_failure(
                        "execute asynchronously",
                        group,
                        error,
                    ) from error

            return _order_results(requests, normalized_results)
        finally:
            await _close_edsl_async_clients(requests, models)


async def _close_edsl_async_clients(
    requests: Sequence[InferenceRequest],
    models: Mapping[str, ModelConfig],
) -> None:
    """Close provider clients that EDSL caches beyond one awaited batch."""

    provider_names = dict.fromkeys(
        models[request.model_config_id].provider for request in requests
    )
    for provider_name in provider_names:
        try:
            service_class = GLOBAL_REGISTRY.get_service_class(provider_name)
        except KeyError:
            continue

        close_async_clients = getattr(service_class, "close_async_clients", None)
        if callable(close_async_clients):
            await close_async_clients()


def _build_job(group: AdapterJobGroup) -> object:
    question = QuestionFreeText(
        question_name=_QUESTION_NAME,
        question_text="{{ prompt }}",
    )
    scenarios = ScenarioList(
        [
            Scenario(
                {
                    _REQUEST_ID_FIELD: request.request_id,
                    _PROMPT_FIELD: request.prompt,
                }
            )
            for request in group.requests
        ]
    )
    agent = (
        Agent()
        if group.system_prompt is None
        else Agent(traits={"persona": group.system_prompt})
    )
    model = Model(
        group.model_config.model,
        service_name=group.model_config.provider,
        **group.model_config.parameters,
    )
    return question.by(scenarios).by(agent).by(model)


def _normalize_rendered_prompts(
    group: AdapterJobGroup,
    prompt_dataset: object,
) -> list[RenderedPrompt]:
    to_dicts = getattr(prompt_dataset, "to_dicts", None)
    if not callable(to_dicts):
        raise InferenceBatchError("EDSL prompt preview did not return a Dataset")

    rows = to_dicts()
    if not _is_sequence(rows):
        raise InferenceBatchError("EDSL prompt Dataset must contain a row sequence")
    if len(rows) != len(group.requests):
        raise InferenceBatchError(
            "EDSL rendered prompt cardinality does not match its scenario group"
        )

    prompts_by_index: dict[int, RenderedPrompt] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise InferenceBatchError("EDSL rendered prompt row must be a mapping")

        scenario_index = row.get("scenario_index")
        if (
            isinstance(scenario_index, bool)
            or not isinstance(scenario_index, int)
            or scenario_index < 0
            or scenario_index >= len(group.requests)
        ):
            raise InferenceBatchError(
                "EDSL rendered prompt row has an invalid scenario index"
            )
        if scenario_index in prompts_by_index:
            raise InferenceBatchError(
                f"EDSL rendered duplicate prompts for scenario index {scenario_index}"
            )

        request = group.requests[scenario_index]
        prompts_by_index[scenario_index] = RenderedPrompt(
            request_id=request.request_id,
            user_prompt=_extract_prompt_text(row.get("user_prompt"), "user"),
            system_prompt=_extract_prompt_text(row.get("system_prompt"), "system"),
        )

    if len(prompts_by_index) != len(group.requests):
        raise InferenceBatchError("EDSL rendered prompts are missing a scenario index")
    return [prompts_by_index[index] for index in range(len(group.requests))]


def _normalize_results(
    group: AdapterJobGroup,
    edsl_results: object,
) -> list[InferenceResult]:
    task_errors = _extract_task_errors(edsl_results)
    try:
        result_items = list(edsl_results)  # type: ignore[arg-type]
    except TypeError as error:
        raise InferenceBatchError("EDSL run did not return an iterable result set") from error

    if len(result_items) != len(group.requests):
        raise InferenceBatchError(
            "EDSL result cardinality does not match its submitted scenario group"
        )

    requests_by_id = {request.request_id: request for request in group.requests}
    results_by_id: dict[str, InferenceResult] = {}

    for result in result_items:
        request_id = _result_request_id(result)
        if request_id not in requests_by_id:
            raise InferenceBatchError(
                f"EDSL result contains unknown request ID {request_id!r}"
            )
        if request_id in results_by_id:
            raise InferenceBatchError(
                f"EDSL returned duplicate request ID {request_id!r}"
            )

        request = requests_by_id[request_id]
        response = _result_response(result, request_id)
        if response is None:
            error = task_errors.get(
                request_id,
                InferenceError(
                    type="EDSLInferenceError",
                    message="EDSL returned no response content",
                ),
            )
        else:
            error = None

        results_by_id[request_id] = InferenceResult(
            request_id=request_id,
            model_config_id=request.model_config_id,
            content=response,
            metadata=dict(request.metadata),
            error=error,
        )

    return [results_by_id[request.request_id] for request in group.requests]


def _result_request_id(result: object) -> str:
    scenario = getattr(result, "scenario", None)
    try:
        request_id = scenario[_REQUEST_ID_FIELD]
    except (KeyError, TypeError) as error:
        raise InferenceBatchError(
            "EDSL result scenario is missing its request ID"
        ) from error
    if not isinstance(request_id, str) or not request_id:
        raise InferenceBatchError("EDSL result request ID must be a non-empty string")
    return request_id


def _result_response(result: object, request_id: str) -> str | None:
    answer = getattr(result, "answer", None)
    if answer is None:
        return None
    if not isinstance(answer, Mapping):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has an invalid answer mapping"
        )

    response = answer.get(_QUESTION_NAME)
    if response is not None and not isinstance(response, str):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has non-string response content"
        )
    return response


def _extract_task_errors(edsl_results: object) -> dict[str, InferenceError]:
    task_history = getattr(edsl_results, "task_history", None)
    exception_collections = getattr(task_history, "exceptions", ())
    if not exception_collections:
        return {}

    errors: dict[str, InferenceError] = {}
    for collection in exception_collections:
        items = getattr(collection, "items", None)
        if not callable(items):
            continue
        for _, entries in items():
            if not _is_sequence(entries):
                continue
            for entry in entries:
                request_id = _exception_request_id(entry)
                if request_id is None:
                    continue
                exception = getattr(entry, "exception", None)
                exception_type = getattr(entry, "exception_type", None)
                if not isinstance(exception_type, str) or not exception_type:
                    exception_type = (
                        type(exception).__name__
                        if exception is not None
                        else "EDSLInferenceError"
                    )
                message = str(exception) if exception is not None else ""
                if not message:
                    message = "EDSL request failed"
                errors[request_id] = InferenceError(
                    type=exception_type,
                    message=message,
                )
    return errors


def _exception_request_id(entry: object) -> str | None:
    invigilator = getattr(entry, "invigilator", None)
    scenario = getattr(invigilator, "scenario", None)
    try:
        request_id = scenario[_REQUEST_ID_FIELD]
    except (KeyError, TypeError):
        return None
    return request_id if isinstance(request_id, str) and request_id else None


def _extract_prompt_text(value: object, prompt_kind: str) -> str:
    if isinstance(value, str):
        return str(value)
    text = getattr(value, "text", None)
    if not isinstance(text, str):
        raise InferenceBatchError(
            f"EDSL rendered {prompt_kind} prompt does not contain string text"
        )
    return text


def _order_rendered_prompts(
    requests: Sequence[InferenceRequest],
    prompts: Sequence[RenderedPrompt],
) -> list[RenderedPrompt]:
    prompts_by_id = {prompt.request_id: prompt for prompt in prompts}
    if len(prompts_by_id) != len(prompts) or set(prompts_by_id) != {
        request.request_id for request in requests
    }:
        raise InferenceBatchError(
            "EDSL prompt groups did not preserve the submitted request set"
        )
    return [prompts_by_id[request.request_id] for request in requests]


def _order_results(
    requests: Sequence[InferenceRequest],
    results: Sequence[InferenceResult],
) -> list[InferenceResult]:
    results_by_id = {result.request_id: result for result in results}
    if len(results_by_id) != len(results) or set(results_by_id) != {
        request.request_id for request in requests
    }:
        raise InferenceBatchError(
            "EDSL job groups did not preserve the submitted request set"
        )
    return [results_by_id[request.request_id] for request in requests]


def _group_failure(
    action: str,
    group: AdapterJobGroup,
    error: Exception,
) -> InferenceBatchError:
    return InferenceBatchError(
        f"EDSL failed to {action} job group for model configuration "
        f"{group.model_config.config_id!r}: {type(error).__name__}: {error}"
    )


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )
