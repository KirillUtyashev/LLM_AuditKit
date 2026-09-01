"""Domain models for hiring experiment execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from llm_auditkit.inference import InferenceConfig

from .exceptions import ExperimentIdentityError


@dataclass(slots=True)
class Persona:
    """Stable persona supplied as an inference system prompt."""

    id: str
    name: str
    description: str


@dataclass(slots=True)
class ExperimentDatasetSchema:
    """Map semantic experiment inputs to DataFrame columns."""

    scenario_id_column: str
    job_posting_column: str
    resume_columns: list[str]
    context_columns: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExperimentConfig:
    """Configuration for one logical hiring experiment."""

    experiment_id: str
    dataset_schema: ExperimentDatasetSchema
    personas: list[Persona]
    inference: InferenceConfig
    save_after_each_batch: bool = True


@dataclass(frozen=True, slots=True)
class ExperimentJobKey:
    """Durable identity for one scenario, persona, and model combination."""

    experiment_id: str
    scenario_id: str
    persona_id: str
    model_config_id: str


def build_experiment_request_id(key: ExperimentJobKey) -> str:
    """Derive a deterministic collision-resistant request ID from a job key."""

    if not isinstance(key, ExperimentJobKey):
        raise ExperimentIdentityError("key must be an ExperimentJobKey")

    values = (
        key.experiment_id,
        key.scenario_id,
        key.persona_id,
        key.model_config_id,
    )
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ExperimentIdentityError(
            "experiment job key fields must be non-empty strings"
        )

    canonical_key = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_key).hexdigest()
    return f"experiment-request:{digest}"
