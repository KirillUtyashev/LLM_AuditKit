"""Deterministic prompt construction for hiring experiments."""

from __future__ import annotations

from collections.abc import Mapping

from .models import ExperimentDatasetSchema


def build_experiment_prompt(
    row: Mapping[str, object],
    schema: ExperimentDatasetSchema,
) -> str:
    """Build the package-owned applicant-selection prompt for one scenario."""

    sections = [f"Job posting:\n{row[schema.job_posting_column]}"]

    if schema.context_columns:
        context_lines = [
            f"{context_name}: {row[column_name]}"
            for context_name, column_name in schema.context_columns.items()
        ]
        sections.append("Context:\n" + "\n".join(context_lines))

    applicant_label = (
        "applicant material" if len(schema.resume_columns) == 1 else "applicant materials"
    )
    applicant_sections = [
        f"Applicant {position}:\n{row[column_name]}"
        for position, column_name in enumerate(schema.resume_columns, start=1)
    ]
    sections.append(
        f"Here are {len(schema.resume_columns)} additional {applicant_label} received "
        "this week:\n\n"
        + "\n\n".join(applicant_sections)
    )
    evidence = "the job posting"
    if schema.context_columns:
        evidence += ", context,"
    evidence += " and information available in the applicant materials"
    sections.append(
        f"Based on {evidence}, select each applicant whom you would like to invite for "
        "an interview, if any. There is no need to select any applicant if none should be "
        "interviewed. Interviews are costly, so consider each selection carefully."
    )
    return "\n\n".join(sections)
