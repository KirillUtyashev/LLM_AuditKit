"""Bounded local raster/PDF reading, separate from tabular dataset loading."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from .configuration import validate_metadata
from .models import OCRConfig, OCRException, SourceDocument, identity


@dataclass(frozen=True)
class DocumentPlan:
    path: Path
    source_id: str
    sha256: str
    metadata: dict
    page_count: int


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


def render_page(plan: DocumentPlan, number: int, config: OCRConfig) -> bytes:
    """Render only the requested physical PDF page, never silently the first."""
    if not 1 <= number <= plan.page_count:
        raise OCRException("physical page number outside source")
    if plan.path.suffix.lower() != ".pdf":
        return plan.path.read_bytes()
    try:
        images = _pdf_tools().convert_from_path(
            str(plan.path), dpi=config.dpi, first_page=number, last_page=number,
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
