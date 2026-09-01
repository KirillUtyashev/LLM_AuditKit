"""Expected Parrot EDSL implementation of the inference adapter boundary."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence

from edsl import Agent, Model, QuestionDict, QuestionFreeText, Scenario, ScenarioList
from edsl.inference_services.registry import GLOBAL_REGISTRY

from .batching import AdapterJobGroup, group_requests_by_compatibility
from .exceptions import InferenceBatchError
from .models import (
    InferenceError,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
    TokenLogprob,
)


_QUESTION_NAME = "response"
_REQUEST_ID_FIELD = "request_id"
_PROMPT_FIELD = "prompt"
_LOGGER = logging.getLogger(__name__)
_VALUE_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}


class EDSLAdapter:
    """Translate generic inference batches to standard public EDSL jobs."""

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        """Render all compatible EDSL job groups without model inference."""

        rendered_prompts: list[RenderedPrompt] = []
        for group in group_requests_by_compatibility(requests, models):
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
        for group in group_requests_by_compatibility(requests, models):
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
            for group in group_requests_by_compatibility(requests, models):
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
            try:
                await _close_edsl_async_clients(requests, models)
            except Exception:
                _LOGGER.warning(
                    "EDSL async client cleanup failed after batch execution",
                    exc_info=True,
                )


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
    question = _build_question(group)
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


def _build_question(group: AdapterJobGroup) -> object:
    if group.response_format is None:
        return QuestionFreeText(
            question_name=_QUESTION_NAME,
            question_text="{{ prompt }}",
        )

    return QuestionDict(
        question_name=_QUESTION_NAME,
        question_text="{{ prompt }}",
        answer_keys=[field.name for field in group.response_format.fields],
        value_types=[
            _VALUE_TYPE_MAP[field.value_type]
            for field in group.response_format.fields
        ],
        value_descriptions=[
            field.description for field in group.response_format.fields
        ],
        include_comment=group.response_format.include_comment,
    )


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
        rendered_prompt = _result_rendered_prompt(result, request_id)
        content, structured_content = _result_response(result, request)
        if content is None:
            error = task_errors.get(
                request_id,
                InferenceError(
                    type="EDSLInferenceError",
                    message="EDSL returned no response content",
                ),
            )
            comment = None
            token_logprobs: list[TokenLogprob] = []
        else:
            error = None
            comment = (
                _result_comment(result, request_id)
                if request.response_format is not None
                else None
            )
            token_logprobs = _result_token_logprobs(result, request_id)

        results_by_id[request_id] = InferenceResult(
            request_id=request_id,
            model_config_id=request.model_config_id,
            content=content,
            metadata=dict(request.metadata),
            error=error,
            structured_content=structured_content,
            comment=comment,
            token_logprobs=token_logprobs,
            rendered_prompt=rendered_prompt,
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


def _result_response(
    result: object,
    request: InferenceRequest,
) -> tuple[str | None, dict[str, object] | None]:
    answer = getattr(result, "answer", None)
    if answer is None:
        return None, None
    if not isinstance(answer, Mapping):
        raise InferenceBatchError(
            f"EDSL result for request {request.request_id!r} has an invalid answer "
            "mapping"
        )

    response = answer.get(_QUESTION_NAME)
    if response is None:
        return None, None
    if request.response_format is None:
        if not isinstance(response, str):
            raise InferenceBatchError(
                f"EDSL result for request {request.request_id!r} has non-string "
                "response content"
            )
        return response, None
    if not isinstance(response, Mapping):
        raise InferenceBatchError(
            f"EDSL result for request {request.request_id!r} has a non-dictionary "
            "structured response"
        )

    generated_content = _result_generated_content(result, request.request_id)
    if generated_content is None:
        raise InferenceBatchError(
            f"EDSL structured result for request {request.request_id!r} is missing "
            "generated response content"
        )
    return generated_content, dict(response)


def _result_generated_content(result: object, request_id: str) -> str | None:
    generated_tokens = _result_data_section(result, "generated_tokens", request_id)
    if generated_tokens is None:
        return None
    content = generated_tokens.get(f"{_QUESTION_NAME}_generated_tokens")
    if content is None:
        return None
    if not isinstance(content, str):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has non-string generated "
            "response content"
        )
    return content


def _result_comment(result: object, request_id: str) -> str | None:
    comments = _result_data_section(result, "comments_dict", request_id)
    if comments is None:
        return None
    comment = comments.get(f"{_QUESTION_NAME}_comment")
    if comment is None:
        return None
    if not isinstance(comment, str):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has a non-string comment"
        )
    return comment


def _result_rendered_prompt(
    result: object,
    request_id: str,
) -> RenderedPrompt | None:
    prompts = _result_data_section(result, "prompt", request_id)
    if prompts is None:
        return None
    user_key = f"{_QUESTION_NAME}_user_prompt"
    system_key = f"{_QUESTION_NAME}_system_prompt"
    if user_key not in prompts and system_key not in prompts:
        return None
    if user_key not in prompts:
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} is missing its rendered user prompt"
        )

    system_value = prompts.get(system_key)
    return RenderedPrompt(
        request_id=request_id,
        user_prompt=_extract_prompt_text(prompts[user_key], "user"),
        system_prompt=(
            None
            if system_value is None
            else _extract_prompt_text(system_value, "system")
        ),
    )


def _result_token_logprobs(
    result: object,
    request_id: str,
) -> list[TokenLogprob]:
    raw_responses = _result_data_section(result, "raw_model_response", request_id)
    if raw_responses is None:
        return []
    raw_response = raw_responses.get(f"{_QUESTION_NAME}_raw_model_response")
    if raw_response is None:
        return []
    return _normalize_token_logprobs(raw_response, request_id)


def _normalize_token_logprobs(
    raw_response: object,
    request_id: str,
) -> list[TokenLogprob]:
    response_mapping = _as_mapping(raw_response)
    if response_mapping is None:
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has an invalid raw model response"
        )

    choices = response_mapping.get("choices")
    if choices is None:
        return []
    if not _is_sequence(choices) or not choices:
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid model choices"
        )
    first_choice = _as_mapping(choices[0])
    if first_choice is None:
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has an invalid model choice"
        )
    logprobs = first_choice.get("logprobs")
    if logprobs is None:
        return []
    logprobs_mapping = _as_mapping(logprobs)
    if logprobs_mapping is None:
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid token logprobs"
        )

    content = logprobs_mapping.get("content")
    if content is not None:
        return _normalize_content_token_logprobs(content, request_id)
    return _normalize_parallel_token_logprobs(logprobs_mapping, request_id)


def _normalize_content_token_logprobs(
    content: object,
    request_id: str,
) -> list[TokenLogprob]:
    if not _is_sequence(content):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid token logprob content"
        )

    normalized: list[TokenLogprob] = []
    for index, entry in enumerate(content):
        entry_mapping = _as_mapping(entry)
        if entry_mapping is None:
            raise InferenceBatchError(
                f"EDSL result for request {request_id!r} token logprob at position "
                f"{index} is invalid"
            )
        token = entry_mapping.get("token")
        logprob = entry_mapping.get("logprob")
        if logprob is None:
            continue
        normalized.append(
            _build_token_logprob(token, logprob, request_id=request_id, index=index)
        )
    return normalized


def _normalize_parallel_token_logprobs(
    logprobs: Mapping[object, object],
    request_id: str,
) -> list[TokenLogprob]:
    tokens = logprobs.get("tokens")
    values = logprobs.get("token_logprobs")
    if tokens is None and values is None:
        return []
    if not _is_sequence(tokens) or not _is_sequence(values):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid parallel token "
            "logprobs"
        )
    if len(tokens) != len(values):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} token and logprob cardinality "
            "does not match"
        )

    return [
        _build_token_logprob(token, value, request_id=request_id, index=index)
        for index, (token, value) in enumerate(zip(tokens, values))
        if value is not None
    ]


def _build_token_logprob(
    token: object,
    logprob: object,
    *,
    request_id: str,
    index: int,
) -> TokenLogprob:
    if not isinstance(token, str):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} token logprob at position "
            f"{index} has a non-string token"
        )
    if (
        isinstance(logprob, bool)
        or not isinstance(logprob, (int, float))
        or not math.isfinite(logprob)
    ):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} token logprob at position "
            f"{index} is not a finite number"
        )
    return TokenLogprob(token=token, logprob=float(logprob))


def _as_mapping(value: object) -> Mapping[object, object] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        return None
    dumped = model_dump()
    return dumped if isinstance(dumped, Mapping) else None


def _result_data_section(
    result: object,
    section_name: str,
    request_id: str,
) -> Mapping[object, object] | None:
    data = getattr(result, "data", None)
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid result data"
        )
    section = data.get(section_name)
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise InferenceBatchError(
            f"EDSL result for request {request_id!r} has invalid {section_name} data"
        )
    return section


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
