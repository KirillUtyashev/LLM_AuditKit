"""Regression coverage for small template-generation review findings."""

import pytest

from llm_auditkit.templates import TemplateResponseParseError
from llm_auditkit.templates.parsing import validate_template_contents
from llm_auditkit.templates.prompts import build_template_prompt

from .helpers import config


def test_generated_template_with_nul_is_rejected():
    with pytest.raises(TemplateResponseParseError, match="NUL"):
        validate_template_contents(
            ["{{name}} {{address}} before\x00after"], ["name", "address"]
        )


def test_explicit_context_mapping_wins_over_same_named_source_column():
    prompt = build_template_prompt(
        {"job_text": "job", "city": "Vancouver", "city_name": "Toronto"}, config()
    )
    assert "in Toronto." in prompt
    assert "Vancouver" not in prompt
