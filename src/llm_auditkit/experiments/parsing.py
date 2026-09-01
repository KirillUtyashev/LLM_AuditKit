"""Association and domain parsing of normalized experiment inference results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from llm_auditkit.inference import InferenceResult

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
    *,
    resume_count: int,
) -> list[ExperimentOutputRecord]:
    """Associate and parse one batch, restoring canonical expected-key order."""

    _validate_parse_inputs(results, expected_keys, personas, resume_count)
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
            resume_count=resume_count,
        )
        for key in expected_keys
    ]


def parse_experiment_result(
    result: InferenceResult,
    key: ExperimentJobKey,
    persona: Persona,
    *,
    resume_count: int,
) -> ExperimentOutputRecord:
    """Convert one safely associated normalized result into an output record."""

    _validate_single_parse_inputs(result, key, persona, resume_count)
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
        "persona_description": persona.description,
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
    if result.content is None:
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

    selected_tokens = [
        (token.token.strip(), token.logprob)
        for token in result.token_logprobs
        if token.token.strip() in {"Yes", "No"}
    ][:resume_count]
    if len(selected_tokens) != resume_count:
        raise ExperimentResponseParseError(
            f"expected {resume_count} emitted Yes/No token log probabilities; "
            f"received {len(selected_tokens)}"
        )

    emitted_decisions = [token for token, _ in selected_tokens]
    if emitted_decisions != decisions:
        raise ExperimentResponseParseError(
            "emitted Yes/No tokens do not match the structured applicant decisions"
        )

    return ExperimentOutcome(
        picks=[1 if decision == "Yes" else 0 for decision in decisions],
        logprobs=[logprob for _, logprob in selected_tokens],
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
        raise ExperimentResultAssociationError("personas must be a mapping by persona ID")
    if (
        isinstance(resume_count, bool)
        or not isinstance(resume_count, int)
        or resume_count < 1
    ):
        raise ExperimentResultAssociationError("resume_count must be a positive integer")

    for key in expected_keys:
        persona = personas.get(key.persona_id)
        if not isinstance(persona, Persona) or persona.id != key.persona_id:
            raise ExperimentResultAssociationError(
                f"no matching persona is configured for ID {key.persona_id!r}"
            )


def _validate_single_parse_inputs(
    result: InferenceResult,
    key: ExperimentJobKey,
    persona: Persona,
    resume_count: int,
) -> None:
    if not isinstance(result, InferenceResult):
        raise ExperimentResultAssociationError("result must be an InferenceResult")
    if not isinstance(key, ExperimentJobKey):
        raise ExperimentResultAssociationError("key must be an ExperimentJobKey")
    if not isinstance(persona, Persona) or persona.id != key.persona_id:
        raise ExperimentResultAssociationError("persona does not match the job key")
    if (
        isinstance(resume_count, bool)
        or not isinstance(resume_count, int)
        or resume_count < 1
    ):
        raise ExperimentResultAssociationError("resume_count must be a positive integer")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )
