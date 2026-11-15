"""Optional newspaper-to-dataset preprocessing (no paid calls on import)."""

from .configuration import load_ocr_run_config
from .models import OCRConfig, OCRException, OCRRunConfig, SourceDocument
from .pipeline import NewspaperOCRPipeline
from .store import OCRStore
from .vision import GoogleVisionOCRBackend

__all__ = [
    "GoogleVisionOCRBackend", "NewspaperOCRPipeline", "OCRConfig", "OCRException",
    "OCRRunConfig", "OCRStore", "SourceDocument", "load_ocr_run_config",
]
