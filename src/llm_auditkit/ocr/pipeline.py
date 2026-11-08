"""Optional newspaper preprocessing, with matching sync/async LLM execution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Sequence

import pandas as pd

from llm_auditkit.inference import InferenceOrchestrator

from .configuration import validate_config, validate_paths
from .models import OCRConfig, OCRException, SourceDocument, canonical_json, identity
from .reconstruction import build_request, parse_response, reconstruction_fingerprint
from .sources import check_source, inspect_document, render_page
from .store import CSV_COLUMNS, OCRStore, validate_page


class NewspaperOCRPipeline:
    def __init__(self, backend, inference_orchestrator: InferenceOrchestrator, store: OCRStore) -> None:
        self.backend = backend
        self.inference = inference_orchestrator
        self.store = store

    def run(self, documents: Sequence[SourceDocument], config: OCRConfig) -> pd.DataFrame:
        """Acquire OCR and reconstruct pending pages using native sync inference."""
        config = deepcopy(config)
        plans, fingerprint = self._prepare(documents, config)
        with self.store.locked():
            self._initialize(plans, fingerprint, config)
            records = {}
            for plan, number, page_id in self._acquisition_pages(plans):
                record = self.store.load(page_id)
                if record is None:
                    page = self.backend.recognize(render_page(plan, number, config), page_id, config)
                    record = self._accept_page(page, page_id, config)
                records[page_id] = record
            requests, ads = self._request_plan(records, plans, config, fingerprint)
            processed = 0
            for batch in self.inference.run_batches(requests, config.inference):
                processed += 1
                self._apply_batch(batch, processed, requests, records, ads, plans, config)
            return self._finish(processed, requests, records, ads, plans, config)

    async def run_async(self, documents: Sequence[SourceDocument], config: OCRConfig) -> pd.DataFrame:
        """Acquire OCR and reconstruct pending pages using native async APIs."""
        config = deepcopy(config)
        plans, fingerprint = self._prepare(documents, config)
        with self.store.locked():
            self._initialize(plans, fingerprint, config)
            records = {}
            for plan, number, page_id in self._acquisition_pages(plans):
                record = self.store.load(page_id)
                if record is None:
                    page = await self.backend.recognize_async(render_page(plan, number, config), page_id, config)
                    record = self._accept_page(page, page_id, config)
                records[page_id] = record
            requests, ads = self._request_plan(records, plans, config, fingerprint)
            processed = 0
            async for batch in self.inference.run_batches_async(requests, config.inference):
                processed += 1
                self._apply_batch(batch, processed, requests, records, ads, plans, config)
            return self._finish(processed, requests, records, ads, plans, config)

    def _prepare(self, documents, config):
        validate_config(config)
        if not isinstance(documents, (list, tuple)) or not documents:
            raise OCRException("documents must be a nonempty list or tuple")
        documents = deepcopy(documents)
        if any(not isinstance(document, SourceDocument) for document in documents):
            raise OCRException("documents must contain SourceDocument values")
        validate_paths(self.store.output_path, self.store.directory,
                       [Path(document.path).resolve() for document in documents])
        plans = [inspect_document(document, config) for document in documents]
        ids = [plan.source_id for plan in plans]
        if len(set(ids)) != len(ids):
            raise OCRException("duplicate source bytes/metadata; supply distinct metadata for intended replicas")
        return plans, reconstruction_fingerprint(config, ids)

    def _initialize(self, plans, fingerprint, config):
        self.store.initialize(fingerprint, sorted([
            {"source_id": plan.source_id, "sha256": plan.sha256, "metadata": plan.metadata,
             "page_count": plan.page_count} for plan in plans
        ], key=lambda source: source["source_id"]), config.save_after_each_batch)

    @staticmethod
    def _pages(plans):
        for plan in plans:
            for number in range(1, plan.page_count + 1):
                yield plan, number, identity("page", [plan.source_id, number])

    def _acquisition_pages(self, plans):
        for plan in plans:
            check_source(plan)
            yield from self._pages([plan])
            check_source(plan)

    def _accept_page(self, page, page_id, config):
        validate_page(page, page_id)
        record = {"version": 1, "page": page, "outcome": None}
        if config.save_after_each_batch:
            self.store.save(record)
        return record

    def _request_plan(self, records, plans, config, fingerprint):
        metadata = {page_id: plan.metadata for plan, _, page_id in self._pages(plans)}
        requests, ads = [], {}
        for page_id, record in records.items():
            page = record["page"]
            request = build_request(page, metadata[page_id], config, fingerprint) if page.blocks else None
            outcome = record["outcome"]
            if outcome is not None:
                self._validate_outcome(outcome, request)
                if outcome["status"] == "success":
                    ads[page_id] = parse_response(outcome["response"], page)
                    continue
            if request is None:
                record["outcome"] = self._outcome(None, '{"ads":[],"blocks":[]}', None)
                ads[page_id] = []
            else:
                requests.append(request)
        if config.save_after_each_batch:
            for record in records.values():
                if not record["page"].blocks:
                    self.store.save(record)
        return requests, ads

    @staticmethod
    def _outcome(request, response, error):
        return {"status": "failed" if error else "success", "response": response,
                "request_id": request.request_id if request else None,
                "model_config_id": request.model_config_id if request else None, "error": error}

    @staticmethod
    def _validate_outcome(outcome, request):
        if not isinstance(outcome, dict) or outcome.keys() != {
            "status", "response", "request_id", "model_config_id", "error",
        }:
            raise OCRException("invalid page outcome checkpoint")
        if outcome["request_id"] != (request.request_id if request else None) or outcome["model_config_id"] != (
            request.model_config_id if request else None
        ):
            raise OCRException("checkpoint request/model identity does not match current OCR content")
        if not isinstance(outcome["status"], str) or outcome["status"] not in {"success", "failed"}:
            raise OCRException("invalid checkpoint completion status")
        if outcome["status"] == "success":
            if not isinstance(outcome["response"], str) or outcome["error"] is not None:
                raise OCRException("successful checkpoint requires a response and no error")
        elif not isinstance(outcome["error"], str) or not outcome["error"].strip():
            raise OCRException("failed checkpoint requires an error")

    def _apply_batch(self, batch, number, requests, records, ads, plans, config):
        size = config.inference.batch_size
        expected = requests[(number - 1) * size:number * size]
        total = (len(requests) + size - 1) // size
        if not expected or batch.batch_number != number or batch.total_batches != total:
            raise OCRException("shared inference batch progress does not match the OCR plan")
        results = {result.request_id: result for result in batch.results}
        if len(results) != len(batch.results) or set(results) != {request.request_id for request in expected}:
            raise OCRException("shared inference results do not match the OCR request plan")
        updates = []
        for request in expected:
            result = results[request.request_id]
            if result.model_config_id != request.model_config_id or result.metadata != request.metadata:
                raise OCRException("shared inference model/metadata association differs from the OCR plan")
            page_id = request.metadata["page_id"]
            response = result.content
            if response is None and result.structured_content is not None:
                response = canonical_json(result.structured_content)
            error = f"{result.error.type}: {result.error.message}" if result.error is not None else None
            parsed = None
            if error is None:
                try:
                    parsed = parse_response(response, records[page_id]["page"])
                except OCRException as failure:
                    error = str(failure)
            updates.append((page_id, self._outcome(request, response, error), parsed))
        # Validate/associate the entire batch before mutating its checkpoints.
        for page_id, outcome, parsed in updates:
            records[page_id]["outcome"] = outcome
            if parsed is not None:
                ads[page_id] = parsed
        if config.save_after_each_batch:
            self._checkpoint(records, ads, plans, config, [page_id for page_id, _, _ in updates])
        if any(outcome["status"] == "failed" for _, outcome, _ in updates):
            raise OCRException("OCR reconstruction batch failed; inspect page checkpoints before resuming")

    def _rows(self, records, ads, plans, config):
        rows = []
        for plan, number, page_id in self._pages(plans):
            record = records[page_id]
            for ad in ads.get(page_id, []):
                rows.append({
                    "ad_id": ad["ad_id"], "source_id": plan.source_id, "page_id": page_id,
                    "page_number": number, "source_path": str(plan.path),
                    "metadata_json": canonical_json(plan.metadata), "raw_text": ad["raw_text"],
                    "Text": ad["Text"], "source_spans_json": canonical_json(ad["source_spans"]),
                    "request_id": record["outcome"]["request_id"],
                    "model_config_id": config.inference.models[0].config_id, "review_required": True,
                })
        return rows

    def _checkpoint(self, records, ads, plans, config, page_ids=None):
        self.store.save_manifest()
        for page_id in (records if page_ids is None else page_ids):
            self.store.save(records[page_id])
        self.store.export(self._rows(records, ads, plans, config))

    def _finish(self, processed, requests, records, ads, plans, config):
        if processed != (len(requests) + config.inference.batch_size - 1) // config.inference.batch_size:
            raise OCRException("shared inference stopped before all OCR batches completed")
        if any(record["outcome"] is None or record["outcome"]["status"] != "success" for record in records.values()):
            raise OCRException("OCR run has incomplete page outcomes")
        for plan in plans:
            check_source(plan)
        rows = self._rows(records, ads, plans, config)
        if not config.save_after_each_batch or not processed:
            self._checkpoint(records, ads, plans, config)
        return pd.DataFrame(rows, columns=CSV_COLUMNS)
