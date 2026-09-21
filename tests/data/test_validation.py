"""Dataset schema validation and optional warning tests."""

from __future__ import annotations

import pandas as pd
import pytest

from llm_auditkit.data import (
    DatasetConfigurationError,
    DatasetSchema,
    DatasetValidationError,
    DatasetValidator,
    MissingOptionalColumnWarning,
)


def test_validator_accepts_required_and_additional_columns() -> None:
    validator = DatasetValidator(
        DatasetSchema(
            required_columns=["job"],
            nonempty_columns=["job"],
        )
    )

    validator.validate(pd.DataFrame({"job": ["Posting"], "extra": ["value"]}))


def test_missing_required_columns_and_empty_required_values_fail() -> None:
    validator = DatasetValidator(
        DatasetSchema(
            required_columns=["job", "city"],
            nonempty_columns=["job"],
        )
    )

    with pytest.raises(DatasetValidationError, match="missing.*'city'"):
        validator.validate(pd.DataFrame({"job": ["Posting"]}))
    with pytest.raises(DatasetValidationError, match="non-empty strings"):
        validator.validate(pd.DataFrame({"job": [" "], "city": ["Toronto"]}))


def test_each_missing_optional_column_emits_an_impact_warning() -> None:
    validator = DatasetValidator(
        DatasetSchema(
            required_columns=["job"],
            optional_columns={
                "year": "historical prompt selection will be unavailable",
                "city": "location-specific prompts will be unavailable",
            },
        )
    )

    with pytest.warns(MissingOptionalColumnWarning) as captured:
        validator.validate(pd.DataFrame({"job": ["Posting"]}))

    messages = [str(warning.message) for warning in captured]
    assert messages == [
        "dataset is missing optional column 'year'; "
        "historical prompt selection will be unavailable",
        "dataset is missing optional column 'city'; "
        "location-specific prompts will be unavailable",
    ]


@pytest.mark.parametrize(
    "schema",
    [
        DatasetSchema(required_columns=[]),
        DatasetSchema(required_columns=["job", "job"]),
        DatasetSchema(required_columns=[" "]),
        DatasetSchema(required_columns=["job"], nonempty_columns=["city"]),
        DatasetSchema(
            required_columns=["job"],
            optional_columns={"job": "duplicate role"},
        ),
        DatasetSchema(required_columns=["scenario_id"]),
        DatasetSchema(
            required_columns=["job"],
            optional_columns={"year": " "},
        ),
    ],
)
def test_invalid_dataset_schemas_are_rejected(schema: DatasetSchema) -> None:
    with pytest.raises(DatasetConfigurationError):
        DatasetValidator(schema)


def test_mutated_schema_is_revalidated() -> None:
    schema = DatasetSchema(required_columns=["job"])
    validator = DatasetValidator(schema)
    schema.required_columns.append("job")

    with pytest.raises(DatasetConfigurationError, match="unique"):
        validator.validate(pd.DataFrame({"job": ["Posting"]}))
