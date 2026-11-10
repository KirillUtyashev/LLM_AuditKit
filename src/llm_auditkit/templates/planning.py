"""Deterministic request planning for template generation."""

from __future__ import annotations

from collections.abc import Collection

import pandas as pd

from llm_auditkit.data.identity import derive_scenario_ids
from llm_auditkit.inference import (
    DictResponseFormat,
    InferenceBatchPreview,
    InferenceOrchestrator,
    InferenceRequest,
    ResponseField,
)

from .exceptions import TemplateGenerationIdentityError
from .identity import build_generation_fingerprint, build_template_request_id
from .models import TemplateGenerationConfig
from .prompts import build_template_prompt, build_template_system_prompt
from .validation import validate_template_generation_inputs


def build_template_requests(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
    *,
    completed_scenario_ids: Collection[str] = (),
) -> list[InferenceRequest]:
    """Build pending requests in source scenario order."""

    validate_template_generation_inputs(dataset, config)
    scenario_ids = derive_scenario_ids(dataset)
    completed = _validate_completed_scenario_ids(completed_scenario_ids)
    unknown = completed.difference(scenario_ids)
    if unknown:
        raise TemplateGenerationIdentityError(
            "completed scenario IDs must belong to the current dataset"
        )

    fingerprint = build_generation_fingerprint(config)
    response_format = DictResponseFormat(
        fields=[
            ResponseField(
                name=f"template_{position}",
                value_type="string",
                description="One complete resume template",
            )
            for position in range(1, config.templates_per_scenario + 1)
        ],
        include_comment=False,
        include_type_hints=False,
    )

    requests: list[InferenceRequest] = []
    for scenario_id, row in zip(
        scenario_ids,
        dataset.to_dict(orient="records"),
        strict=True,
    ):
        if scenario_id in completed:
            continue
        requests.append(
            InferenceRequest(
                request_id=build_template_request_id(scenario_id, fingerprint),
                prompt=build_template_prompt(row, config),
                system_prompt=build_template_system_prompt(row, config),
                model_config_id=config.model_config_id,
                metadata={
                    "scenario_id": scenario_id,
                    "generation_fingerprint": fingerprint,
                },
                response_format=response_format,
            )
        )
    return requests


def preview_template_batch(
    dataset: pd.DataFrame,
    config: TemplateGenerationConfig,
    inference_orchestrator: InferenceOrchestrator,
    *,
    batch_number: int = 1,
    completed_scenario_ids: Collection[str] = (),
) -> InferenceBatchPreview:
    """Preview one selected pending batch without model inference."""

    requests = build_template_requests(
        dataset,
        config,
        completed_scenario_ids=completed_scenario_ids,
    )
    return inference_orchestrator.preview_batch(
        requests,
        config.inference,
        batch_number=batch_number,
    )


def _validate_completed_scenario_ids(values: Collection[str]) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise TemplateGenerationIdentityError(
            "completed_scenario_ids must be a collection of strings"
        )
    try:
        completed = set(values)
    except TypeError as error:
        raise TemplateGenerationIdentityError(
            "completed_scenario_ids must be a collection of strings"
        ) from error
    if any(not isinstance(value, str) or not value.strip() for value in completed):
        raise TemplateGenerationIdentityError(
            "completed scenario IDs must be non-empty strings"
        )
    return completed
