"""Run one small hiring experiment through the asynchronous execution API."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentException,
    ExperimentResultStore,
    ExperimentRunner,
    Persona,
)
from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceException,
    InferenceOrchestrator,
    ModelConfig,
)


async def run() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: python examples/experiment_execution_async.py OUTPUT.csv",
            file=sys.stderr,
        )
        return 2

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Set OPENAI_API_KEY in .env or the process environment.", file=sys.stderr)
        return 2

    output_path = Path(sys.argv[1])
    dataset = _dataset()
    config = _config()
    runner = ExperimentRunner(
        InferenceOrchestrator(EDSLAdapter()),
        ExperimentResultStore(output_path),
    )

    try:
        if not output_path.exists():
            preview = runner.preview(dataset, config)
            for rendered in preview.prompts:
                print("Effective system prompt:")
                print(rendered.system_prompt)
                print("Effective user prompt:")
                print(rendered.user_prompt)
        else:
            print(f"Resuming checkpoint: {output_path}")

        output = await runner.run_async(dataset, config)
    except (ExperimentException, InferenceException) as error:
        print(f"Experiment stopped: {error}", file=sys.stderr)
        return 1

    print(output[_summary_columns(config)].to_string(index=False))
    print(f"Saved checkpoint: {output_path}")
    return 0


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": ["synthetic-scenario-1"],
            "job_posting": [
                "Hire a careful research assistant who can organize qualitative data."
            ],
            "resume_1": [
                "Candidate A has two years of research-assistant experience and strong "
                "data-organization skills."
            ],
            "resume_2": [
                "Candidate B has retail experience and is learning spreadsheet tools."
            ],
            "city": ["Toronto"],
        }
    )


def _config() -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="example-async-v1",
        dataset_schema=ExperimentDatasetSchema(
            scenario_id_column="scenario_id",
            job_posting_column="job_posting",
            resume_columns=["resume_1", "resume_2"],
            context_columns={"city": "city"},
        ),
        personas=[
            Persona(
                id="hiring-manager-v1",
                name="Hiring manager",
                description="You are the hiring manager responsible for this role.",
            )
        ],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    config_id="openai-gpt-4.1-nano-v1",
                    provider="openai",
                    model="gpt-4.1-nano",
                    parameters={"temperature": 0, "logprobs": True},
                )
            ],
            batch_size=1,
        ),
        save_after_each_batch=True,
    )


def _summary_columns(config: ExperimentConfig) -> list[str]:
    applicant_count = len(config.dataset_schema.resume_columns)
    return (
        ["scenario_id", "persona_id", "model_config_id", "picks"]
        + [f"logprob{position}" for position in range(1, applicant_count + 1)]
        + ["error_type", "error_message"]
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
