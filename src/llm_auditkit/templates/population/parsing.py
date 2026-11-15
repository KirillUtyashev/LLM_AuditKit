"""Parse source placeholders and render their already validated literal values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .exceptions import TemplatePopulationPlaceholderError


_LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class _Placeholder:
    label: str


@dataclass(frozen=True)
class ParsedTemplate:
    """Immutable source tokens with distinct labels in first-occurrence order."""

    labels: tuple[str, ...]
    _parts: tuple[str | _Placeholder, ...] = field(repr=False)

    def render(self, values: Mapping[str, str]) -> str:
        """Insert validated values once, without inspecting the resulting text."""

        return "".join(
            values[part.label] if isinstance(part, _Placeholder) else part
            for part in self._parts
        )


def parse_template(source: str, *, context: str) -> ParsedTemplate:
    """Parse a validated source string, reporting zero-based character offsets.

    Only a backslash immediately followed by a doubled delimiter escapes it.
    Other backslashes remain literal, including one before another backslash.
    Malformed-source diagnostics omit source text and invalid label contents.
    """

    parts: list[str | _Placeholder] = []
    literal: list[str] = []
    labels: dict[str, None] = {}
    offset = 0

    while offset < len(source):
        if source.startswith((r"\{{", r"\}}"), offset):
            literal.append(source[offset + 1 : offset + 3])
            offset += 3
        elif source.startswith("{{", offset):
            if literal:
                parts.append("".join(literal))
                literal.clear()
            opening_offset = offset
            label_start = offset + 2
            offset = label_start
            while offset < len(source):
                if source.startswith((r"\{{", r"\}}"), offset):
                    offset += 3
                elif source.startswith("}}", offset):
                    label = source[label_start:offset]
                    if _LABEL.fullmatch(label) is None:
                        raise TemplatePopulationPlaceholderError(
                            f"{context}: invalid placeholder label at character "
                            f"offset {opening_offset}"
                        )
                    parts.append(_Placeholder(label))
                    labels.setdefault(label, None)
                    offset += 2
                    break
                else:
                    offset += 1
            else:
                raise TemplatePopulationPlaceholderError(
                    f"{context}: unclosed placeholder at character "
                    f"offset {opening_offset}"
                )
        elif source.startswith("}}", offset):
            raise TemplatePopulationPlaceholderError(
                f"{context}: unexpected closing delimiter at character "
                f"offset {offset}"
            )
        else:
            literal.append(source[offset])
            offset += 1

    if literal:
        parts.append("".join(literal))
    return ParsedTemplate(labels=tuple(labels), _parts=tuple(parts))
