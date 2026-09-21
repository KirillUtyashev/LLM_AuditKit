"""Command-line composition boundary for YAML-configured experiment execution."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import pandas as pd
from dotenv import load_dotenv

from llm_auditkit.data import (
    DatasetLoader,
    DatasetLoadingException,
    DatasetSchema,
    LocalDatasetSource,
)
from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceBatchPreview,
    InferenceException,
    InferenceOrchestrator,
)

from .configuration import load_experiment_run_config
from .exceptions import (
    ExperimentConfigurationError,
    ExperimentDatasetError,
    ExperimentException,
)
from .models import ExperimentRunConfig
from .runner import ExperimentRunner
from .store import ExperimentResultStore


def main(argv: Sequence[str] | None = None) -> int:
    """Load one YAML run configuration and execute its selected mode."""

    arguments = _parser().parse_args(argv)
    try:
        load_dotenv(override=False)
        run_config = load_experiment_run_config(arguments.config)
        dataset = _load_experiment_dataset(run_config)
        runner = _build_runner(run_config)

        if arguments.preview or arguments.preview_only:
            preview = runner.preview(
                dataset,
                run_config.experiment_config,
                batch_number=arguments.preview_batch,
            )
            _print_preview(preview)
        if arguments.preview_only:
            return 0

        output = _execute(runner, dataset, run_config)
    except (ExperimentException, InferenceException) as error:
        print(f"Experiment stopped: {error}", file=sys.stderr)
        return 1

    print(f"Completed experiment rows: {len(output)}")
    print(f"Output CSV: {run_config.output_path}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-auditkit-experiment",
        description="Run a hiring experiment from a YAML configuration.",
    )
    parser.add_argument("--config", required=True, help="path to experiment YAML")
    preview_group = parser.add_mutually_exclusive_group()
    preview_group.add_argument(
        "--preview",
        action="store_true",
        help="render one batch before executing the experiment",
    )
    preview_group.add_argument(
        "--preview-only",
        action="store_true",
        help="render one batch without executing model inference",
    )
    parser.add_argument(
        "--preview-batch",
        type=int,
        default=1,
        help="one-based pending batch to render (default: 1)",
    )
    return parser


def _load_experiment_dataset(run_config: ExperimentRunConfig) -> pd.DataFrame:
    dataset_path = run_config.dataset_path
    if dataset_path.suffix.lower() != ".csv":
        raise ExperimentDatasetError(
            "the experiment command currently supports CSV dataset paths"
        )
    schema = run_config.experiment_config.dataset_schema
    required_columns = list(
        dict.fromkeys(
            [
                schema.job_posting_column,
                *schema.resume_columns,
                *schema.context_columns.values(),
            ]
        )
    )
    try:
        return DatasetLoader(
            DatasetSchema(
                required_columns=required_columns,
                nonempty_columns=[
                    schema.job_posting_column,
                    *schema.resume_columns,
                ],
            )
        ).load(
            LocalDatasetSource(dataset_path),
        )
    except DatasetLoadingException as error:
        raise ExperimentDatasetError(
            f"could not load experiment CSV: {error}"
        ) from error


def _build_runner(run_config: ExperimentRunConfig) -> ExperimentRunner:
    return ExperimentRunner(
        InferenceOrchestrator(EDSLAdapter()),
        ExperimentResultStore(run_config.output_path),
    )


def _execute(
    runner: ExperimentRunner,
    dataset: pd.DataFrame,
    run_config: ExperimentRunConfig,
) -> pd.DataFrame:
    if run_config.mode == "sync":
        return runner.run(dataset, run_config.experiment_config)
    if run_config.mode == "async":
        return asyncio.run(runner.run_async(dataset, run_config.experiment_config))
    raise ExperimentConfigurationError(
        "execution mode must be exactly 'sync' or 'async'"
    )


def _print_preview(preview: InferenceBatchPreview) -> None:
    for prompt in preview.prompts:
        print(f"Request: {prompt.request_id}")
        print("System prompt:")
        print(prompt.system_prompt)
        print("User prompt:")
        print(prompt.user_prompt)


if __name__ == "__main__":
    raise SystemExit(main())
