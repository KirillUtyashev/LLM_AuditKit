"""Association and domain parsing of normalized experiment inference results."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence

from llm_auditkit.inference import InferenceResult, ModelConfig

from .exceptions import (
    ExperimentResponseParseError,
    ExperimentResultAssociationError,
)
from .models import (
    ExperimentJobKey,
    ExperimentOutcome,
    ExperimentOutputRecord,
    Persona,
    build_experiment_request_id,
)


def parse_experiment_batch(
    results: Sequence[InferenceResult],
    expected_keys: Sequence[ExperimentJobKey],
    personas: Mapping[str, Persona],
    models: Mapping[str, ModelConfig],
    *,
    resume_count: int,
) -> list[ExperimentOutputRecord]:
    """Associate and parse one batch, restoring canonical expected-key order."""

    _validate_parse_inputs(results, expected_keys, personas, models, resume_count)
    expected_by_request_id = {
        build_experiment_request_id(key): key for key in expected_keys
    }
    if len(expected_by_request_id) != len(expected_keys):
        raise ExperimentResultAssociationError(
            "expected experiment job keys must be unique"
        )

    results_by_request_id: dict[str, InferenceResult] = {}
    for result in results:
        if result.request_id not in expected_by_request_id:
            raise ExperimentResultAssociationError(
                f"inference results contain unknown request ID {result.request_id!r}"
            )
        if result.request_id in results_by_request_id:
            raise ExperimentResultAssociationError(
                f"inference results contain duplicate request ID {result.request_id!r}"
            )
        results_by_request_id[result.request_id] = result

    missing_request_ids = set(expected_by_request_id).difference(results_by_request_id)
    if missing_request_ids:
        raise ExperimentResultAssociationError(
            "inference result cardinality does not match the planned experiment batch"
        )

    return [
        parse_experiment_result(
            results_by_request_id[build_experiment_request_id(key)],
            key,
            personas[key.persona_id],
            models[key.model_config_id],
            resume_count=resume_count,
        )
        for key in expected_keys
    ]


def parse_experiment_result(
    result: InferenceResult,
    key: ExperimentJobKey,
    persona: Persona,
    model_config: ModelConfig,
    *,
    resume_count: int,
) -> ExperimentOutputRecord:
    """Convert one safely associated normalized result into an output record."""

    _validate_single_parse_inputs(result, key, persona, model_config, resume_count)
    _validate_result_identity(result, key)
    user_prompt = (
        None if result.rendered_prompt is None else result.rendered_prompt.user_prompt
    )
    system_prompt = (
        None if result.rendered_prompt is None else result.rendered_prompt.system_prompt
    )
    record_values = {
        "key": key,
        "request_id": result.request_id,
        "persona_name": persona.name,
        "model": model_config.model,
        "provider": model_config.provider,
        "persona_instruction": persona.instruction,
        "user_prompt": user_prompt,
        "system_prompt": system_prompt,
    }

    if result.error is not None:
        return ExperimentOutputRecord(
            **record_values,
            error_type=result.error.type,
            error_message=result.error.message,
        )

    try:
        outcome = _parse_successful_result(result, resume_count)
    except ExperimentResponseParseError as error:
        return ExperimentOutputRecord(
            **record_values,
            error_type=type(error).__name__,
            error_message=str(error),
        )

    return ExperimentOutputRecord(**record_values, outcome=outcome)


def _parse_successful_result(
    result: InferenceResult,
    resume_count: int,
) -> ExperimentOutcome:
    if result.content is None or not result.content.strip():
        raise ExperimentResponseParseError("successful inference result has no content")
    if result.rendered_prompt is None:
        raise ExperimentResponseParseError(
            "successful inference result has no rendered prompt"
        )

    expected_fields = [
        f"Applicant {position}" for position in range(1, resume_count + 1)
    ]
    if result.structured_content is None:
        raise ExperimentResponseParseError(
            "successful inference result has no structured applicant decisions"
        )
    if list(result.structured_content) != expected_fields:
        raise ExperimentResponseParseError(
            "structured applicant decision fields do not match the configured resumes"
        )

    decisions: list[str] = []
    for field_name in expected_fields:
        decision = result.structured_content[field_name]
        if not isinstance(decision, str) or decision not in {"Yes", "No"}:
            raise ExperimentResponseParseError(
                f"structured field {field_name!r} must be exactly 'Yes' or 'No'; "
                f"received {decision!r}"
            )
        decisions.append(decision)

    decision_logprobs = _decision_logprobs(
        result,
        expected_fields,
        decisions,
    )

    return ExperimentOutcome(
        picks=[1 if decision == "Yes" else 0 for decision in decisions],
        logprobs=decision_logprobs,
        generated_response=result.content,
        comment=result.comment,
    )


def _validate_result_identity(
    result: InferenceResult,
    key: ExperimentJobKey,
) -> None:
    expected_request_id = build_experiment_request_id(key)
    if result.request_id != expected_request_id:
        raise ExperimentResultAssociationError(
            f"result request ID {result.request_id!r} does not match its job key"
        )
    if result.model_config_id != key.model_config_id:
        raise ExperimentResultAssociationError(
            f"result model configuration ID {result.model_config_id!r} does not "
            f"match job key value {key.model_config_id!r}"
        )

    expected_metadata = {
        "experiment_id": key.experiment_id,
        "scenario_id": key.scenario_id,
        "persona_id": key.persona_id,
        "model_config_id": key.model_config_id,
    }
    for field_name, expected_value in expected_metadata.items():
        if result.metadata.get(field_name) != expected_value:
            raise ExperimentResultAssociationError(
                f"result metadata field {field_name!r} does not match its job key"
            )


def _validate_parse_inputs(
    results: Sequence[InferenceResult],
    expected_keys: Sequence[ExperimentJobKey],
    personas: Mapping[str, Persona],
    models: Mapping[str, ModelConfig],
    resume_count: int,
) -> None:
    if not _is_sequence(results) or not all(
        isinstance(result, InferenceResult) for result in results
    ):
        raise ExperimentResultAssociationError(
            "results must be a sequence of InferenceResult values"
        )
    if not _is_sequence(expected_keys) or not all(
        isinstance(key, ExperimentJobKey) for key in expected_keys
    ):
        raise ExperimentResultAssociationError(
            "expected_keys must be a sequence of ExperimentJobKey values"
        )
    if len(results) != len(expected_keys):
        raise ExperimentResultAssociationError(
            "inference result cardinality does not match the planned experiment batch"
        )
    if not isinstance(personas, Mapping):
        raise ExperimentResultAssociationError(
            "personas must be a mapping by persona ID"
        )
    if not isinstance(models, Mapping):
        raise ExperimentResultAssociationError(
            "models must be a mapping by model configuration ID"
        )
    if (
        isinstance(resume_count, bool)
        or not isinstance(resume_count, int)
        or resume_count < 1
    ):
        raise ExperimentResultAssociationError(
            "resume_count must be a positive integer"
        )

    for key in expected_keys:
        persona = personas.get(key.persona_id)
        if not isinstance(persona, Persona) or persona.id != key.persona_id:
            raise ExperimentResultAssociationError(
                f"no matching persona is configured for ID {key.persona_id!r}"
            )
        model = models.get(key.model_config_id)
        if not isinstance(model, ModelConfig) or model.config_id != key.model_config_id:
            raise ExperimentResultAssociationError(
                "no matching model is configured for ID "
                f"{key.model_config_id!r}"
            )


def _validate_single_parse_inputs(
    result: InferenceResult,
    key: ExperimentJobKey,
    persona: Persona,
    model_config: ModelConfig,
    resume_count: int,
) -> None:
    if not isinstance(result, InferenceResult):
        raise ExperimentResultAssociationError("result must be an InferenceResult")
    if not isinstance(key, ExperimentJobKey):
        raise ExperimentResultAssociationError("key must be an ExperimentJobKey")
    if not isinstance(persona, Persona) or persona.id != key.persona_id:
        raise ExperimentResultAssociationError("persona does not match the job key")
    if (
        not isinstance(model_config, ModelConfig)
        or model_config.config_id != key.model_config_id
    ):
        raise ExperimentResultAssociationError(
            "model configuration does not match the job key"
        )
    if (
        isinstance(resume_count, bool)
        or not isinstance(resume_count, int)
        or resume_count < 1
    ):
        raise ExperimentResultAssociationError(
            "resume_count must be a positive integer"
        )


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _decision_logprobs(
    result: InferenceResult,
    expected_fields: list[str],
    decisions: list[str],
) -> list[float]:
    """Associate emitted token probabilities with their structured field values."""

    token_text = "".join(token.token for token in result.token_logprobs)
    candidates = _matching_decision_value_spans(
        token_text,
        expected_fields,
        decisions,
    )
    if len(candidates) != 1:
        raise ExperimentResponseParseError(
            "could not unambiguously associate emitted token log probabilities "
            "with the structured applicant decisions"
        )

    token_spans: list[tuple[int, int]] = []
    cursor = 0
    for token in result.token_logprobs:
        end = cursor + len(token.token)
        token_spans.append((cursor, end))
        cursor = end

    used_tokens: set[int] = set()
    logprobs: list[float] = []
    for field_name in expected_fields:
        value_start, value_end = candidates[0][field_name]
        matching_tokens = [
            index
            for index, (token_start, token_end) in enumerate(token_spans)
            if token_start < value_end and token_end > value_start
        ]
        if not matching_tokens or used_tokens.intersection(matching_tokens):
            raise ExperimentResponseParseError(
                "could not uniquely bind emitted token log probabilities to "
                f"structured field {field_name!r}"
            )
        used_tokens.update(matching_tokens)
        logprobs.append(
            sum(result.token_logprobs[index].logprob for index in matching_tokens)
        )
    return logprobs


def _matching_decision_value_spans(
    content: str,
    expected_fields: list[str],
    decisions: list[str],
) -> list[dict[str, tuple[int, int]]]:
    expected = dict(zip(expected_fields, decisions, strict=True))
    matches: list[dict[str, tuple[int, int]]] = []
    for start, end in _braced_spans(content):
        candidate = content[start:end]
        try:
            expression = ast.parse(candidate, mode="eval").body
            parsed = ast.literal_eval(expression)
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            continue
        if not isinstance(expression, ast.Dict) or parsed != expected:
            continue

        keys: list[str] = []
        spans: dict[str, tuple[int, int]] = {}
        for key_node, value_node in zip(
            expression.keys,
            expression.values,
            strict=True,
        ):
            try:
                key = ast.literal_eval(key_node)
                value = ast.literal_eval(value_node)
            except (ValueError, TypeError):
                break
            if (
                not isinstance(key, str)
                or key not in expected
                or value != expected[key]
            ):
                break
            value_span = _string_value_span(candidate, value_node, value)
            if value_span is None:
                break
            keys.append(key)
            spans[key] = (start + value_span[0], start + value_span[1])
        else:
            if len(keys) == len(expected_fields) and set(keys) == set(expected_fields):
                matches.append(spans)
    return matches


def _string_value_span(
    source: str,
    node: ast.AST,
    value: object,
) -> tuple[int, int] | None:
    if (
        not isinstance(value, str)
        or not hasattr(node, "end_lineno")
        or node.end_lineno is None
        or node.end_col_offset is None
    ):
        return None
    start = _source_offset(source, node.lineno, node.col_offset)
    end = _source_offset(source, node.end_lineno, node.end_col_offset)
    literal = source[start:end]
    first = literal.find(value)
    if first < 0 or literal.find(value, first + 1) >= 0:
        return None
    return start + first, start + first + len(value)


def _source_offset(source: str, line_number: int, byte_column: int) -> int:
    lines = source.splitlines(keepends=True)
    line = lines[line_number - 1]
    prefix = line.encode("utf-8")[:byte_column].decode("utf-8")
    return sum(len(value) for value in lines[: line_number - 1]) + len(prefix)


def _braced_spans(content: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    depth = 0
    quote: str | None = None
    escaped = False

    for index, character in enumerate(content):
        if depth == 0:
            if character == "{":
                start = index
                depth = 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    return spans
