"""Populate two synthetic applicant sets and preview their experiment questions offline."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

# EDSL reads its settings at import. This preview needs neither .env nor token prices.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["EDSL_FETCH_TOKEN_PRICES"] = "False"

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentResultStore,
    ExperimentRunner,
    Persona,
)
from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceOrchestrator,
    ModelConfig,
)
from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


def main() -> None:
    example_dir = Path(__file__).resolve().parent
    templates = pd.read_csv(example_dir / "templates.csv", dtype=str, keep_default_na=False)
    replacements = pd.read_csv(
        example_dir / "replacements.csv", dtype=str, keep_default_na=False, na_values=[""]
    ).astype({"candidate_order": "int64", "quality_score": "Int64"})
    population = TemplatePopulationConfig(
        job_posting_column="Text",
        template_columns={"application": "template_1", "resume": "template_2"},
        placeholder_columns={
            "name": "full_name",
            "school": "school",
            "start_month": "start_month",
            "end_month": "end_month",
            "credential": "credential",
            "skill": "skill",
        },
    )
    populated = TemplatePopulator().populate(templates, replacements, population)

    # Use the same numeric slot order for both the schema and the question.
    slots = range(1, len(population.template_columns) + 1)
    resume_columns = [f"resume_{slot}" for slot in slots]
    applicants = "\n\n".join(
        f"Applicant {slot}: {{{column}}}" for slot, column in enumerate(resume_columns, start=1)
    )
    experiment = ExperimentConfig(
        experiment_id="synthetic-population-preview-v1",
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column=population.job_posting_column,
            resume_columns=resume_columns,
        ),
        prompt_template=(
            f"Job posting: {{job_posting}}\n\n{applicants}\n\n"
            "Would you interview each applicant? Answer Yes or No for each.\n\n"
        ),
        personas=[
            Persona(
                id="reviewer-v1",
                name="Reviewer",
                trait_template="You review job applications.",
                instruction="Evaluate each applicant against the job posting.",
            )
        ],
        inference=InferenceConfig(
            models=[
                ModelConfig(
                    config_id="openai-gpt-4.1-nano-v1",
                    provider="openai",
                    model="gpt-4.1-nano",
                    parameters={"temperature": 0, "logprobs": True},
                )
            ],
            # Both jobs are in this logical batch; each request contains both applicants.
            batch_size=2,
        ),
    )

    # Preview validates the populated DataFrame and renders prompts without running inference.
    with TemporaryDirectory() as directory:
        runner = ExperimentRunner(
            InferenceOrchestrator(EDSLAdapter()),
            ExperimentResultStore(Path(directory) / "preview.csv"),
        )
        first = runner.preview(populated, experiment)
        previews = [first] + [
            runner.preview(populated, experiment, batch_number=batch)
            for batch in range(2, first.total_batches + 1)
        ]

    columns = ["scenario_id"]
    for slot in slots:
        columns.extend([f"candidate_{slot}_id", f"candidate_{slot}_full_name"])
    print(populated[columns].to_string(index=False))
    for preview in previews:
        print(f"\nPreview batch {preview.batch_number}:")
        for prompt in preview.prompts:
            print(f"\n{prompt.user_prompt}")


if __name__ == "__main__":
    main()
