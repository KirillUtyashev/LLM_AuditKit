"""Shared synthetic inputs for template-generation tests."""

from __future__ import annotations

import pandas as pd

from llm_auditkit.inference import InferenceConfig, ModelConfig
from llm_auditkit.templates import (
    TemplateDatasetSchema,
    TemplateGenerationConfig,
)


def dataset(count: int = 3, *, supplied_ids: bool = True) -> pd.DataFrame:
    values: dict[str, list[object]] = {
        "job_text": [f"Synthetic job {position}" for position in range(1, count + 1)],
        "city_name": ["Toronto", "Montreal", "Birmingham"][:count],
        "code": [f"00{position}" for position in range(1, count + 1)],
    }
    if supplied_ids:
        values["scenario_id"] = [
            f"scenario-{position}" for position in range(1, count + 1)
        ]
    return pd.DataFrame(values)


def config(
    *,
    templates_per_scenario: int = 2,
    batch_size: int = 2,
    save_after_each_result: bool = True,
) -> TemplateGenerationConfig:
    return TemplateGenerationConfig(
        templates_per_scenario=templates_per_scenario,
        dataset_schema=TemplateDatasetSchema(
            job_posting_column="job_text",
            context_columns={"city": "city_name"},
        ),
        prompt_template=(
            "Generate {templates_per_scenario} distinct resume templates for "
            "{job_posting} in {city}. Preserve every token in "
            "{required_placeholders}."
        ),
        system_prompt_template="You are a resume agency serving {city}.",
        required_placeholders=["name", "address"],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    config_id="template-model-v1",
                    provider="test",
                    model="test-model",
                    parameters={"temperature": 0},
                )
            ],
            batch_size=batch_size,
        ),
        model_config_id="template-model-v1",
        save_after_each_result=save_after_each_result,
    )


def template_text(scenario_id: str, position: int) -> str:
    return (
        f"Resume {position} for {scenario_id}\n"
        "Name: {{name}}\nAddress: {{address}}"
    )
