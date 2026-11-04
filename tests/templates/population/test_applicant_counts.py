"""Applicant counts and numeric slot order through the public population API."""

import pandas as pd
import pytest

from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


# Explicit template ID, storage column, and applicant ID, in template-map order.
FORMS = (
    ("letter", "draft_17", "cedar"),
    ("profile", "draft_10", "birch"),
    ("essay", "draft_31", "elm"),
    ("statement", "draft_8", "ash"),
    ("report", "draft_25", "pine"),
    ("entry", "draft_12", "alder"),
    ("note", "draft_19", "beech"),
    ("survey", "draft_3", "oak"),
    ("sample", "draft_11", "maple"),
    ("outline", "draft_2", "spruce"),
    ("summary", "draft_9", "aspen"),
)


@pytest.fixture(scope="module")
def populator() -> TemplatePopulator:
    return TemplatePopulator()


@pytest.mark.parametrize(
    "form_indices_by_slot",
    [
        pytest.param((0,), id="one"),
        pytest.param((3, 0, 4, 2, 1), id="five"),
        pytest.param((8, 4, 2, 7, 3, 6, 0, 9, 1, 5), id="ten"),
        pytest.param((7, 3, 0, 6, 4, 10, 1, 5, 9, 2, 8), id="eleven"),
    ],
)
def test_configured_applicant_count_and_slot_alignment(
    populator: TemplatePopulator, form_indices_by_slot: tuple[int, ...],
) -> None:
    forms = FORMS[:len(form_indices_by_slot)]
    config = TemplatePopulationConfig(
        template_columns={form_id: column for form_id, column, _ in forms},
        placeholder_columns={"entry": "response"},
    )
    sources, assignments, expected_rows = [], [], []
    scenarios = (("west", 52, form_indices_by_slot), ("east", 19, form_indices_by_slot[::-1]))
    for scenario, office_code, slot_plan in scenarios:
        source = {
            "scenario_id": scenario, "job_id": "shared-job",
            "office_code": office_code, "Text": "Hire an editor.",
        }
        for form_id, column, _ in forms:
            source[column] = f"{scenario} {form_id} / " + "{{entry}}"
        sources.append(source)

        expected = {**source, "candidate_count": len(forms)}
        for slot, form_index in enumerate(slot_plan, start=1):
            form_id, column, applicant_id = forms[form_index]
            response = f"{applicant_id} writes for {scenario}"
            reviewer = f"{scenario} desk {form_id}"
            assignments.append({
                "scenario_id": scenario, "template_id": form_id, "candidate_id": applicant_id,
                "candidate_order": slot, "reviewer": reviewer, "response": response,
            })
            expected.update({
                f"resume_{slot}": f"{scenario} {form_id} / {response}",
                f"candidate_{slot}_id": applicant_id,
                f"candidate_{slot}_template_id": form_id,
                f"candidate_{slot}_template_column": column,
                f"candidate_{slot}_reviewer": reviewer,
                f"candidate_{slot}_response": response,
            })
        expected_rows.append(expected)

    # This input order differs from both template-map order and candidate_order.
    replacements = pd.DataFrame(assignments[1::2] + assignments[::2])
    result = populator.populate(pd.DataFrame(sources), replacements, config)

    pd.testing.assert_frame_equal(result, pd.DataFrame(expected_rows), check_dtype=False)
