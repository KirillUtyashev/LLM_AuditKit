"""Provider-neutral newspaper OCR inputs and provenance records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from llm_auditkit.inference import InferenceConfig


class OCRException(ValueError):
    """Invalid OCR configuration, source, checkpoint or extraction outcome."""


@dataclass(frozen=True)
class SourceDocument:
    path: str | Path
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.path, (str, Path)) or not str(self.path).strip():
            raise OCRException("source path must be a nonempty string or Path")
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class OCRConfig:
    inference: InferenceConfig
    dpi: int = 300
    language_hints: tuple[str, ...] = ()
    timeout: float = 120
    max_page_characters: int = 40000
    save_after_each_batch: bool = True


@dataclass(frozen=True)
class OCRRunConfig:
    documents: tuple[SourceDocument, ...]
    config: OCRConfig
    output_path: Path
    checkpoint_directory: Path
    mode: str


@dataclass(frozen=True)
class OCRBlock:
    block_id: str
    text: str
    vertices: tuple[tuple[int, int], ...]
    confidence: float


@dataclass(frozen=True)
class OCRPage:
    page_id: str
    width: int
    height: int
    blocks: tuple[OCRBlock, ...]
    raw_response: dict


class OCRBackend(Protocol):
    """Implementations keep their provider SDK objects behind this boundary."""

    def recognize(self, image: bytes, page_id: str, config: OCRConfig) -> OCRPage: ...

    async def recognize_async(
        self, image: bytes, page_id: str, config: OCRConfig,
    ) -> OCRPage: ...


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def identity(kind: str, value: object) -> str:
    return kind + ":" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
