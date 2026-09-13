"""Synchronous and asynchronous orchestration for hiring experiments."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from llm_auditkit.inference import (
    InferenceBatchPreview,
    InferenceBatchResult,
    InferenceOrchestrator,
    InferenceRequest,
)

from .exceptions import ExperimentResultAssociationError
from .models import ExperimentConfig, ExperimentJobKey, build_experiment_request_id
from .parsing import parse_experiment_batch
from .planning import (
    build_experiment_job_keys,
    build_experiment_requests,
    preview_experiment_batch,
)
from .store import ExperimentResultStore


class ExperimentRunner:
    """Run validated experiment jobs through shared inference and durable storage."""

    def __init__(
        self,
        inference_orchestrator: InferenceOrchestrator,
        result_store: ExperimentResultStore,
    ) -> None:
        if not isinstance(inference_orchestrator, InferenceOrchestrator):
            raise TypeError("inference_orchestrator must be an InferenceOrchestrator")
        if not isinstance(result_store, ExperimentResultStore):
            raise TypeError("result_store must be an ExperimentResultStore")
        self._inference_orchestrator = inference_orchestrator
        self._result_store = result_store

    def preview(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
        batch_number: int = 1,
    ) -> InferenceBatchPreview:
        """Render one pending logical batch without performing model inference."""

        output_dataset = self._result_store.initialize(dataset, config)
        completed_keys = self._result_store.completed_keys(
            output_dataset,
            dataset,
            config,
        )
        return preview_experiment_batch(
            dataset,
            config,
            self._inference_orchestrator,
            batch_number=batch_number,
            completed_keys=completed_keys,
        )

    def run(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        """Execute pending jobs with the shared inference synchronous API."""

        output_dataset, pending_keys, requests = self._prepare_run(dataset, config)
        if not requests:
            return self._finish_empty_run(output_dataset)

        expected_total_batches = _total_batches(
            len(requests),
            config.inference.batch_size,
        )
        processed_batches = 0
        for expected_batch_number, batch in enumerate(
            self._inference_orchestrator.run_batches(requests, config.inference),
            start=1,
        ):
            output_dataset = self._process_batch(
                output_dataset,
                dataset,
                config,
                pending_keys,
                batch,
                expected_batch_number,
                expected_total_batches,
            )
            processed_batches = expected_batch_number

        _validate_completed_iteration(processed_batches, expected_total_batches)
        if not config.save_after_each_batch:
            self._result_store.save(output_dataset)
        return output_dataset

    async def run_async(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> pd.DataFrame:
        """Execute pending jobs with the shared inference native async API."""

        output_dataset, pending_keys, requests = self._prepare_run(dataset, config)
        if not requests:
            return self._finish_empty_run(output_dataset)

        expected_total_batches = _total_batches(
            len(requests),
            config.inference.batch_size,
        )
        processed_batches = 0
        expected_batch_number = 1
        async for batch in self._inference_orchestrator.run_batches_async(
            requests,
            config.inference,
        ):
            output_dataset = self._process_batch(
                output_dataset,
                dataset,
                config,
                pending_keys,
                batch,
                expected_batch_number,
                expected_total_batches,
            )
            processed_batches = expected_batch_number
            expected_batch_number += 1

        _validate_completed_iteration(processed_batches, expected_total_batches)
        if not config.save_after_each_batch:
            self._result_store.save(output_dataset)
        return output_dataset

    def _prepare_run(
        self,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
    ) -> tuple[pd.DataFrame, list[ExperimentJobKey], list[InferenceRequest]]:
        output_dataset = self._result_store.initialize(dataset, config)
        completed_keys = self._result_store.completed_keys(
            output_dataset,
            dataset,
            config,
        )
        pending_keys = [
            key
            for key in build_experiment_job_keys(dataset, config)
            if key not in completed_keys
        ]
        requests = build_experiment_requests(
            dataset,
            config,
            completed_keys=completed_keys,
        )
        expected_request_ids = [
            build_experiment_request_id(key) for key in pending_keys
        ]
        if [request.request_id for request in requests] != expected_request_ids:
            raise ExperimentResultAssociationError(
                "pending experiment requests do not match the canonical job plan"
            )
        return output_dataset, pending_keys, requests

    def _process_batch(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: ExperimentConfig,
        pending_keys: Sequence[ExperimentJobKey],
        batch: InferenceBatchResult,
        expected_batch_number: int,
        expected_total_batches: int,
    ) -> pd.DataFrame:
        if not isinstance(batch, InferenceBatchResult):
            raise ExperimentResultAssociationError(
                "shared inference must yield InferenceBatchResult values"
            )
        if (
            batch.batch_number != expected_batch_number
            or batch.total_batches != expected_total_batches
        ):
            raise ExperimentResultAssociationError(
                "shared inference batch progress does not match the pending job plan"
            )

        start = (expected_batch_number - 1) * config.inference.batch_size
        expected_keys = list(
            pending_keys[start : start + config.inference.batch_size]
        )
        records = parse_experiment_batch(
            batch.results,
            expected_keys,
            {persona.id: persona for persona in config.personas},
            {model.config_id: model for model in config.inference.models},
            resume_count=len(config.dataset_schema.resume_columns),
        )
        if config.save_after_each_batch:
            return self._result_store.save_batch(
                output_dataset,
                dataset,
                config,
                records,
            )
        return self._result_store.apply_batch(
            output_dataset,
            dataset,
            config,
            records,
        )

    def _finish_empty_run(self, output_dataset: pd.DataFrame) -> pd.DataFrame:
        if not self._result_store.output_path.exists():
            self._result_store.save(output_dataset)
        return output_dataset


def _total_batches(request_count: int, batch_size: int) -> int:
    return (request_count + batch_size - 1) // batch_size


def _validate_completed_iteration(
    processed_batches: int,
    expected_total_batches: int,
) -> None:
    if processed_batches != expected_total_batches:
        raise ExperimentResultAssociationError(
            "shared inference ended before every pending experiment batch was returned"
        )
