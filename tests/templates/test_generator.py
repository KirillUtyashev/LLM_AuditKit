"""End-to-end unit tests for template-generation orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
import pytest

from llm_auditkit.inference import (
    InferenceBatchError,
    InferenceError,
    InferenceOrchestrator,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
)
from llm_auditkit.templates import TemplateGenerator, TemplateStore

from .helpers import config, dataset, template_text


class RecordingAdapter:
    def __init__(
        self,
        *,
        failure_scenarios: set[str] | None = None,
        invalid_scenarios: set[str] | None = None,
        systemic_failure_call: int | None = None,
    ) -> None:
        self.failure_scenarios = failure_scenarios or set()
        self.invalid_scenarios = invalid_scenarios or set()
        self.systemic_failure_call = systemic_failure_call
        self.render_calls: list[list[str]] = []
        self.sync_calls: list[list[str]] = []
        self.async_calls: list[list[str]] = []

    def render_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[RenderedPrompt]:
        del models
        self.render_calls.append(_scenario_ids(requests))
        return list(
            reversed(
                [
                    RenderedPrompt(
                        request_id=request.request_id,
                        user_prompt=f"rendered:{request.prompt}",
                        system_prompt=f"rendered:{request.system_prompt}",
                    )
                    for request in requests
                ]
            )
        )

    def execute_batch(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        del models
        self.sync_calls.append(_scenario_ids(requests))
        return self._results(requests, len(self.sync_calls))

    async def execute_batch_async(
        self,
        requests: Sequence[InferenceRequest],
        models: Mapping[str, ModelConfig],
    ) -> list[InferenceResult]:
        del models
        self.async_calls.append(_scenario_ids(requests))
        return self._results(requests, len(self.async_calls))

    def _results(
        self,
        requests: Sequence[InferenceRequest],
        call_number: int,
    ) -> list[InferenceResult]:
        results = [_result_for_request(request, self) for request in requests]
        if self.systemic_failure_call == call_number:
            results[0].request_id = "unknown-request"
        return list(reversed(results))


class CountingStore(TemplateStore):
    def __init__(self, output_path: Path) -> None:
        super().__init__(output_path)
        self.save_calls = 0

    def save(self, output_dataset: pd.DataFrame) -> None:
        self.save_calls += 1
        super().save(output_dataset)


def _scenario_ids(requests: Sequence[InferenceRequest]) -> list[str]:
    return [str(request.metadata["scenario_id"]) for request in requests]


def _result_for_request(
    request: InferenceRequest,
    adapter: RecordingAdapter,
) -> InferenceResult:
    scenario_id = str(request.metadata["scenario_id"])
    if scenario_id in adapter.failure_scenarios:
        return InferenceResult(
            request_id=request.request_id,
            model_config_id=request.model_config_id,
            content=None,
            metadata={},
            error=InferenceError("ProviderError", "request failed after retries"),
        )

    assert request.response_format is not None
    structured_content = {
        field.name: template_text(scenario_id, position)
        for position, field in enumerate(request.response_format.fields, start=1)
    }
    if scenario_id in adapter.invalid_scenarios:
        structured_content["template_1"] = "Resume without placeholders"
    return InferenceResult(
        request_id=request.request_id,
        model_config_id=request.model_config_id,
        content="structured templates",
        metadata={},
        structured_content=structured_content,
    )


def _generator(
    tmp_path: Path,
    adapter: RecordingAdapter,
    *,
    filename: str = "templates.csv",
) -> tuple[TemplateGenerator, CountingStore]:
    store = CountingStore(tmp_path / filename)
    generator = TemplateGenerator(InferenceOrchestrator(adapter), store)
    return generator, store


def _normalize_missing(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.astype(object).where(frame.notna(), "<missing>")


def test_preview_renders_only_the_selected_pending_batch(tmp_path: Path) -> None:
    adapter = RecordingAdapter()
    generator, _ = _generator(tmp_path, adapter)

    preview = generator.preview(dataset(), config(), batch_number=2)

    assert preview.batch_number == 2
    assert preview.total_batches == 2
    assert adapter.render_calls == [["scenario-3"]]
    assert adapter.sync_calls == []
    assert adapter.async_calls == []
    assert len(preview.prompts) == 1
    assert preview.prompts[0].system_prompt == (
        "rendered:You are a resume agency serving Birmingham."
    )


def test_sync_generation_checkpoints_each_result_in_canonical_order(
    tmp_path: Path,
) -> None:
    adapter = RecordingAdapter()
    generator, store = _generator(tmp_path, adapter)

    output = generator.generate(dataset(), config())

    assert adapter.sync_calls == [
        ["scenario-1", "scenario-2"],
        ["scenario-3"],
    ]
    assert adapter.async_calls == []
    assert store.save_calls == 3
    assert output["scenario_id"].tolist() == [
        "scenario-1",
        "scenario-2",
        "scenario-3",
    ]
    assert output["template_1"].tolist() == [
        template_text("scenario-1", 1),
        template_text("scenario-2", 1),
        template_text("scenario-3", 1),
    ]
    assert output["template_generation_error_type"].isna().all()


def test_async_generation_uses_native_async_batches_and_matches_sync_output(
    tmp_path: Path,
) -> None:
    source = dataset()
    generation = config(save_after_each_result=False)
    sync_adapter = RecordingAdapter()
    async_adapter = RecordingAdapter()
    sync_generator, sync_store = _generator(
        tmp_path,
        sync_adapter,
        filename="sync.csv",
    )
    async_generator, async_store = _generator(
        tmp_path,
        async_adapter,
        filename="async.csv",
    )

    sync_output = sync_generator.generate(source, generation)
    async_output = asyncio.run(async_generator.generate_async(source, generation))

    assert async_adapter.sync_calls == []
    assert async_adapter.async_calls == [
        ["scenario-1", "scenario-2"],
        ["scenario-3"],
    ]
    assert sync_store.save_calls == 1
    assert async_store.save_calls == 1
    pd.testing.assert_frame_equal(
        _normalize_missing(sync_output),
        _normalize_missing(async_output),
        check_dtype=False,
    )


def test_resume_retries_failures_skips_completed_scenarios_and_noops_when_done(
    tmp_path: Path,
) -> None:
    source = dataset(3)
    generation = config()
    first_adapter = RecordingAdapter(
        failure_scenarios={"scenario-1"},
        invalid_scenarios={"scenario-2"},
    )
    first_generator, store = _generator(tmp_path, first_adapter)

    first_output = first_generator.generate(source, generation)

    assert first_output.loc[0, "template_generation_error_type"] == "ProviderError"
    assert (
        first_output.loc[1, "template_generation_error_type"]
        == "TemplateResponseParseError"
    )
    assert pd.isna(first_output.loc[2, "template_generation_error_type"])

    retry_adapter = RecordingAdapter()
    retry_generator = TemplateGenerator(InferenceOrchestrator(retry_adapter), store)
    retry_output = retry_generator.generate(source, generation)

    assert retry_adapter.sync_calls == [["scenario-1", "scenario-2"]]
    assert retry_output["template_generation_error_type"].isna().all()

    no_op_adapter = RecordingAdapter()
    no_op_generator = TemplateGenerator(InferenceOrchestrator(no_op_adapter), store)
    save_calls_before_noop = store.save_calls
    no_op_output = no_op_generator.generate(source, generation)

    assert no_op_adapter.sync_calls == []
    assert store.save_calls == save_calls_before_noop
    pd.testing.assert_frame_equal(retry_output, no_op_output)


def test_systemic_inference_failure_stops_before_a_later_batch(
    tmp_path: Path,
) -> None:
    adapter = RecordingAdapter(systemic_failure_call=2)
    generator, store = _generator(tmp_path, adapter)
    source = dataset(3)

    with pytest.raises(InferenceBatchError, match="unknown request ID"):
        generator.generate(source, config(batch_size=1))

    assert adapter.sync_calls == [["scenario-1"], ["scenario-2"]]
    checkpoint = store.initialize(source, config(batch_size=1))
    assert store.completed_scenario_ids(
        checkpoint,
        source,
        config(batch_size=1),
    ) == {"scenario-1"}
