"""Bounded local raster/PDF reading, separate from tabular dataset loading."""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from .configuration import validate_metadata
from .models import OCRConfig, OCRException, SourceDocument, identity, validate_export_text


@dataclass(frozen=True)
class DocumentPlan:
    path: Path
    source_id: str
    sha256: str
    metadata: dict
    page_count: int
    snapshot_path: Path | None = None


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_tools():
    try:
        import pdf2image
        return pdf2image
    except ImportError as error:
        raise OCRException('PDF support requires pip install "llm-auditkit[ocr]" and system Poppler') from error


def inspect_document(document: SourceDocument, config: OCRConfig) -> DocumentPlan:
    if not isinstance(document, SourceDocument):
        raise OCRException("documents must contain SourceDocument values")
    validate_metadata(document.metadata)
    path = Path(document.path).resolve()
    validate_export_text(str(path))
    if not path.is_file() or path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise OCRException("source must be a local PDF, PNG or JPEG file")
    digest = file_hash(path)
    try:
        if path.suffix.lower() == ".pdf":
            count = _pdf_tools().pdfinfo_from_path(str(path), timeout=config.timeout)["Pages"]
        else:
            from PIL import Image
            with Image.open(path) as image:
                if image.format not in {"PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1:
                    raise OCRException("raster input must be single-page PNG or JPEG")
                image.verify()
            count = 1
    except OCRException:
        raise
    except Exception as error:
        raise OCRException(f"cannot inspect source (PDFs require Poppler): {type(error).__name__}") from error
    if type(count) is not int or count < 1:
        raise OCRException("source has no physical pages")
    if file_hash(path) != digest:
        raise OCRException("source changed during inspection")
    return DocumentPlan(path, identity("source", [digest, document.metadata]), digest,
                        dict(document.metadata), count)


def check_source(plan: DocumentPlan) -> None:
    if file_hash(plan.path) != plan.sha256:
        raise OCRException("source changed during OCR run")


@contextmanager
def verified_snapshot(plan: DocumentPlan):
    """Render only bytes verified against the durable source hash.

    A later source mutation may stop the run, but cannot poison cached OCR for
    that original source. The private copy is removed even on interruption.
    """
    with tempfile.TemporaryDirectory(prefix="auditkit-ocr-source-") as directory:
        snapshot = Path(directory) / ("source" + plan.path.suffix)
        shutil.copyfile(plan.path, snapshot)
        if file_hash(snapshot) != plan.sha256:
            raise OCRException("source changed while creating its verified snapshot")
        snapshot.chmod(0o400)
        yield replace(plan, snapshot_path=snapshot)


def render_page(plan: DocumentPlan, number: int, config: OCRConfig) -> bytes:
    """Render only the requested physical PDF page, never silently the first."""
    if not 1 <= number <= plan.page_count:
        raise OCRException("physical page number outside source")
    source = plan.snapshot_path or plan.path
    if source.suffix.lower() != ".pdf":
        return source.read_bytes()
    try:
        images = _pdf_tools().convert_from_path(
            str(source), dpi=config.dpi, first_page=number, last_page=number,
            fmt="png", thread_count=1, timeout=config.timeout,
        )
        if len(images) != 1:
            raise OCRException("PDF rendering did not return exactly one page")
        with images[0] as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
    except OCRException:
        raise
    except Exception as error:
        raise OCRException(f"cannot render PDF page: {type(error).__name__}") from error
