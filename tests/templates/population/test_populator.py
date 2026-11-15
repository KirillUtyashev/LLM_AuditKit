"""Contract tests for matching, validation, and complete population outputs."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

from llm_auditkit.templates.population import (
    TemplatePopulationConfig,
    TemplatePopulationConfigurationError,
    TemplatePopulationDatasetError,
    TemplatePopulationError,
    TemplatePopulationPlaceholderError,
    TemplatePopulator,
)


def _config(**changes: object) -> TemplatePopulationConfig:
    values: dict[str, object] = {
        "template_columns": {"application": "template_1", "resume": "template_2"},
        "placeholder_columns": {
            "name": "full_name",
            "school": "school",
            "start_month": "start_month",
            "end_month": "end_month",
            "credential": "credential",
            "skill": "skill",
        },
    }
    values.update(changes)
    return TemplatePopulationConfig(**values)  # type: ignore[arg-type]


def _templates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": ["clerk-set-a", "assistant-set-a"],
            "job_id": ["job-clerk", "job-assistant"],
            "Text": ["Hire a records clerk.", "Hire a laboratory assistant."],
            "template_1": [
                "Application: {{name}}. Education: {{school}}. Signed: {{name}}.",
                "Application: {{name}}. Training: {{school}} ({{credential}}). Signed: {{name}}.",
            ],
            "template_2": [
                "Resume: {{name}}. Experience: {{start_month}} to {{end_month}}.",
                "Resume: {{name}}. Skills: {{skill}}.",
            ],
        },
        dtype=object,
    )


def _replacements() -> pd.DataFrame:
    # Interleaved scenarios and reverse template/slot order are intentional.
    return pd.DataFrame(
        [
            ["clerk-set-a", "application", "applicant-cedar", 2, "Alex Rowan", "Example College", None, None, None, None, 7],
            ["assistant-set-a", "resume", "applicant-elm", 2, "Jamie Vale", None, None, None, None, "Printing {{lot_code}} labels", 6],
            ["clerk-set-a", "resume", "applicant-birch", 1, "Casey Brook", None, "May 2021", "June 2024", None, None, 8],
            ["assistant-set-a", "application", "applicant-ash", 1, "Morgan Reed", "Sample Institute", None, None, "Laboratory certificate", None, 9],
        ],
        columns=[
            "scenario_id", "template_id", "candidate_id", "candidate_order",
            "full_name", "school", "start_month", "end_month", "credential",
            "skill", "quality_score",
        ],
        dtype=object,
    )


def _expected() -> pd.DataFrame:
    # An explicit oracle for every cell and column in the worked guide.
    values = {
        "scenario_id": ["clerk-set-a", "assistant-set-a"],
        "job_id": ["job-clerk", "job-assistant"],
        "Text": ["Hire a records clerk.", "Hire a laboratory assistant."],
        "template_1": [
            "Application: {{name}}. Education: {{school}}. Signed: {{name}}.",
            "Application: {{name}}. Training: {{school}} ({{credential}}). Signed: {{name}}.",
        ],
        "template_2": [
            "Resume: {{name}}. Experience: {{start_month}} to {{end_month}}.",
            "Resume: {{name}}. Skills: {{skill}}.",
        ],
        "candidate_count": [2, 2],
        "resume_1": [
            "Resume: Casey Brook. Experience: May 2021 to June 2024.",
            "Application: Morgan Reed. Training: Sample Institute (Laboratory certificate). Signed: Morgan Reed.",
        ],
        "candidate_1_id": ["applicant-birch", "applicant-ash"],
        "candidate_1_template_id": ["resume", "application"],
        "candidate_1_template_column": ["template_2", "template_1"],
        "candidate_1_full_name": ["Casey Brook", "Morgan Reed"],
        "candidate_1_school": [None, "Sample Institute"],
        "candidate_1_start_month": ["May 2021", None],
        "candidate_1_end_month": ["June 2024", None],
        "candidate_1_credential": [None, "Laboratory certificate"],
        "candidate_1_skill": [None, None],
        "candidate_1_quality_score": [8, 9],
        "resume_2": [
            "Application: Alex Rowan. Education: Example College. Signed: Alex Rowan.",
            "Resume: Jamie Vale. Skills: Printing {{lot_code}} labels.",
        ],
        "candidate_2_id": ["applicant-cedar", "applicant-elm"],
        "candidate_2_template_id": ["application", "resume"],
        "candidate_2_template_column": ["template_1", "template_2"],
        "candidate_2_full_name": ["Alex Rowan", "Jamie Vale"],
        "candidate_2_school": ["Example College", None],
        "candidate_2_start_month": [None, None],
        "candidate_2_end_month": [None, None],
        "candidate_2_credential": [None, None],
        "candidate_2_skill": [None, "Printing {{lot_code}} labels"],
        "candidate_2_quality_score": [7, 6],
    }
    return pd.DataFrame(values, dtype=object)


def _populate(
    templates: pd.DataFrame | None = None,
    replacements: pd.DataFrame | None = None,
    config: TemplatePopulationConfig | None = None,
) -> pd.DataFrame:
    return TemplatePopulator().populate(
        _templates() if templates is None else templates,
        _replacements() if replacements is None else replacements,
        _config() if config is None else config,
    )


def test_worked_guide_matches_every_output_cell_and_column() -> None:
    actual = _populate()

    pd.testing.assert_frame_equal(actual, _expected(), check_dtype=False)
    assert type(actual.index) is pd.RangeIndex
    assert actual.shape == (2, 28)
    assert actual.at[0, "candidate_1_school"] is None


def test_population_is_deterministic_and_independent_of_indices_and_value_row_order() -> None:
    templates = _templates()
    replacements = _replacements().iloc[[3, 1, 0, 2]]
    templates.index = ["same", "same"]
    replacements.index = [99, 99, -1, -1]
    config = _config(template_columns={"resume": "template_2", "application": "template_1"})
    populator = TemplatePopulator()

    first = populator.populate(templates, replacements, config)
    second = populator.populate(templates, replacements, config)

    pd.testing.assert_frame_equal(first, _expected(), check_dtype=False)
    pd.testing.assert_frame_equal(first, second)


def test_template_row_order_and_all_provenance_are_retained() -> None:
    actual = _populate(templates=_templates().iloc[::-1])

    pd.testing.assert_frame_equal(
        actual, _expected().iloc[::-1].reset_index(drop=True), check_dtype=False,
    )


def test_candidate_order_moves_complete_candidate_bundles_without_changing_identity() -> None:
    templates = _templates().replace({"clerk-set-a": "clerk-set-b"})
    replacements = _replacements().replace({"clerk-set-a": "clerk-set-b"})
    replacements.loc[replacements.scenario_id == "clerk-set-b", "candidate_order"] = [1, 2]

    actual = _populate(templates, replacements)

    assert actual.at[0, "scenario_id"] == "clerk-set-b"
    assert actual.at[0, "resume_1"] == _expected().at[0, "resume_2"]
    assert actual.at[0, "candidate_1_id"] == "applicant-cedar"
    assert actual.at[0, "candidate_1_template_id"] == "application"
    assert actual.at[0, "candidate_1_template_column"] == "template_1"
    assert actual.at[0, "candidate_1_quality_score"] == 7
    assert actual.at[0, "resume_2"] == _expected().at[0, "resume_1"]
    assert actual.at[0, "candidate_2_id"] == "applicant-birch"
    assert actual.at[0, "candidate_2_quality_score"] == 8


def test_candidate_ids_may_recur_across_scenarios() -> None:
    replacements = _replacements()
    replacements.at[3, "candidate_id"] = "applicant-cedar"

    actual = _populate(replacements=replacements)

    assert actual.at[0, "candidate_2_id"] == actual.at[1, "candidate_1_id"]


def test_configured_job_column_is_preserved_without_placeholder_processing() -> None:
    templates = _templates().rename(columns={"Text": "posting"})
    templates.at[0, "posting"] = "Job {{unmapped}} with malformed {{ and literal braces."

    actual = _populate(templates=templates, config=_config(job_posting_column="posting"))

    assert actual.at[0, "posting"] == templates.at[0, "posting"]
    assert "Text" not in actual


def test_one_configured_template_ignores_unselected_template_text_and_uses_no_inferred_mapping() -> None:
    templates = _templates()
    templates["template_2"] = "Unselected {{ malformed text"
    replacements = _replacements().loc[lambda frame: frame.template_id == "application"].copy()
    replacements["candidate_order"] = 1

    actual = _populate(
        templates, replacements,
        _config(template_columns={"application": "template_1"}),
    )

    assert actual.candidate_count.tolist() == [1, 1]
    assert actual.template_2.tolist() == templates.template_2.tolist()
    assert "resume_2" not in actual


def test_fixed_templates_need_matched_applicants_but_no_placeholder_mappings() -> None:
    templates = _templates()
    templates["template_1"] = "Plain {name} text."
    templates["template_2"] = r"Literal \{{name\}}."

    actual = _populate(templates=templates, config=_config(placeholder_columns={}))

    assert actual.at[0, "resume_1"] == "Literal {{name}}."
    assert actual.at[0, "resume_2"] == "Plain {name} text."


def test_required_labels_are_template_specific_and_unused_mappings_allow_missing_cells() -> None:
    replacements = _replacements()
    replacements["unused_value"] = pd.Series([None, pd.NA, "", "  "], dtype=object)
    mappings = dict(_config().placeholder_columns)
    mappings["unused"] = "unused_value"

    actual = _populate(replacements=replacements, config=_config(placeholder_columns=mappings))

    assert actual.at[0, "candidate_2_unused_value"] is None
    assert actual.at[1, "candidate_2_unused_value"] is pd.NA
    assert actual.at[0, "candidate_1_unused_value"] == ""
    assert actual.at[1, "candidate_1_unused_value"] == "  "


def test_multiple_labels_can_map_to_one_payload_column() -> None:
    templates = _templates()
    templates["template_1"] = "{{name}} / {{alias}} / {{name}}"
    mappings = dict(_config().placeholder_columns)
    mappings["alias"] = "full_name"

    actual = _populate(templates=templates, config=_config(placeholder_columns=mappings))

    assert actual.at[0, "resume_2"] == "Alex Rowan / Alex Rowan / Alex Rowan"


def test_structural_label_requires_explicit_payload_mapping() -> None:
    templates = _templates()
    templates["template_1"] = "Display {{candidate_id}}"
    replacements = _replacements()
    replacements["display_id"] = "003"
    mappings = dict(_config().placeholder_columns)
    mappings["candidate_id"] = "display_id"

    actual = _populate(templates, replacements, _config(placeholder_columns=mappings))

    assert actual.at[0, "resume_2"] == "Display 003"
    assert actual.at[0, "candidate_2_id"] == "applicant-cedar"
    assert actual.at[0, "candidate_2_display_id"] == "003"


def test_insertions_are_single_pass_and_preserve_exact_unicode_whitespace_and_braces() -> None:
    replacements = _replacements()
    inserted = "  Zoë\nWrites {{notes}} and {examples}; \\{{name\\}}  "
    replacements.at[0, "full_name"] = inserted

    actual = _populate(replacements=replacements)

    assert actual.at[0, "resume_2"] == f"Application: {inserted}. Education: Example College. Signed: {inserted}."
    assert actual.at[0, "candidate_2_full_name"] == inserted


@pytest.mark.parametrize("value", [None, pd.NA, np.nan, pd.NaT, "", " \t\n", 2024, 3.0, False, np.int64(2024), np.bool_(False)])
def test_required_insertions_are_nonblank_strings(value: object) -> None:
    replacements = _replacements()
    replacements.at[3, "credential"] = value

    with pytest.raises(TemplatePopulationPlaceholderError):
        _populate(replacements=replacements)


def test_missing_label_is_not_satisfied_by_equal_mapping_count() -> None:
    mappings = dict(_config().placeholder_columns)
    del mappings["school"]
    mappings["unused_school"] = "school"

    with pytest.raises(TemplatePopulationPlaceholderError, match="school"):
        _populate(config=_config(placeholder_columns=mappings))


@pytest.mark.parametrize("source", ["{{ name }}", "{{}}", "{{name", "name}}", "{{{name}}}"])
def test_malformed_source_tokens_fail_through_public_api(source: str) -> None:
    templates = _templates()
    templates.at[0, "template_1"] = source

    with pytest.raises(TemplatePopulationPlaceholderError):
        _populate(templates=templates)


@pytest.mark.parametrize(
    "changes",
    [
        {"template_columns": {}},
        {"template_columns": []},
        {"template_columns": {"": "template_1"}},
        {"template_columns": {1: "template_1"}},
        {"template_columns": {"application": " "}},
        {"template_columns": {"application": 1}},
        {"template_columns": {"first": "template_1", "second": "template_1"}},
        {"template_columns": {"first": "scenario_id"}},
        {"template_columns": {"first": "Text"}},
        {"job_posting_column": "scenario_id"},
        {"job_posting_column": "template_1"},
        {"job_posting_column": " "},
        {"job_posting_column": None},
        {"placeholder_columns": []},
        {"placeholder_columns": {"bad-label": "full_name"}},
        {"placeholder_columns": {"": "full_name"}},
        {"placeholder_columns": {"name": " "}},
        {"placeholder_columns": {"name": 1}},
    ],
)
def test_invalid_configuration_is_a_domain_configuration_error(changes: dict[str, object]) -> None:
    with pytest.raises(TemplatePopulationConfigurationError):
        _populate(config=_config(**changes))


def test_configuration_requires_the_public_model() -> None:
    with pytest.raises(TemplatePopulationConfigurationError):
        TemplatePopulator().populate(_templates(), _replacements(), {})  # type: ignore[arg-type]


@pytest.mark.parametrize("column", ["scenario_id", "template_id", "candidate_id", "candidate_order"])
def test_placeholder_mapping_cannot_target_structural_fields(column: str) -> None:
    with pytest.raises(TemplatePopulationConfigurationError, match=column):
        _populate(config=_config(placeholder_columns={"name": column}))


def test_mapping_interface_accepts_read_only_mappings() -> None:
    config = _config(
        template_columns=MappingProxyType(dict(_config().template_columns)),
        placeholder_columns=MappingProxyType(dict(_config().placeholder_columns)),
    )

    pd.testing.assert_frame_equal(_populate(config=config), _expected(), check_dtype=False)


@pytest.mark.parametrize("table_name", ["templates", "replacements"])
@pytest.mark.parametrize("invalid", [[], {}, "input.csv", None])
def test_inputs_must_be_dataframes(table_name: str, invalid: object) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements(), "config": _config()}
    inputs[table_name] = invalid

    with pytest.raises(TemplatePopulationDatasetError):
        TemplatePopulator().populate(**inputs)  # type: ignore[arg-type]


@pytest.mark.parametrize("table_name", ["templates", "replacements"])
def test_empty_inputs_are_rejected_even_with_correct_headers(table_name: str) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements()}
    inputs[table_name] = inputs[table_name].iloc[0:0]

    with pytest.raises(TemplatePopulationDatasetError):
        _populate(**inputs)


@pytest.mark.parametrize("table_name", ["templates", "replacements"])
@pytest.mark.parametrize("bad_column", ["", "  ", 10, None, ("nested", "label")])
def test_column_names_must_be_nonblank_strings(table_name: str, bad_column: object) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements()}
    columns = list(inputs[table_name].columns)
    columns[-1] = bad_column
    inputs[table_name].columns = columns

    with pytest.raises(TemplatePopulationDatasetError):
        _populate(**inputs)


@pytest.mark.parametrize("table_name", ["templates", "replacements"])
def test_duplicate_column_names_are_rejected(table_name: str) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements()}
    columns = list(inputs[table_name].columns)
    columns[-1] = columns[-2]
    inputs[table_name].columns = columns

    with pytest.raises(TemplatePopulationDatasetError):
        _populate(**inputs)


@pytest.mark.parametrize(
    ("table_name", "column"),
    [
        ("templates", "scenario_id"), ("templates", "Text"),
        ("templates", "template_1"), ("templates", "template_2"),
        ("replacements", "scenario_id"), ("replacements", "template_id"),
        ("replacements", "candidate_id"), ("replacements", "candidate_order"),
        ("replacements", "school"),
    ],
)
def test_every_required_column_must_exist(table_name: str, column: str) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements()}
    inputs[table_name] = inputs[table_name].drop(columns=[column])

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(**inputs)


def test_unused_mapping_targets_must_still_exist() -> None:
    mappings = dict(_config().placeholder_columns)
    mappings["unused"] = "absent_payload"

    with pytest.raises(TemplatePopulationDatasetError, match="absent_payload"):
        _populate(config=_config(placeholder_columns=mappings))


@pytest.mark.parametrize("column", ["scenario_id", "Text", "template_1", "template_2"])
@pytest.mark.parametrize("value", [None, "", " \n", 1])
def test_template_identity_and_text_columns_require_nonblank_strings(column: str, value: object) -> None:
    templates = _templates()
    templates.at[0, column] = value

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(templates=templates)


@pytest.mark.parametrize("column", ["scenario_id", "template_id", "candidate_id"])
@pytest.mark.parametrize("value", [None, "", " \n", 1])
def test_replacement_identifiers_require_nonblank_strings(column: str, value: object) -> None:
    replacements = _replacements()
    replacements.at[0, column] = value

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(replacements=replacements)


def test_duplicate_source_scenarios_are_ambiguous() -> None:
    templates = pd.concat([_templates(), _templates().iloc[[0]]], ignore_index=True)

    with pytest.raises(TemplatePopulationDatasetError, match="scenario"):
        _populate(templates=templates)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_scenario", "unknown_template", "duplicate_template", "duplicate_candidate"])
def test_matching_rejects_missing_extra_unknown_and_ambiguous_records(change: str) -> None:
    replacements = _replacements()
    if change == "missing":
        replacements = replacements.iloc[1:]
    elif change == "duplicate":
        replacements = pd.concat([replacements, replacements.iloc[[0]]], ignore_index=True)
    elif change == "unknown_scenario":
        replacements.at[0, "scenario_id"] = "unmatched-scenario"
    elif change == "unknown_template":
        replacements.at[0, "template_id"] = "unmatched-template"
    elif change == "duplicate_template":
        replacements.at[0, "template_id"] = "resume"
    else:
        replacements.at[0, "candidate_id"] = "applicant-birch"

    with pytest.raises(TemplatePopulationDatasetError):
        _populate(replacements=replacements)


@pytest.mark.parametrize("value", [0, -1, 3, "2", True, np.bool_(True), 2.0, np.float64(2.0), None, pd.NA])
def test_candidate_order_requires_integer_permutation(value: object) -> None:
    replacements = _replacements()
    replacements.at[0, "candidate_order"] = value

    with pytest.raises(TemplatePopulationDatasetError, match="candidate_order"):
        _populate(replacements=replacements)


def test_duplicate_candidate_orders_are_rejected() -> None:
    replacements = _replacements()
    replacements.at[0, "candidate_order"] = 1

    with pytest.raises(TemplatePopulationDatasetError, match="candidate_order"):
        _populate(replacements=replacements)


def test_numpy_integer_orders_and_nullable_integer_metadata_are_supported() -> None:
    replacements = _replacements()
    replacements["candidate_order"] = pd.Series([2, 2, 1, 1], dtype="Int64")
    replacements["covariate"] = pd.Series([np.int64(7), pd.NA, np.int64(8), np.int64(9)], dtype="Int64")

    actual = _populate(replacements=replacements)

    assert actual.at[0, "candidate_2_covariate"] == 7
    assert actual.at[1, "candidate_2_covariate"] is pd.NA
    assert actual.at[0, "candidate_1_covariate"] == 8


def test_exact_nonblank_identifiers_are_preserved_without_trimming() -> None:
    templates = _templates().replace({"clerk-set-a": " 003 "})
    replacements = _replacements().replace({"clerk-set-a": " 003 "})
    replacements.at[0, "candidate_id"] = " 0007 "

    actual = _populate(templates, replacements)

    assert actual.at[0, "scenario_id"] == " 003 "
    assert actual.at[0, "candidate_2_id"] == " 0007 "
    replacements.at[0, "scenario_id"] = "003"
    with pytest.raises(TemplatePopulationDatasetError):
        _populate(templates, replacements)


@pytest.mark.parametrize("column", ["resume_1", "candidate_count", "candidate_1_id", "candidate_2_full_name"])
def test_source_columns_cannot_collide_with_generated_output(column: str) -> None:
    templates = _templates()
    templates[column] = "already present"

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(templates=templates)


@pytest.mark.parametrize("column", ["id", "template_column"])
def test_payload_columns_cannot_collide_with_candidate_identity_fields(column: str) -> None:
    replacements = _replacements()
    replacements[column] = "already present"

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(replacements=replacements)


@pytest.mark.parametrize(
    "column",
    [
        "experiment_id", "persona_id", "model_config_id", "request_id", "persona_name",
        "model", "provider", "persona_instruction", "user_prompt", "system_prompt",
        "generated_response", "comment", "picks", "error_type", "error_message",
        "pick1", "pick10", "logprob1", "logprob10",
    ],
)
def test_final_namespace_rejects_experiment_reserved_columns(column: str) -> None:
    templates = _templates()
    templates[column] = None

    with pytest.raises(TemplatePopulationDatasetError, match=column):
        _populate(templates=templates)


def test_reserved_names_are_checked_after_candidate_prefixing_and_with_exact_pattern() -> None:
    templates = _templates()
    templates["pick0"] = "zero"
    templates["logprob01"] = "leading zero"
    templates["pick1_extra"] = "suffix"
    replacements = _replacements()
    replacements["comment"] = "researcher's note"
    replacements["pick1"] = False

    actual = _populate(templates, replacements)

    assert actual.at[0, "pick0"] == "zero"
    assert actual.at[0, "logprob01"] == "leading zero"
    assert actual.at[0, "pick1_extra"] == "suffix"
    assert actual.at[0, "candidate_1_comment"] == "researcher's note"
    assert actual.at[0, "candidate_1_pick1"] is False


@pytest.mark.parametrize(
    "value",
    [
        None, pd.NA, pd.NaT, np.nan, "", " \n", "003", True,
        np.bool_(False), 2**64 + 1, np.int64(-3), np.uint64(2**64 - 1),
        0.25, np.float32(0.5), np.str_("text"), np.datetime64("NaT", "ns"),
    ],
)
def test_allowed_metadata_scalars_and_missingness_are_preserved(value: object) -> None:
    templates = _templates()
    replacements = _replacements()
    templates["source_meta"] = pd.Series([value, None], dtype=object)
    replacements["payload_meta"] = pd.Series([value, None, None, None], dtype=object)

    actual = _populate(templates, replacements)

    for actual_value in [actual.at[0, "source_meta"], actual.at[0, "candidate_2_payload_meta"]]:
        if value is None or value is pd.NA or value is pd.NaT:
            assert actual_value is value
        elif bool(pd.isna(value)):
            assert bool(pd.isna(actual_value))
        else:
            assert actual_value == value
            if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
                assert isinstance(actual_value, (int, np.integer))


@pytest.mark.parametrize("table_name", ["templates", "replacements"])
@pytest.mark.parametrize(
    "value",
    [
        [], {}, (1, 2), {1}, np.array([1]), np.array(1),
        date(2024, 1, 1), datetime(2024, 1, 1), timedelta(days=1),
        pd.Timestamp("2024-01-01"), np.datetime64("2024-01-01"),
        np.inf, -np.inf, complex(1, 2), Decimal("1.5"), object(),
    ],
)
def test_unsupported_metadata_objects_are_rejected(table_name: str, value: object) -> None:
    inputs = {"templates": _templates(), "replacements": _replacements()}
    inputs[table_name]["invalid_meta"] = pd.Series([None] * len(inputs[table_name]), dtype=object)
    inputs[table_name].at[0, "invalid_meta"] = value

    with pytest.raises(TemplatePopulationDatasetError, match="invalid_meta"):
        _populate(**inputs)


@pytest.mark.parametrize("fail", [False, True])
def test_inputs_and_configuration_are_unchanged_on_success_and_failure(fail: bool) -> None:
    templates = _templates()
    replacements = _replacements()
    templates.index = [11, 3]
    replacements.index = [8, 6, 4, 2]
    if fail:
        replacements.at[2, "credential"] = None
    config = _config()
    templates_before = templates.copy(deep=True)
    replacements_before = replacements.copy(deep=True)
    config_before = deepcopy(config)

    if fail:
        with pytest.raises(TemplatePopulationError):
            _populate(templates, replacements, config)
    else:
        actual = _populate(templates, replacements, config)
        actual.at[0, "template_1"] = "Caller edits output"
        actual.at[0, "candidate_2_full_name"] = "Caller edits output"

    pd.testing.assert_frame_equal(templates, templates_before)
    pd.testing.assert_frame_equal(replacements, replacements_before)
    assert config == config_before


def test_placeholder_error_identifies_context_without_disclosing_source_or_values() -> None:
    templates = _templates()
    replacements = _replacements()
    templates.at[0, "template_1"] = "PRIVATE_RESUME_CONTENT {{unknown_label}}"
    replacements.at[0, "full_name"] = "PRIVATE_REPLACEMENT_CONTENT"

    with pytest.raises(TemplatePopulationPlaceholderError) as error:
        _populate(templates, replacements)

    message = str(error.value)
    assert "unknown_label" in message
    assert "clerk-set-a" in message
    assert "application" in message
    assert "PRIVATE_RESUME_CONTENT" not in message
    assert "PRIVATE_REPLACEMENT_CONTENT" not in message


def test_unsupported_value_error_identifies_field_without_dumping_contents() -> None:
    replacements = _replacements()
    replacements.at[0, "school"] = {"PRIVATE_METADATA_CONTENT": "sensitive"}

    with pytest.raises(TemplatePopulationError) as error:
        _populate(replacements=replacements)

    assert "school" in str(error.value)
    assert "PRIVATE_METADATA_CONTENT" not in str(error.value)
    assert "sensitive" not in str(error.value)


def test_public_domain_errors_have_a_common_base() -> None:
    for error_type in [
        TemplatePopulationConfigurationError,
        TemplatePopulationDatasetError,
        TemplatePopulationPlaceholderError,
    ]:
        assert issubclass(error_type, TemplatePopulationError)
