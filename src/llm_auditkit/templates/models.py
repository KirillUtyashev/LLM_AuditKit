"""Domain models for resume-template generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_auditkit.inference import InferenceConfig


@dataclass(slots=True)
class TemplateDatasetSchema:
    """Map semantic template-generation inputs to DataFrame columns."""

    job_posting_column: str
    context_columns: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TemplateGenerationConfig:
    """Configuration for one deterministic template-generation plan."""

    templates_per_scenario: int
    dataset_schema: TemplateDatasetSchema
    prompt_template: str
    required_placeholders: list[str]
    inference: InferenceConfig
    model_config_id: str
    system_prompt_template: str | None = None
    save_after_each_result: bool = True


@dataclass(slots=True)
class TemplateOutputRecord:
    """One normalized successful or failed template-generation outcome."""

    scenario_id: str
    request_id: str
    generation_fingerprint: str
    model_config_id: str
    templates: list[str] | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def is_successful(self) -> bool:
        """Whether this record contains templates and no error."""

        return (
            self.templates is not None
            and self.error_type is None
            and self.error_message is None
        )
