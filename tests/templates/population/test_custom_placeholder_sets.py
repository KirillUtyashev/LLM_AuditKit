"""Verify researcher-defined label sets against literal expected resumes."""

import pandas as pd
import pytest

from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


# Each entry names a label, its payload column, and the value chosen for one form.
_LAB_FIELDS = (
    ("Bay", "work_area", "West wing"),
    ("bay", "bench_code", "B-07"),
    ("_tool2", "instrument", "calipers"),
    ("lot8", "lot_code", "L-21"),
    ("finish", "surface", "matte"),
    ("side_A", "sample_side", "left"),
    ("Gauge", "wire_size", "16 AWG"),
    ("sample_N", "specimen", "copper"),
    ("Mark3", "stamp", "delta"),
    ("rack", "rack_code", "R-04"),
)


@pytest.mark.parametrize(
    ("label_count", "log_details", "expected_details"),
    [
        (3, "", ""),
        (6, "\n{{lot8}}: {{finish}}, {{side_A}}.", "\nL-21: matte, left."),
        (
            10,
            "\n{{lot8}}: {{finish}}, {{side_A}}."
            "\n{{sample_N}} ({{Gauge}}), marked {{Mark3}} on {{rack}}.",
            "\nL-21: matte, left.\ncopper (16 AWG), marked delta on R-04.",
        ),
    ],
    ids=["three-labels", "six-labels", "ten-labels"],
)
def test_custom_labels_follow_each_matched_form(
    label_count: int, log_details: str, expected_details: str,
) -> None:
    fields = _LAB_FIELDS[:label_count]
    config = TemplatePopulationConfig(
        template_columns={"log": "work_log", "note": "handoff"},
        placeholder_columns={label: column for label, column, _ in fields},
    )
    templates = pd.DataFrame({
        "scenario_id": ["assembly", "intake"],
        "Text": ["Hire an assembly technician.", "Hire an intake technician."],
        "work_log": [
            "{{bay}} in {{Bay}}: {{_tool2}}. Return to {{Bay}}." + log_details,
            "Station {{bay}}.",
        ],
        "handoff": ["Packed {{_tool2}}.", "Assigned to {{Bay}}."],
    })
    replacements = pd.DataFrame([
        {
            "scenario_id": "assembly", "template_id": "log",
            "candidate_id": "hazel", "candidate_order": 2,
            **{column: value for _, column, value in fields},
        },
        {
            "scenario_id": "assembly", "template_id": "note",
            "candidate_id": "alder", "candidate_order": 1,
            "instrument": "forceps", "work_area": "",
        },
        {
            "scenario_id": "intake", "template_id": "log",
            "candidate_id": "willow", "candidate_order": 1,
            "bench_code": "Z-02",
        },
        {
            "scenario_id": "intake", "template_id": "note",
            "candidate_id": "larch", "candidate_order": 2,
            "work_area": "East wing",
        },
    ], dtype=object)

    actual = TemplatePopulator().populate(templates, replacements, config)

    assert actual[["candidate_count", "resume_1", "resume_2"]].values.tolist() == [
        [
            2,
            "Packed forceps.",
            "B-07 in West wing: calipers. Return to West wing." + expected_details,
        ],
        [2, "Station Z-02.", "Assigned to East wing."],
    ]
