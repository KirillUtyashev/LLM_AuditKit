"""Versioned, atomic OCR checkpoints and the scalar CSV export boundary."""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import OCRBlock, OCRException, OCRPage, canonical_json, identity


CSV_COLUMNS = [
    "ad_id", "source_id", "page_id", "page_number", "source_path", "metadata_json",
    "raw_text", "Text", "source_spans_json", "request_id", "model_config_id", "review_required",
]


def validate_page(page: OCRPage, page_id: str) -> None:
    if not isinstance(page, OCRPage) or page.page_id != page_id:
        raise OCRException("OCR page identity does not match the source plan")
    if any(type(value) is not int or value < 0 for value in (page.width, page.height)):
        raise OCRException("OCR page dimensions must be nonnegative integers")
    if page.blocks and (not page.width or not page.height):
        raise OCRException("textual OCR page requires positive dimensions")
    if not isinstance(page.raw_response, dict):
        raise OCRException("raw OCR response must be a dictionary")
    canonical_json(page.raw_response)
    seen = set()
    for block in page.blocks:
        if not isinstance(block, OCRBlock) or not isinstance(block.text, str) or not block.text.strip():
            raise OCRException("OCR blocks require nonempty text")
        if len(block.vertices) != 4 or any(
            len(vertex) != 2 or any(type(value) is not int for value in vertex)
            for vertex in block.vertices
        ):
            raise OCRException("OCR block polygons must have four integer-coordinate vertices")
        if type(block.confidence) not in (int, float) or not math.isfinite(block.confidence) or not 0 <= block.confidence <= 1:
            raise OCRException("OCR block confidence must be between zero and one")
        if block.block_id != identity("block", [page_id, block.text, block.vertices]) or block.block_id in seen:
            raise OCRException("invalid or duplicate content/geometry-based OCR block ID")
        seen.add(block.block_id)


def _atomic(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class OCRStore:
    def __init__(self, checkpoint_directory: str | Path, output_path: str | Path) -> None:
        self.directory = Path(checkpoint_directory).resolve()
        self.output_path = Path(output_path).resolve()

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        acquired = []
        try:
            for lock in (self.directory / ".lock", self.output_path.with_name(self.output_path.name + ".lock")):
                try:
                    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as error:
                    raise OCRException("OCR checkpoint/output is locked; inspect any stale lock before removing it") from error
                os.close(descriptor)
                acquired.append(lock)
            yield self
        finally:
            for lock in reversed(acquired):
                lock.unlink(missing_ok=True)

    def initialize(self, fingerprint: str, sources: list[dict], incremental: bool) -> None:
        expected = {
            "version": 1, "fingerprint": fingerprint, "sources": sources,
            "output_path": str(self.output_path),
        }
        path = self.directory / "manifest.json"
        if path.exists():
            if self._read(path) != expected:
                raise OCRException("checkpoint inputs/configuration differ; use a new checkpoint directory")
        else:
            if any(self.directory.glob("*.json")):
                raise OCRException("checkpoint files exist without a manifest")
            if self.output_path.exists():
                raise OCRException("refusing to overwrite an output CSV without a matching checkpoint manifest")
            if incremental:
                self._write(path, expected)
        self._manifest = expected

    def load(self, page_id: str) -> dict | None:
        path = self._page_path(page_id)
        if not path.exists():
            return None
        record = self._read(path)
        if not isinstance(record, dict) or set(record) != {"version", "page", "outcome"} or record["version"] != 1:
            raise OCRException("invalid page checkpoint schema")
        try:
            raw_page = record["page"]
            page = OCRPage(
                page_id=raw_page["page_id"], width=raw_page["width"], height=raw_page["height"],
                blocks=tuple(OCRBlock(
                    block_id=block["block_id"], text=block["text"],
                    vertices=tuple(tuple(vertex) for vertex in block["vertices"]), confidence=block["confidence"],
                ) for block in raw_page["blocks"]), raw_response=raw_page["raw_response"],
            )
            validate_page(page, page_id)
            record["page"] = page
            return record
        except (KeyError, TypeError, ValueError) as error:
            raise OCRException("invalid or corrupt OCR page checkpoint") from error

    def save(self, record: dict) -> None:
        self._write(self._page_path(record["page"].page_id), {
            "version": 1, "page": asdict(record["page"]), "outcome": record["outcome"],
        })

    def save_manifest(self) -> None:
        self._write(self.directory / "manifest.json", self._manifest)

    def export(self, rows: list[dict]) -> None:
        def write(stream):
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        _atomic(self.output_path, write)

    def _page_path(self, page_id: str) -> Path:
        # IDs are only produced internally; validate before using as a filename.
        if not isinstance(page_id, str) or len(page_id) != 69 or not page_id.startswith("page:") or any(
            char not in "0123456789abcdef" for char in page_id[5:]
        ):
            raise OCRException("invalid page identifier")
        return self.directory / (page_id[5:] + ".json")

    @staticmethod
    def _read(path: Path):
        try:
            # A checkpoint is not trusted merely because it is valid JSON.
            from .reconstruction import _pairs, _invalid_constant
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                              parse_constant=_invalid_constant)
        except (OSError, ValueError, TypeError) as error:
            raise OCRException("cannot read valid OCR checkpoint") from error

    @staticmethod
    def _write(path: Path, value: object) -> None:
        text = canonical_json(value)
        _atomic(path, lambda stream: stream.write(text + "\n"))
