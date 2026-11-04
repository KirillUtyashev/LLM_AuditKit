"""Offline population checks using public, independently expected form examples.

The YAML fixture adapts reference structures to named placeholders. Tests read
only that public fixture; they never load the private reference or derive dates,
candidate assignments, or expected text from a historical population recipe.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from llm_auditkit.templates.population import (
    TemplatePopulationConfig,
    TemplatePopulationPlaceholderError,
    TemplatePopulator,
)


_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "template_population"
    / "reference_structures.yaml"
)
_FAMILIES = (
    "application_1950_1960",
    "school_employment_1970_1980",
    "university_one_job_1990",
    "university_student_job_2000_2002",
    "university_two_jobs_internship_2010_2020",
)
_STRUCTURAL_COLUMNS = (
    "scenario_id", "template_id", "candidate_id", "candidate_order",
)


@pytest.fixture
def reference_data() -> dict:
    with _FIXTURE.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _payload_columns(reference_data: dict) -> list[str]:
    # Materialize the supplied columns, including fields unused by some forms.
    return list(dict.fromkeys([
        *reference_data["placeholder_columns"].values(),
        *(
            column
            for family in reference_data["families"].values()
            for column in family["values"]
        ),
    ]))


def _payload(reference_data: dict, family_name: str) -> dict[str, object]:
    supplied = reference_data["families"][family_name]["values"]
    return {
        column: supplied.get(column)
        for column in _payload_columns(reference_data)
    }


def _single_inputs(
    reference_data: dict, family_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, TemplatePopulationConfig]:
    family = reference_data["families"][family_name]
    templates = pd.DataFrame([{
        "scenario_id": "single-form-set",
        "job_id": "synthetic-records-job",
        "Text": "Hire an assistant for a synthetic records office.",
        "research_note": "Public synthetic form verification.",
        "template_1": family["template"],
    }], dtype=object)
    replacements = pd.DataFrame([{
        "scenario_id": "single-form-set",
        "template_id": "primary",
        "candidate_id": family["candidate_id"],
        "candidate_order": 1,
        **_payload(reference_data, family_name),
    }], dtype=object)
    config = TemplatePopulationConfig(
        template_columns={"primary": "template_1"},
        placeholder_columns=reference_data["placeholder_columns"],
    )
    return templates, replacements, config


def _assert_candidate(
    actual: pd.DataFrame,
    *,
    row: int,
    slot: int,
    family_name: str,
    template_id: str,
    template_column: str,
    reference_data: dict,
) -> None:
    family = reference_data["families"][family_name]
    # Expected resumes are independent literal strings, never rendered here.
    assert actual.at[row, f"resume_{slot}"] == family["expected_resume"]
    assert actual.at[row, f"candidate_{slot}_id"] == family["candidate_id"]
    assert actual.at[row, f"candidate_{slot}_template_id"] == template_id
    assert actual.at[row, f"candidate_{slot}_template_column"] == template_column
    for field, value in _payload(reference_data, family_name).items():
        populated_value = actual.at[row, f"candidate_{slot}_{field}"]
        if value is None:
            assert populated_value is None
        else:
            assert populated_value == value
    assert isinstance(actual.at[row, f"candidate_{slot}_quality_score"], int)


def _assert_columns(
    actual: pd.DataFrame,
    templates: pd.DataFrame,
    replacements: pd.DataFrame,
    count: int,
) -> None:
    expected = [*templates.columns, "candidate_count"]
    payload = [column for column in replacements if column not in _STRUCTURAL_COLUMNS]
    for slot in range(1, count + 1):
        expected.extend([
            f"resume_{slot}",
            f"candidate_{slot}_id",
            f"candidate_{slot}_template_id",
            f"candidate_{slot}_template_column",
            *(f"candidate_{slot}_{field}" for field in payload),
        ])
    assert actual.columns.tolist() == expected


@pytest.mark.parametrize("family_name", _FAMILIES)
def test_reference_form_preserves_exact_multiline_text_and_provenance(
    reference_data: dict, family_name: str,
) -> None:
    templates, replacements, config = _single_inputs(reference_data, family_name)

    actual = TemplatePopulator().populate(templates, replacements, config)

    assert actual.shape[0] == 1
    assert actual.index.equals(pd.RangeIndex(1))
    assert actual.candidate_count.tolist() == [1]
    pd.testing.assert_frame_equal(actual[templates.columns], templates)
    _assert_columns(actual, templates, replacements, count=1)
    _assert_candidate(
        actual, row=0, slot=1, family_name=family_name,
        template_id="primary", template_column="template_1",
        reference_data=reference_data,
    )


def test_explicit_mixed_form_cohort_keeps_all_six_candidate_bundles_aligned(
    reference_data: dict,
) -> None:
    cohort = reference_data["cohort"]
    template_columns = cohort["template_columns"]
    source_rows = []
    replacement_rows = []
    # Only the six researcher-supplied assignments are assembled into tables.
    for job in cohort["jobs"]:
        source = {
            field: job[field]
            for field in ("scenario_id", "job_id", "Text", "research_note")
        }
        for assignment in job["assignments"]:
            family = reference_data["families"][assignment["family"]]
            source[template_columns[assignment["template_id"]]] = family["template"]
            replacement_rows.append({
                "scenario_id": job["scenario_id"],
                "template_id": assignment["template_id"],
                "candidate_id": family["candidate_id"],
                "candidate_order": assignment["candidate_order"],
                **_payload(reference_data, assignment["family"]),
            })
        source_rows.append(source)
    templates = pd.DataFrame(source_rows, columns=[
        "scenario_id", "job_id", "Text", "research_note", *template_columns.values(),
    ], dtype=object)
    replacements = pd.DataFrame(replacement_rows, dtype=object).iloc[[4, 1, 5, 0, 3, 2]]
    templates.index = [71, -9]
    replacements.index = [12, 12, -1, -1, 5, 5]
    config = TemplatePopulationConfig(
        template_columns=template_columns,
        placeholder_columns=reference_data["placeholder_columns"],
    )

    actual = TemplatePopulator().populate(templates, replacements, config)

    assert actual.shape[0] == 2
    assert actual.index.equals(pd.RangeIndex(2))
    assert actual.candidate_count.tolist() == [3, 3]
    pd.testing.assert_frame_equal(
        actual[templates.columns], templates.reset_index(drop=True),
    )
    _assert_columns(actual, templates, replacements, count=3)
    for row, job in enumerate(cohort["jobs"]):
        # The fixture states output order independently of the assignments list.
        for slot, family_name in enumerate(job["expected_families"], start=1):
            assignment = next(
                item for item in job["assignments"] if item["family"] == family_name
            )
            _assert_candidate(
                actual, row=row, slot=slot, family_name=family_name,
                template_id=assignment["template_id"],
                template_column=template_columns[assignment["template_id"]],
                reference_data=reference_data,
            )
    reordered = TemplatePopulator().populate(templates, replacements.iloc[::-1], config)
    pd.testing.assert_frame_equal(actual, reordered)


@pytest.mark.parametrize(
    ("requiring_family", "unaffected_family"),
    [
        ("application_1950_1960", "university_two_jobs_internship_2010_2020"),
        ("university_two_jobs_internship_2010_2020", "application_1950_1960"),
    ],
)
def test_family_specific_date_value_is_required_only_by_its_source_form(
    reference_data: dict, requiring_family: str, unaffected_family: str,
) -> None:
    family = reference_data["families"][requiring_family]
    label = family["missing_required_label"]
    column = reference_data["placeholder_columns"][label]
    assert "{{" + label + "}}" in family["template"]
    templates, replacements, config = _single_inputs(reference_data, requiring_family)
    assert isinstance(replacements.at[0, column], str)
    replacements.at[0, column] = None

    with pytest.raises(TemplatePopulationPlaceholderError) as error:
        TemplatePopulator().populate(templates, replacements, config)

    assert label in str(error.value)
    assert "scenario_id='single-form-set'" in str(error.value)
    assert "template_id='primary'" in str(error.value)
    assert family["candidate_id"] in str(error.value)
    other = reference_data["families"][unaffected_family]
    assert "{{" + label + "}}" not in other["template"]
    templates, replacements, config = _single_inputs(reference_data, unaffected_family)
    assert replacements.at[0, column] is None

    actual = TemplatePopulator().populate(templates, replacements, config)

    assert actual.at[0, "resume_1"] == other["expected_resume"]
    assert actual.at[0, f"candidate_1_{column}"] is None
