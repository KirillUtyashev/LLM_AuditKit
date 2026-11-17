"""Typed resume parts and deterministic rendering of researcher-owned slots."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from .exceptions import TemplateResponseParseError
from .prompts import placeholder_token


class _StrictObject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _TextPart(_StrictObject):
    text: str = Field(min_length=1, description="Literal resume prose or formatting; no double-brace tokens")


@lru_cache(maxsize=128)
def template_parts_model(count: int, names: tuple[str, ...]) -> type[BaseModel]:
    """Build an object schema with N resumes and only configured field names."""

    field_part = create_model(
        "ResumeFieldPart", __base__=_StrictObject,
        field=(Literal[names], Field(description="Reference only; never supply a value")),
    )
    resume = create_model(
        "ResumeParts", __base__=_StrictObject,
        parts=(list[Union[_TextPart, field_part]], Field(min_length=1)),
    )
    return create_model(
        "ResumeTemplates", __base__=_StrictObject,
        templates=(list[resume], Field(min_length=count, max_length=count)),
    )


def render_template_parts(content: object, count: int, names: list[str]) -> list[str]:
    """Render only validated slot references; never infer, fill or repair values."""

    model = template_parts_model(count, tuple(names))
    try:
        parsed = model.model_validate(content, strict=True).model_dump(mode="json")
    except ValidationError as error:
        # Do not embed provider output or private resume text in the error.
        raise TemplateResponseParseError("template parts do not match the configured schema") from error
    rendered = []
    for resume in parsed["templates"]:
        pieces = []
        found = set()
        literal_tail = ""
        for part in resume["parts"]:
            if "field" in part:
                found.add(part["field"])
                pieces.append(placeholder_token(part["field"]))
                literal_tail = ""
            else:
                text = part["text"]
                if "{{" in literal_tail + text or "}}" in literal_tail + text:
                    raise TemplateResponseParseError(
                        "literal text must not contain double-brace tokens; use field parts"
                    )
                pieces.append(text)
                literal_tail = text[-1:]
        missing = set(names).difference(found)
        if missing:
            raise TemplateResponseParseError(
                "template parts are missing required fields: " + ", ".join(sorted(missing))
            )
        rendered.append("".join(pieces).strip())
    return rendered
