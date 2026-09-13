"""Tests for deterministic experiment job and request planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetError,
    ExperimentDatasetSchema,
    ExperimentIdentityError,
    ExperimentJobKey,
    Persona,
)
from llm_auditkit.experiments.planning import (
    build_experiment_job_keys,
    build_experiment_requests,
    preview_experiment_batch,
)
from llm_auditkit.experiments.prompts import build_experiment_prompt
from llm_auditkit.inference import (
    InferenceOrchestrator,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)
from llm_auditkit.inference.models import InferenceConfig


class PreviewAdapter:
    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        del models
        return [
            RenderedPrompt(
                request_id=request.request_id,
                user_prompt=f"rendered:{request.prompt}",
                system_prompt=request.system_prompt,
            )
            for request in requests
        ]

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        raise AssertionError("preview must not execute inference")

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        raise AssertionError("preview must not execute inference")


def _config(*, batch_size: int = 3) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="experiment-1",
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column="job_posting",
            resume_columns=["resume_1", "resume_2"],
            context_columns={"city": "city", "year": "year"},
        ),
        prompt_template="""Job posting:
{job_posting}

Context:
city: {city}
year: {year}

Here are 2 additional applicant materials received this week:

Applicant 1:
{resume_1}

Applicant 2:
{resume_2}

Based on the job posting, context, and information available in the applicant materials, select each applicant whom you would like to invite for an interview, if any. There is no need to select any applicant if none should be interviewed. Interviews are costly, so consider each selection carefully.""",
        personas=[
            Persona(
                "manager",
                "Manager",
                "You are a hiring manager in {city} in {year}.",
                "Evaluate the applicant materials.",
            ),
            Persona(
                "predictor",
                "Predictor",
                "Predict the hiring manager in {city}.",
                "Make an honest prediction.",
            ),
        ],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    "model-1",
                    "openai",
                    "first-model",
                    {"logprobs": True},
                ),
                ModelConfig(
                    "model-2",
                    "openai",
                    "second-model",
                    {"logprobs": True},
                ),
            ],
            batch_size=batch_size,
        ),
    )


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": ["scenario-1", "scenario-2"],
            "job_posting": ["Posting one", "Posting two"],
            "resume_1": ["Resume 1A", "Resume 1B"],
            "resume_2": ["Resume 2A", "Resume 2B"],
            "city": ["Toronto", "Boston"],
            "year": [2020, 1960],
            "source_note": ["first", "second"],
        }
    )


def test_prompt_text_is_stable_and_generalized_to_configured_resumes() -> None:
    config = _config()
    prompt = build_experiment_prompt(
        _dataset().to_dict(orient="records")[0],
        config.dataset_schema,
        config.prompt_template,
    )

    assert prompt == """Job posting:
Posting one

Context:
city: Toronto
year: 2020

Here are 2 additional applicant materials received this week:

Applicant 1:
Resume 1A

Applicant 2:
Resume 2A

Based on the job posting, context, and information available in the applicant materials, select each applicant whom you would like to invite for an interview, if any. There is no need to select any applicant if none should be interviewed. Interviews are costly, so consider each selection carefully."""


def test_job_and_request_order_is_scenario_then_persona_then_model() -> None:
    config = _config()

    keys = build_experiment_job_keys(_dataset(), config)
    requests = build_experiment_requests(_dataset(), config)

    expected_dimensions = [
        (scenario_id, persona_id, model_id)
        for scenario_id in ["scenario-1", "scenario-2"]
        for persona_id in ["manager", "predictor"]
        for model_id in ["model-1", "model-2"]
    ]
    assert [
        (key.scenario_id, key.persona_id, key.model_config_id) for key in keys
    ] == expected_dimensions
    assert [
        (
            request.metadata["scenario_id"],
            request.metadata["persona_id"],
            request.model_config_id,
        )
        for request in requests
    ] == expected_dimensions


def test_missing_scenario_ids_are_derived_stably_from_complete_rows() -> None:
    dataset = _dataset().drop(columns=["scenario_id"])
    config = _config()

    original_keys = build_experiment_job_keys(dataset, config)
    reordered_keys = build_experiment_job_keys(
        dataset[list(reversed(dataset.columns))],
        config,
    )
    reindexed_dataset = dataset.copy()
    reindexed_dataset.index = [20, 10]
    reindexed_keys = build_experiment_job_keys(reindexed_dataset, config)
    changed_dataset = dataset.copy()
    changed_dataset.loc[0, "source_note"] = "changed"
    changed_keys = build_experiment_job_keys(changed_dataset, config)

    assert all(key.scenario_id.startswith("scenario:") for key in original_keys)
    assert [key.scenario_id for key in reordered_keys] == [
        key.scenario_id for key in original_keys
    ]
    assert [key.scenario_id for key in reindexed_keys] == [
        key.scenario_id for key in original_keys
    ]
    assert changed_keys[0].scenario_id != original_keys[0].scenario_id
    assert changed_keys[4].scenario_id == original_keys[4].scenario_id


def test_requests_render_persona_and_use_static_instruction() -> None:
    requests = build_experiment_requests(_dataset(), _config())

    assert requests[0].persona == "You are a hiring manager in Toronto in 2020."
    assert requests[1].persona == requests[0].persona
    assert requests[2].persona == "Predict the hiring manager in Toronto."
    assert requests[0].system_prompt == "Evaluate the applicant materials."
    assert requests[2].system_prompt == "Make an honest prediction."
    assert requests[0].response_format is not None
    assert [field.name for field in requests[0].response_format.fields] == [
        "Applicant 1",
        "Applicant 2",
    ]
    assert all(
        field.description == "Yes or No"
        for field in requests[0].response_format.fields
    )
    assert requests[0].response_format.include_type_hints is False
    assert len({request.request_id for request in requests}) == len(requests)


def test_paper_persona_fields_derive_date14_and_newspaper_without_mutation() -> None:
    dataset = _dataset().iloc[[0]].copy()
    dataset.loc[:, "city"] = "Birmingham"
    dataset.loc[:, "year"] = 1950
    dataset["month"] = 6
    dataset["day"] = 18
    original = dataset.copy(deep=True)
    config = _config()
    config.dataset_schema.context_columns.update({"month": "month", "day": "day"})
    config.personas = [
        Persona(
            "manager",
            "Manager",
            "Today is {date14}. You are the HR manager in {city} reading "
            "the {newspaper}: {job_posting}.",
            "Evaluate application forms.",
        )
    ]

    request = build_experiment_requests(dataset, config)[0]

    assert request.persona == (
        "Today is July 02, 1950. You are the HR manager in Birmingham reading "
        "the Birmingham News: Posting one."
    )
    pd.testing.assert_frame_equal(dataset, original)


@pytest.mark.parametrize(
    ("city", "month", "message"),
    [("Toronto", 6, "supported city"), ("Birmingham", 13, "valid year")],
)
def test_invalid_paper_persona_derivations_fail_before_inference(
    city: str,
    month: int,
    message: str,
) -> None:
    dataset = _dataset().iloc[[0]].copy()
    dataset.loc[:, "city"] = city
    dataset["month"] = month
    dataset["day"] = 18
    config = _config()
    config.dataset_schema.context_columns.update({"month": "month", "day": "day"})
    config.personas = [
        Persona(
            "manager",
            "Manager",
            "Today is {date14}; newspaper: {newspaper}.",
            "Evaluate applicants.",
        )
    ]

    with pytest.raises(ExperimentDatasetError, match=message):
        build_experiment_requests(dataset, config)


def test_completed_jobs_are_removed_without_reordering_pending_jobs() -> None:
    dataset = _dataset()
    config = _config()
    keys = build_experiment_job_keys(dataset, config)

    requests = build_experiment_requests(
        dataset,
        config,
        completed_keys={keys[1], keys[4]},
    )

    assert [request.metadata["scenario_id"] for request in requests] == [
        "scenario-1",
        "scenario-1",
        "scenario-1",
        "scenario-2",
        "scenario-2",
        "scenario-2",
    ]
    assert [request.metadata["model_config_id"] for request in requests] == [
        "model-1",
        "model-1",
        "model-2",
        "model-2",
        "model-1",
        "model-2",
    ]


def test_prompt_does_not_claim_absent_context() -> None:
    config = _config()
    config.dataset_schema.context_columns = {}
    config.prompt_template = """Job posting:
{job_posting}

Applicant 1:
{resume_1}

Applicant 2:
{resume_2}

Based on the job posting and information available in the applicant materials, select applicants."""

    prompt = build_experiment_prompt(
        _dataset().to_dict(orient="records")[0],
        config.dataset_schema,
        config.prompt_template,
    )

    assert "Context:" not in prompt
    assert "Based on the job posting and information" in prompt


def test_completed_job_must_belong_to_current_plan() -> None:
    unknown = ExperimentJobKey(
        "experiment-1",
        "unknown-scenario",
        "manager",
        "model-1",
    )

    with pytest.raises(ExperimentIdentityError, match="current experiment plan"):
        build_experiment_requests(
            _dataset(),
            _config(),
            completed_keys={unknown},
        )


def test_preview_uses_shared_inference_batching_without_execution() -> None:
    preview = preview_experiment_batch(
        _dataset(),
        _config(batch_size=3),
        InferenceOrchestrator(PreviewAdapter()),
        batch_number=2,
    )

    assert preview.batch_number == 2
    assert preview.total_batches == 3
    assert len(preview.prompts) == 3
    assert all(prompt.user_prompt.startswith("rendered:") for prompt in preview.prompts)
