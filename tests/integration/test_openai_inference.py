"""Opt-in smoke tests against the real OpenAI API through EDSL."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceBatchResult,
    InferenceConfig,
    InferenceOrchestrator,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
)


pytestmark = pytest.mark.live_inference

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MODEL_CONFIG_ID = "live-openai-smoke-test"
_OPENAI_MODEL = "gpt-4.1-nano"
_SYSTEM_PROMPT = (
    "You are running an integration smoke test. Follow the user's output format "
    "exactly and do not add explanations or formatting."
)


@pytest.fixture(scope="module")
def live_openai_config() -> InferenceConfig:
    """Load local credentials only after the live-test gate is enabled."""

    load_dotenv(_REPOSITORY_ROOT / ".env", override=False)

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.fail(
            "live OpenAI inference requires OPENAI_API_KEY",
            pytrace=False,
        )

    return InferenceConfig(
        models=[
            ModelConfig(
                config_id=_MODEL_CONFIG_ID,
                provider="openai",
                model=_OPENAI_MODEL,
            )
        ],
        batch_size=2,
    )


def test_live_openai_preview_renders_prompts_without_inference(
    live_openai_config: InferenceConfig,
) -> None:
    requests = _sync_requests()

    preview = InferenceOrchestrator(EDSLAdapter()).preview_batch(
        requests,
        live_openai_config,
    )

    assert preview.batch_number == 1
    assert preview.total_batches == 1
    assert [prompt.request_id for prompt in preview.prompts] == [
        request.request_id for request in requests
    ]
    for rendered_prompt, request in zip(preview.prompts, requests, strict=True):
        assert request.metadata["expected_token"] in rendered_prompt.user_prompt
        assert rendered_prompt.system_prompt is not None
        assert "integration smoke test" in rendered_prompt.system_prompt


def test_live_openai_synchronous_batch_preserves_outcomes(
    live_openai_config: InferenceConfig,
) -> None:
    requests = _sync_requests()

    batches = list(
        InferenceOrchestrator(EDSLAdapter()).run_batches(
            requests,
            live_openai_config,
        )
    )

    assert len(batches) == 1
    assert batches[0].batch_number == 1
    assert batches[0].total_batches == 1
    assert batches[0].elapsed_seconds >= 0
    assert [result.request_id for result in batches[0].results] == [
        request.request_id for request in requests
    ]
    for result, request in zip(batches[0].results, requests, strict=True):
        _assert_successful_token_result(result, request)


def test_live_openai_asynchronous_batch_preserves_outcome(
    live_openai_config: InferenceConfig,
) -> None:
    request = InferenceRequest(
        request_id="live-openai-async",
        prompt="Return exactly this token and nothing else: ASYNC_OK",
        system_prompt=_SYSTEM_PROMPT,
        model_config_id=_MODEL_CONFIG_ID,
        metadata={"expected_token": "ASYNC_OK", "execution": "async"},
    )

    async def collect_batches() -> list[InferenceBatchResult]:
        return [
            batch
            async for batch in InferenceOrchestrator(
                EDSLAdapter()
            ).run_batches_async([request], live_openai_config)
        ]

    batches = asyncio.run(collect_batches())

    assert len(batches) == 1
    assert batches[0].batch_number == 1
    assert batches[0].total_batches == 1
    assert batches[0].elapsed_seconds >= 0
    assert len(batches[0].results) == 1
    _assert_successful_token_result(batches[0].results[0], request)


def _sync_requests() -> list[InferenceRequest]:
    return [
        InferenceRequest(
            request_id="live-openai-sync-alpha",
            prompt="Return exactly this token and nothing else: SYNC_ALPHA",
            system_prompt=_SYSTEM_PROMPT,
            model_config_id=_MODEL_CONFIG_ID,
            metadata={"expected_token": "SYNC_ALPHA", "position": 1},
        ),
        InferenceRequest(
            request_id="live-openai-sync-beta",
            prompt="Return exactly this token and nothing else: SYNC_BETA",
            system_prompt=_SYSTEM_PROMPT,
            model_config_id=_MODEL_CONFIG_ID,
            metadata={"expected_token": "SYNC_BETA", "position": 2},
        ),
    ]


def _assert_successful_token_result(
    result: InferenceResult,
    request: InferenceRequest,
) -> None:
    expected_token = request.metadata["expected_token"]

    assert result.model_config_id == request.model_config_id
    assert result.metadata == request.metadata
    assert result.error is None
    assert result.content is not None
    assert isinstance(expected_token, str)
    assert expected_token in result.content
