"""Prompt fields and deterministic rendering for template generation."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .exceptions import (
    TemplateGenerationConfigurationError,
    TemplateGenerationDatasetError,
)
from .models import TemplateGenerationConfig


_FIELD = re.compile(r"(?<!\{)\{([A-Za-z][A-Za-z0-9_]*)\}(?!\})")
_PLACEHOLDER = re.compile(
    r"\{\{[ \t]*([A-Za-z][A-Za-z0-9_]*)[ \t]*\}\}"
)


def placeholder_token(name: str) -> str:
    """Return the canonical token for one validated placeholder name."""

    return "{{" + name + "}}"


def template_prompt_fields(template: str, label: str) -> set[str]:
    """Return simple single-brace fields while preserving double-brace tokens."""

    if not isinstance(template, str) or not template.strip():
        raise TemplateGenerationConfigurationError(
            f"{label} must be a non-empty string"
        )
    fields = set(_FIELD.findall(template))
    remainder = _FIELD.sub("", _PLACEHOLDER.sub("", template))
    if "{" in remainder or "}" in remainder:
        raise TemplateGenerationConfigurationError(
            f"{label} contains invalid brace syntax"
        )
    return fields


def build_template_prompt(
    row: Mapping[str, object],
    config: TemplateGenerationConfig,
) -> str:
    """Render one user prompt from a source scenario and generation config."""

    return _render(
        config.prompt_template,
        row,
        config,
        "prompt_template",
    )


def build_template_system_prompt(
    row: Mapping[str, object],
    config: TemplateGenerationConfig,
) -> str | None:
    """Render the optional ordinary system prompt for one source scenario."""

    if config.system_prompt_template is None:
        return None
    return _render(
        config.system_prompt_template,
        row,
        config,
        "system_prompt_template",
    )


def available_prompt_fields(
    source_columns: set[str],
    config: TemplateGenerationConfig,
) -> set[str]:
    """Return fields made available by source data and configured aliases."""

    return (
        source_columns
        | set(config.dataset_schema.context_columns)
        | {"job_posting", "templates_per_scenario", "required_placeholders"}
    )


def _render(
    template: str,
    row: Mapping[str, object],
    config: TemplateGenerationConfig,
    label: str,
) -> str:
    fields = template_prompt_fields(template, label)
    values = dict(row)
    values["job_posting"] = row[config.dataset_schema.job_posting_column]
    values.update(
        {
            alias: row[column]
            for alias, column in config.dataset_schema.context_columns.items()
        }
    )
    values["templates_per_scenario"] = config.templates_per_scenario
    values["required_placeholders"] = ", ".join(
        placeholder_token(name) for name in config.required_placeholders
    )

    missing = sorted(fields.difference(values))
    if missing:
        rendered = ", ".join(repr(field) for field in missing)
        raise TemplateGenerationDatasetError(
            f"{label} references unavailable fields: {rendered}"
        )

    def replace(match: re.Match[str]) -> str:
        return str(values[match.group(1)])

    rendered = _FIELD.sub(replace, template)
    if not rendered.strip():
        raise TemplateGenerationDatasetError(f"rendered {label} must not be empty")
    return rendered


def extract_placeholder_names(template: str) -> list[str]:
    """Return placeholder names in occurrence order."""

    return _PLACEHOLDER.findall(template)


def canonicalize_placeholders(template: str) -> str:
    """Remove EDSL/Jinja-added inner whitespace from placeholder tokens."""

    return _PLACEHOLDER.sub(
        lambda match: placeholder_token(match.group(1)),
        template,
    )


def has_valid_placeholder_syntax(template: str) -> bool:
    """Whether every double-brace marker is one complete supported token."""

    position = 0
    while True:
        opening = template.find("{{", position)
        closing = template.find("}}", position)
        if opening == -1 and closing == -1:
            return True
        if closing != -1 and (opening == -1 or closing < opening):
            return False
        match = _PLACEHOLDER.match(template, opening)
        if match is None:
            return False
        position = match.end()
