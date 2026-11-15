"""Explicitly invoked paid OCR workflow, configured through YAML."""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

from llm_auditkit.inference import EDSLAdapter, InferenceOrchestrator

from .configuration import load_ocr_run_config
from .models import OCRException
from .pipeline import NewspaperOCRPipeline
from .store import OCRStore
from .vision import GoogleVisionOCRBackend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract existing newspaper job ads (paid Vision/model calls)")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    backend = None
    try:
        run = load_ocr_run_config(args.config)
        load_dotenv()
        backend = GoogleVisionOCRBackend()
        pipeline = NewspaperOCRPipeline(backend, InferenceOrchestrator(EDSLAdapter()),
                                        OCRStore(run.checkpoint_directory, run.output_path))
        if run.mode == "async":
            async def execute():
                try:
                    return await pipeline.run_async(run.documents, run.config)
                finally:
                    await backend.close_async()
            result = asyncio.run(execute())
        else:
            result = pipeline.run(run.documents, run.config)
        print(f"Extracted {len(result)} ads; inspect scans before use. CSV: {run.output_path}")
        return 0
    except Exception as error:
        # Provider error strings can contain prompts or private newspaper text.
        detail = str(error) if isinstance(error, OCRException) else type(error).__name__
        print(f"OCR run failed: {detail}; inspect configuration/checkpoints. "
              "Output CSV may be partial.", file=sys.stderr)
        return 1
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
