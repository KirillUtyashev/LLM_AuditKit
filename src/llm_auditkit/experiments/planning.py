"""Deterministic job and inference-request planning for experiments."""

from __future__ import annotations

from collections.abc import Collection

import pandas as pd

from llm_auditkit.inference import (
    DictResponseFormat,
    InferenceBatchPreview,
    InferenceOrchestrator,
    InferenceRequest,
    ResponseField,
)

from .exceptions import ExperimentIdentityError
from .identity import derive_scenario_ids
from .models import (
    ExperimentConfig,
    ExperimentJobKey,
    build_experiment_request_id,
)
from .prompts import build_experiment_prompt, render_persona_trait
from .validation import validate_experiment_inputs


def build_experiment_job_keys(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> list[ExperimentJobKey]:
    """Return every configured job key in canonical execution order."""

    validate_experiment_inputs(dataset, config)
    return _build_experiment_job_keys(dataset, config)


def _build_experiment_job_keys(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
) -> list[ExperimentJobKey]:
    scenario_ids = derive_scenario_ids(dataset)
    return [
        ExperimentJobKey(
            experiment_id=config.experiment_id,
            scenario_id=scenario_id,
            persona_id=persona.id,
            model_config_id=model.config_id,
        )
        for scenario_id in scenario_ids
        for persona in config.personas
        for model in config.inference.models
    ]


def build_experiment_requests(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
    *,
    completed_keys: Collection[ExperimentJobKey] = (),
) -> list[InferenceRequest]:
    """Build pending inference requests in canonical scenario-persona-model order."""

    validate_experiment_inputs(dataset, config)
    completed = _validate_completed_keys(completed_keys)
    planned_keys = _build_experiment_job_keys(dataset, config)
    unknown_completed = completed.difference(planned_keys)
    if unknown_completed:
        raise ExperimentIdentityError(
            "completed experiment job keys must belong to the current experiment plan"
        )

    response_format = DictResponseFormat(
        fields=[
            ResponseField(
                name=f"Applicant {position}",
                value_type="string",
                description="Yes or No",
            )
            for position in range(1, len(config.dataset_schema.resume_columns) + 1)
        ],
        include_comment=True,
        include_type_hints=False,
    )
    rows_by_scenario_id = dict(
        zip(
            derive_scenario_ids(dataset),
            dataset.to_dict(orient="records"),
            strict=True,
        )
    )
    personas_by_id = {persona.id: persona for persona in config.personas}

    requests: list[InferenceRequest] = []
    for key in planned_keys:
        if key in completed:
            continue
        persona = personas_by_id[key.persona_id]
        row = rows_by_scenario_id[key.scenario_id]
        request = InferenceRequest(
            request_id=build_experiment_request_id(key),
            prompt=build_experiment_prompt(
                row,
                config.dataset_schema,
                config.prompt_template,
            ),
            system_prompt=persona.instruction,
            persona=render_persona_trait(row, config.dataset_schema, persona),
            model_config_id=key.model_config_id,
            metadata={
                "experiment_id": key.experiment_id,
                "scenario_id": key.scenario_id,
                "persona_id": key.persona_id,
                "model_config_id": key.model_config_id,
            },
            response_format=response_format,
        )
        requests.append(request)
    return requests


def preview_experiment_batch(
    dataset: pd.DataFrame,
    config: ExperimentConfig,
    orchestrator: InferenceOrchestrator,
    *,
    batch_number: int = 1,
    completed_keys: Collection[ExperimentJobKey] = (),
) -> InferenceBatchPreview:
    """Preview one pending experiment batch without performing inference."""

    requests = build_experiment_requests(
        dataset,
        config,
        completed_keys=completed_keys,
    )
    return orchestrator.preview_batch(
        requests,
        config.inference,
        batch_number=batch_number,
    )


def _validate_completed_keys(
    completed_keys: Collection[ExperimentJobKey],
) -> set[ExperimentJobKey]:
    if isinstance(completed_keys, (str, bytes, bytearray)) or not isinstance(
        completed_keys,
        Collection,
    ):
        raise ExperimentIdentityError(
            "completed_keys must be a collection of ExperimentJobKey values"
        )
    for key in completed_keys:
        if not isinstance(key, ExperimentJobKey):
            raise ExperimentIdentityError(
                "completed_keys must contain only ExperimentJobKey values"
            )
    return set(completed_keys)
