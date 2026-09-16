"""Tests for normalized experiment response association and parsing."""

from __future__ import annotations

import pytest

from llm_auditkit.experiments import (
    ExperimentJobKey,
    ExperimentResultAssociationError,
    Persona,
    build_experiment_request_id,
)
from llm_auditkit.experiments.parsing import (
    parse_experiment_batch,
    parse_experiment_result,
)
from llm_auditkit.inference import (
    InferenceError,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
    TokenLogprob,
)


def _key(
    scenario_id: str = "scenario-1",
    persona_id: str = "manager",
) -> ExperimentJobKey:
    return ExperimentJobKey(
        experiment_id="experiment-1",
        scenario_id=scenario_id,
        persona_id=persona_id,
        model_config_id="model-1",
    )


def _persona(persona_id: str = "manager") -> Persona:
    return Persona(
        persona_id,
        "Manager",
        "You are a hiring manager in {city}.",
        "Evaluate applicants.",
    )


def _model() -> ModelConfig:
    return ModelConfig("model-1", "openai", "gpt-test", {"logprobs": True})


def _result(
    key: ExperimentJobKey | None = None,
    **changes: object,
) -> InferenceResult:
    key = _key() if key is None else key
    values: dict[str, object] = {
        "request_id": build_experiment_request_id(key),
        "model_config_id": key.model_config_id,
        "content": '{"Applicant 1":"Yes","Applicant 2":"No"}',
        "metadata": {
            "experiment_id": key.experiment_id,
            "scenario_id": key.scenario_id,
            "persona_id": key.persona_id,
            "model_config_id": key.model_config_id,
        },
        "structured_content": {"Applicant 1": "Yes", "Applicant 2": "No"},
        "comment": "Interview the first applicant.",
        "token_logprobs": [
            TokenLogprob('{"Applicant 1":"', -0.01),
            TokenLogprob("Yes", -0.2),
            TokenLogprob('","Applicant 2":"', -0.01),
            TokenLogprob("No", -0.4),
            TokenLogprob('"}', -0.01),
        ],
        "rendered_prompt": RenderedPrompt(
            request_id=build_experiment_request_id(key),
            user_prompt="Rendered user prompt",
            system_prompt="Rendered system prompt",
        ),
    }
    values.update(changes)
    return InferenceResult(**values)  # type: ignore[arg-type]


def test_successful_result_parses_decisions_logprobs_and_prompts() -> None:
    record = parse_experiment_result(
        _result(),
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert record.is_successful
    assert record.outcome is not None
    assert record.outcome.picks == [1, 0]
    assert record.outcome.logprobs == [-0.2, -0.4]
    assert record.outcome.generated_response.startswith("{")
    assert record.outcome.comment == "Interview the first applicant."
    assert record.user_prompt == "Rendered user prompt"
    assert record.system_prompt == "Rendered system prompt"
    assert record.persona_name == "Manager"
    assert record.model == "gpt-test"
    assert record.provider == "openai"


def test_batch_associates_by_request_id_and_restores_expected_order() -> None:
    keys = [_key("scenario-1"), _key("scenario-2")]

    records = parse_experiment_batch(
        [_result(keys[1]), _result(keys[0])],
        keys,
        {"manager": _persona()},
        {"model-1": _model()},
        resume_count=2,
    )

    assert [record.key for record in records] == keys


def test_terminal_inference_error_becomes_an_incomplete_record() -> None:
    result = _result(
        content=None,
        structured_content=None,
        comment=None,
        token_logprobs=[],
        rendered_prompt=None,
        error=InferenceError("ProviderError", "request failed after retries"),
    )

    record = parse_experiment_result(
        result,
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert not record.is_successful
    assert record.outcome is None
    assert record.error_type == "ProviderError"
    assert record.error_message == "request failed after retries"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"structured_content": None}, "no structured"),
        ({"content": "  "}, "no content"),
        (
            {"structured_content": {"Applicant 1": "Yes", "Wrong": "No"}},
            "do not match",
        ),
        (
            {
                "structured_content": {
                    "Applicant 1": "Maybe",
                    "Applicant 2": "No",
                }
            },
            "exactly",
        ),
        (
            {
                "structured_content": {
                    "Applicant 1": ["Yes"],
                    "Applicant 2": "No",
                }
            },
            "exactly",
        ),
        ({"rendered_prompt": None}, "no rendered prompt"),
    ],
)
def test_malformed_domain_response_becomes_a_parse_error_record(
    changes: dict[str, object],
    message: str,
) -> None:
    record = parse_experiment_result(
        _result(**changes),
            _key(),
            _persona(),
            _model(),
            resume_count=2,
    )

    assert not record.is_successful
    assert record.error_type == "ExperimentResponseParseError"
    assert message in (record.error_message or "")


def test_missing_decision_logprobs_becomes_a_parse_error_record() -> None:
    record = parse_experiment_result(
        _result(token_logprobs=[TokenLogprob("Yes", -0.2)]),
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert record.error_type == "ExperimentResponseParseError"
    assert "unambiguously" in (record.error_message or "")


def test_mismatched_decision_tokens_becomes_a_parse_error_record() -> None:
    record = parse_experiment_result(
        _result(
            token_logprobs=[
                TokenLogprob('{"Applicant 1":"', -0.01),
                TokenLogprob("No", -0.2),
                TokenLogprob('","Applicant 2":"', -0.01),
                TokenLogprob("No", -0.4),
                TokenLogprob('"}', -0.01),
            ]
        ),
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert record.error_type == "ExperimentResponseParseError"
    assert "unambiguously" in (record.error_message or "")


@pytest.mark.parametrize(
    "result",
    [
        _result(request_id="unknown-request"),
        _result(model_config_id="other-model"),
        _result(metadata={}),
    ],
)
def test_identity_mismatch_is_a_systemic_error(result: InferenceResult) -> None:
    with pytest.raises(ExperimentResultAssociationError):
        parse_experiment_result(
            result,
            _key(),
            _persona(),
            _model(),
            resume_count=2,
        )


def test_duplicate_and_missing_batch_results_are_systemic_errors() -> None:
    keys = [_key("scenario-1"), _key("scenario-2")]

    with pytest.raises(ExperimentResultAssociationError, match="duplicate"):
        parse_experiment_batch(
            [_result(keys[0]), _result(keys[0])],
            keys,
            {"manager": _persona()},
            {"model-1": _model()},
            resume_count=2,
        )

    with pytest.raises(ExperimentResultAssociationError, match="cardinality"):
        parse_experiment_batch(
            [_result(keys[0])],
            keys,
            {"manager": _persona()},
            {"model-1": _model()},
            resume_count=2,
        )


def test_parser_supports_arbitrary_configured_resume_count() -> None:
    result = _result(
        content='{"Applicant 1":"No"}',
        structured_content={"Applicant 1": "No"},
        token_logprobs=[
            TokenLogprob('{"Applicant 1":"', -0.01),
            TokenLogprob("No", -0.7),
            TokenLogprob('"}', -0.01),
        ],
    )

    record = parse_experiment_result(
        result,
        _key(),
        _persona(),
        _model(),
        resume_count=1,
    )

    assert record.outcome is not None
    assert record.outcome.picks == [0]
    assert record.outcome.logprobs == [-0.7]


def test_logprobs_are_bound_to_fields_not_unrelated_decision_words() -> None:
    result = _result(
        token_logprobs=[
            TokenLogprob("Yes, preliminary note. ", -9.0),
            TokenLogprob('{"Applicant 2":"', -0.01),
            TokenLogprob("No", -0.4),
            TokenLogprob('","Applicant 1":"', -0.01),
            TokenLogprob("Yes", -0.2),
            TokenLogprob('"} No afterthought', -8.0),
        ]
    )

    record = parse_experiment_result(
        result,
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert record.outcome is not None
    assert record.outcome.logprobs == [-0.2, -0.4]


def test_multitoken_decision_logprob_is_summed_for_its_field() -> None:
    result = _result(
        token_logprobs=[
            TokenLogprob('{"Applicant 1":"', -0.01),
            TokenLogprob("Y", -0.1),
            TokenLogprob("es", -0.2),
            TokenLogprob('","Applicant 2":"', -0.01),
            TokenLogprob("No", -0.4),
            TokenLogprob('"}', -0.01),
        ]
    )

    record = parse_experiment_result(
        result,
        _key(),
        _persona(),
        _model(),
        resume_count=2,
    )

    assert record.outcome is not None
    assert record.outcome.logprobs == [pytest.approx(-0.3), -0.4]


def test_reordered_twelve_applicant_fields_keep_their_own_logprobs() -> None:
    decisions = {
        f"Applicant {position}": "Yes" if position % 2 else "No"
        for position in range(1, 13)
    }
    token_logprobs = [TokenLogprob("{", -9.0)]
    for offset, position in enumerate(range(12, 0, -1)):
        separator = "" if offset == 0 else ","
        field = f"Applicant {position}"
        token_logprobs.extend(
            [
                TokenLogprob(f'{separator}"{field}":"', -9.0),
                TokenLogprob(decisions[field], -position / 100),
                TokenLogprob('"', -9.0),
            ]
        )
    token_logprobs.append(TokenLogprob("}", -9.0))
    content = "".join(token.token for token in token_logprobs)
    result = _result(
        content=content,
        structured_content=decisions,
        token_logprobs=token_logprobs,
    )

    record = parse_experiment_result(
        result,
        _key(),
        _persona(),
        _model(),
        resume_count=12,
    )

    assert record.outcome is not None
    assert record.outcome.logprobs == [
        pytest.approx(-position / 100) for position in range(1, 13)
    ]
