"""Opt-in experiment runner smoke tests against the real OpenAI API."""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentResultStore,
    ExperimentRunner,
    Persona,
)
from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceOrchestrator,
    ModelConfig,
)


pytestmark = pytest.mark.live_inference

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MODEL_CONFIG_ID = "live-openai-experiment-smoke-test"
_OPENAI_MODEL = "gpt-4.1-nano"


@pytest.fixture(scope="module", autouse=True)
def require_openai_key() -> None:
    load_dotenv(_REPOSITORY_ROOT / ".env", override=False)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.fail(
            "live OpenAI experiment execution requires OPENAI_API_KEY",
            pytrace=False,
        )


def test_live_openai_synchronous_experiment(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    config = _config("live-openai-experiment-sync")
    runner = _runner(tmp_path / "sync.csv")

    preview = runner.preview(dataset, config)
    output = runner.run(dataset, config)

    assert preview.batch_number == 1
    assert preview.total_batches == 1
    assert len(preview.prompts) == 1
    _assert_successful_output(output)


def test_live_openai_asynchronous_experiment(
    tmp_path: Path,
) -> None:
    output = asyncio.run(
        _runner(tmp_path / "async.csv").run_async(
            _dataset(),
            _config("live-openai-experiment-async"),
        )
    )

    _assert_successful_output(output)


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": ["live-synthetic-scenario"],
            "job_posting": ["Hire a research assistant who can organize text data."],
            "resume_1": [
                "The synthetic applicant has research and data-organization experience."
            ],
        }
    )


def _config(experiment_id: str) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id=experiment_id,
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column="job_posting",
            resume_columns=["resume_1"],
        ),
        prompt_template="Applicant 1: {resume_1}",
        personas=[
            Persona(
                id="live-hiring-manager",
                name="Hiring manager",
                trait_template="You are the hiring manager responsible for this role.",
                instruction="Evaluate the applicant material carefully.",
            )
        ],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    config_id=_MODEL_CONFIG_ID,
                    provider="openai",
                    model=_OPENAI_MODEL,
                    parameters={"temperature": 0, "logprobs": True},
                )
            ],
            batch_size=1,
        ),
    )


def _runner(output_path: Path) -> ExperimentRunner:
    return ExperimentRunner(
        InferenceOrchestrator(EDSLAdapter()),
        ExperimentResultStore(output_path),
    )


def _assert_successful_output(output: pd.DataFrame) -> None:
    assert len(output) == 1
    assert pd.isna(output.loc[0, "error_type"])
    assert output.loc[0, "pick1"] in {0, 1}
    assert output.loc[0, "picks"] in {"[0]", "[1]"}
    assert math.isfinite(float(output.loc[0, "logprob1"]))
    assert isinstance(output.loc[0, "generated_response"], str)
