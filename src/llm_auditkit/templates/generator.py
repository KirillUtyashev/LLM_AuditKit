"""Synchronous and asynchronous orchestration for template generation."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from llm_auditkit.data.identity import derive_scenario_ids
from llm_auditkit.inference import (
    InferenceBatchPreview,
    InferenceBatchResult,
    InferenceOrchestrator,
    InferenceRequest,
)

from .exceptions import TemplateResultAssociationError
from .identity import build_generation_fingerprint, build_template_request_id
from .models import TemplateGenerationConfig
from .parsing import parse_template_batch
from .planning import build_template_requests, preview_template_batch
from .store import TemplateStore


class TemplateGenerator:
    """Generate and checkpoint resume templates through shared inference."""

    def __init__(
        self,
        inference_orchestrator: InferenceOrchestrator,
        template_store: TemplateStore,
    ) -> None:
        if not isinstance(inference_orchestrator, InferenceOrchestrator):
            raise TypeError("inference_orchestrator must be an InferenceOrchestrator")
        if not isinstance(template_store, TemplateStore):
            raise TypeError("template_store must be a TemplateStore")
        self._inference_orchestrator = inference_orchestrator
        self._template_store = template_store

    def preview(
        self,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
        batch_number: int = 1,
    ) -> InferenceBatchPreview:
        """Render one pending logical batch without model inference."""

        output_dataset = self._template_store.initialize(dataset, config)
        completed = self._template_store.completed_scenario_ids(
            output_dataset,
            dataset,
            config,
        )
        return preview_template_batch(
            dataset,
            config,
            self._inference_orchestrator,
            batch_number=batch_number,
            completed_scenario_ids=completed,
        )

    def generate(
        self,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> pd.DataFrame:
        """Generate pending templates with shared inference's synchronous API."""

        output_dataset, pending_scenarios, requests = self._prepare_run(dataset, config)
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
                pending_scenarios,
                batch,
                expected_batch_number,
                expected_total_batches,
            )
            processed_batches = expected_batch_number

        _validate_completed_iteration(processed_batches, expected_total_batches)
        if not config.save_after_each_result:
            self._template_store.save(output_dataset)
        return output_dataset

    async def generate_async(
        self,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> pd.DataFrame:
        """Generate pending templates with shared inference's native async API."""

        output_dataset, pending_scenarios, requests = self._prepare_run(dataset, config)
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
                pending_scenarios,
                batch,
                expected_batch_number,
                expected_total_batches,
            )
            processed_batches = expected_batch_number
            expected_batch_number += 1

        _validate_completed_iteration(processed_batches, expected_total_batches)
        if not config.save_after_each_result:
            self._template_store.save(output_dataset)
        return output_dataset

    def _prepare_run(
        self,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
    ) -> tuple[pd.DataFrame, list[str], list[InferenceRequest]]:
        output_dataset = self._template_store.initialize(dataset, config)
        completed = self._template_store.completed_scenario_ids(
            output_dataset,
            dataset,
            config,
        )
        pending_scenarios = [
            scenario_id
            for scenario_id in derive_scenario_ids(dataset)
            if scenario_id not in completed
        ]
        requests = build_template_requests(
            dataset,
            config,
            completed_scenario_ids=completed,
        )
        fingerprint = build_generation_fingerprint(config)
        expected_request_ids = [
            build_template_request_id(scenario_id, fingerprint)
            for scenario_id in pending_scenarios
        ]
        if [request.request_id for request in requests] != expected_request_ids:
            raise TemplateResultAssociationError(
                "pending template requests do not match canonical scenario order"
            )
        return output_dataset, pending_scenarios, requests

    def _process_batch(
        self,
        output_dataset: pd.DataFrame,
        dataset: pd.DataFrame,
        config: TemplateGenerationConfig,
        pending_scenarios: Sequence[str],
        batch: InferenceBatchResult,
        expected_batch_number: int,
        expected_total_batches: int,
    ) -> pd.DataFrame:
        if not isinstance(batch, InferenceBatchResult):
            raise TemplateResultAssociationError(
                "shared inference must yield InferenceBatchResult values"
            )
        if (
            batch.batch_number != expected_batch_number
            or batch.total_batches != expected_total_batches
        ):
            raise TemplateResultAssociationError(
                "shared inference batch progress does not match the pending plan"
            )

        start = (expected_batch_number - 1) * config.inference.batch_size
        expected_scenarios = list(
            pending_scenarios[start : start + config.inference.batch_size]
        )
        records = parse_template_batch(batch.results, expected_scenarios, config)
        if config.save_after_each_result:
            updated = output_dataset
            for record in records:
                updated = self._template_store.save_result(
                    updated,
                    dataset,
                    config,
                    record,
                )
            return updated
        return self._template_store.apply_results(
            output_dataset,
            dataset,
            config,
            records,
        )

    def _finish_empty_run(self, output_dataset: pd.DataFrame) -> pd.DataFrame:
        if not self._template_store.output_path.exists():
            self._template_store.save(output_dataset)
        return output_dataset


def _total_batches(request_count: int, batch_size: int) -> int:
    return (request_count + batch_size - 1) // batch_size


def _validate_completed_iteration(
    processed_batches: int,
    expected_total_batches: int,
) -> None:
    if processed_batches != expected_total_batches:
        raise TemplateResultAssociationError(
            "shared inference ended before every template batch was processed"
        )
