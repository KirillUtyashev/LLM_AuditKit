"""Deterministic matching, literal filling, and wide output assembly."""

from __future__ import annotations

import pandas as pd

from .exceptions import TemplatePopulationPlaceholderError
from .models import TemplatePopulationConfig
from .parsing import parse_template
from .validation import is_nonblank_string, validate_inputs


class TemplatePopulator:
    """Populate prepared templates using only researcher-supplied values."""

    def populate(
        self,
        templates: pd.DataFrame,
        replacements: pd.DataFrame,
        config: TemplatePopulationConfig,
    ) -> pd.DataFrame:
        """Return complete applicant sets or raise a domain validation error.

        No input/configuration mutation, file access, model calls, value
        generation, or row expansion occurs. Output uses a fresh RangeIndex.
        """
        validated = validate_inputs(templates, replacements, config)
        count = len(config.template_columns)
        output_values: dict[str, list[object]] = {
            column: [] for column in validated.appended_columns
        }
        for source in validated.source_rows:
            scenario_id = source["scenario_id"]
            output_values["candidate_count"].append(count)
            for slot in range(1, count + 1):
                candidate = validated.candidates[scenario_id][slot]
                template_id = candidate["template_id"]
                column = config.template_columns[template_id]
                context = (
                    f"scenario_id={scenario_id!r}, template_id={template_id!r}, "
                    f"candidate_id={candidate['candidate_id']!r}, column={column!r}"
                )
                parsed = parse_template(source[column], context=context)
                values: dict[str, str] = {}
                for label in parsed.labels:
                    if label not in config.placeholder_columns:
                        raise TemplatePopulationPlaceholderError(
                            f"{context}: placeholder {label!r} has no column mapping"
                        )
                    value_column = config.placeholder_columns[label]
                    value = candidate[value_column]
                    if not is_nonblank_string(value):
                        raise TemplatePopulationPlaceholderError(
                            f"{context}: placeholder {label!r} requires a nonblank "
                            f"string in payload column {value_column!r}"
                        )
                    values[label] = value
                resume = parsed.render(values)
                if not is_nonblank_string(resume):
                    raise TemplatePopulationPlaceholderError(
                        f"{context}: populated resume must be a nonblank string"
                    )
                output_values[f"resume_{slot}"].append(resume)
                output_values[f"candidate_{slot}_id"].append(candidate["candidate_id"])
                output_values[f"candidate_{slot}_template_id"].append(template_id)
                output_values[f"candidate_{slot}_template_column"].append(column)
                for field in validated.payload_columns:
                    output_values[f"candidate_{slot}_{field}"].append(candidate[field])

        # Object series prevent pandas from coercing mixed scalar payloads (for
        # example large integers plus missing values) during wide assembly.
        additions = pd.DataFrame({
            column: pd.Series(values, dtype="int64" if column == "candidate_count" else object)
            for column, values in output_values.items()
        })
        source_copy = templates.copy(deep=True).reset_index(drop=True)
        return pd.concat([source_copy, additions], axis=1)
