"""Tests for the source-only template population placeholder language."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from llm_auditkit.templates.population.exceptions import (
    TemplatePopulationPlaceholderError,
)
from llm_auditkit.templates.population.parsing import parse_template


_CONTEXT = "scenario_id='job-a', template_id='application'"


def test_distinct_labels_follow_source_order_and_repeats_reuse_values() -> None:
    parsed = parse_template(
        "{{surname}}, {{name}}; contact {{name}} {{surname}}.",
        context=_CONTEXT,
    )

    assert parsed.labels == ("surname", "name")
    assert parsed.render({"name": "Alex", "surname": "Example"}) == (
        "Example, Alex; contact Alex Example."
    )


@pytest.mark.parametrize("label", ["a", "Z", "_", "_private", "Name_2", "a0129"])
def test_supported_label_grammar(label: str) -> None:
    parsed = parse_template("{{" + label + "}}", context=_CONTEXT)

    assert parsed.labels == (label,)
    assert parsed.render({label: "exact value"}) == "exact value"


def test_labels_are_case_sensitive_and_adjacent_tokens_are_supported() -> None:
    parsed = parse_template("{{Name}}{{name}}", context=_CONTEXT)

    assert parsed.labels == ("Name", "name")
    assert parsed.render({"Name": "A", "name": "B"}) == "AB"


def test_source_escapes_do_not_create_required_labels() -> None:
    parsed = parse_template(
        r"Example: \{{name\}}; {{name}}; \}}; \{{",
        context=_CONTEXT,
    )

    assert parsed.labels == ("name",)
    assert parsed.render({"name": "Alex"}) == (
        "Example: {{name}}; Alex; }}; {{"
    )


def test_other_backslashes_and_single_braces_are_literal() -> None:
    source = r"{name}; \name; \{year\}; \\{{escaped\}}; final" + "\\"
    parsed = parse_template(source, context=_CONTEXT)

    assert parsed.labels == ()
    assert parsed.render({}) == (
        r"{name}; \name; \{year\}; \{{escaped}}; final" + "\\"
    )


def test_literal_text_unicode_and_line_endings_are_preserved() -> None:
    source = "  Résumé\r\n姓名: {{name}}\n{notes} — τέλος  "
    parsed = parse_template(source, context=_CONTEXT)

    assert parsed.render({"name": "  山田\n Zoë  "}) == (
        "  Résumé\r\n姓名:   山田\n Zoë  \n{notes} — τέλος  "
    )


@pytest.mark.parametrize(
    "value",
    [
        "Writes {{notes}} and {examples}",
        "{{}}",
        "{{unclosed",
        "stray }}",
        r"\{{name\}}",
        "{{name}}",
    ],
)
def test_inserted_text_is_never_parsed_or_unescaped(value: str) -> None:
    parsed = parse_template("Start {{name}} / {{name}} end.", context=_CONTEXT)
    values = {"name": value, "notes": "must not be inserted"}

    assert parsed.render(values) == f"Start {value} / {value} end."
    assert values == {"name": value, "notes": "must not be inserted"}


@pytest.mark.parametrize(
    "source",
    [
        "{{}}",
        "{{ name}}",
        "{{name }}",
        "{{name\n}}",
        "{{name.upper()}}",
        "{{name:>4}}",
        "{{first-name}}",
        "{{first.name}}",
        "{{name[0]}}",
        "{{1name}}",
        "{{naïve}}",
        "{{姓名}}",
        "{{{name}}}",
        "{{{{name}}}}",
        "{{outer{{inner}}}}",
        r"{{name\}}later}}",
        r"{{name\{{later}}",
    ],
)
def test_invalid_labels_and_nesting_are_rejected(source: str) -> None:
    with pytest.raises(
        TemplatePopulationPlaceholderError,
        match="invalid placeholder label at character offset 0",
    ):
        parse_template(source, context=_CONTEXT)


@pytest.mark.parametrize("source", ["{{", "{{name", "{{name}", r"{{name\}}"])
def test_unclosed_placeholders_are_rejected(source: str) -> None:
    with pytest.raises(
        TemplatePopulationPlaceholderError,
        match="unclosed placeholder at character offset 0",
    ):
        parse_template(source, context=_CONTEXT)


@pytest.mark.parametrize("source", ["}}", "prefix }}", r"\{{name}}", "{{name}}}}"])
def test_unescaped_closing_delimiters_are_rejected(source: str) -> None:
    with pytest.raises(
        TemplatePopulationPlaceholderError,
        match="unexpected closing delimiter",
    ):
        parse_template(source, context=_CONTEXT)


def test_diagnostic_reports_context_and_character_offset_without_source() -> None:
    with pytest.raises(TemplatePopulationPlaceholderError) as caught:
        parse_template("秘\n{{private malformed content}}", context=_CONTEXT)

    assert str(caught.value) == (
        f"{_CONTEXT}: invalid placeholder label at character offset 2"
    )
    assert "private malformed content" not in str(caught.value)


def test_parsed_source_is_immutable_and_reusable() -> None:
    parsed = parse_template("Hello {{name}}.", context=_CONTEXT)

    assert parsed.render({"name": "Alex"}) == "Hello Alex."
    assert parsed.render({"name": "Robin"}) == "Hello Robin."
    assert parsed.labels == ("name",)
    with pytest.raises(FrozenInstanceError):
        parsed.labels = ("different",)  # type: ignore[misc]
