"""Tests for deterministic experiment job and request planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import pytest

from llm_auditkit.experiments import (
    ExperimentConfig,
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
            scenario_id_column="scenario_id",
            job_posting_column="job_posting",
            resume_columns=["resume_1", "resume_2"],
            context_columns={"city": "city", "year": "year"},
        ),
        personas=[
            Persona("manager", "Manager", "You are a hiring manager."),
            Persona("predictor", "Predictor", "Predict the manager's decision."),
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
        }
    )


def test_prompt_text_is_stable_and_generalized_to_configured_resumes() -> None:
    prompt = build_experiment_prompt(
        _dataset().to_dict(orient="records")[0],
        _config().dataset_schema,
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


def test_requests_use_persona_system_prompt_and_ordered_response_fields() -> None:
    requests = build_experiment_requests(_dataset(), _config())

    assert requests[0].system_prompt == "You are a hiring manager."
    assert requests[1].system_prompt == "You are a hiring manager."
    assert requests[2].system_prompt == "Predict the manager's decision."
    assert requests[0].response_format is not None
    assert [field.name for field in requests[0].response_format.fields] == [
        "Applicant 1",
        "Applicant 2",
    ]
    assert all(
        field.description == "Yes or No"
        for field in requests[0].response_format.fields
    )
    assert len({request.request_id for request in requests}) == len(requests)


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

    prompt = build_experiment_prompt(
        _dataset().to_dict(orient="records")[0],
        config.dataset_schema,
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
