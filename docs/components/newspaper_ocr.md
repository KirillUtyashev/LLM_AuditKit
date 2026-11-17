# Newspaper OCR (optional preprocessing)

[Workflow diagram](../architecture/newspaper_ocr.mmd) ·
[User guide](../guides/newspaper_ocr.md) · Tracking issue: #35

This is an optional acquisition/preprocessing feature **before** the five-stage
hiring pipeline, not a replacement for dataset loading. Local newspaper scans
and PDFs become a job-ad CSV, which the ordinary `DatasetLoader` then loads.
There is no new-ad generation, substantive eligibility filtering, occupational
selection, scoring, or fuzzy deduplication in this feature.

## Execution and fidelity contract

`NewspaperOCRPipeline` accepts explicit `SourceDocument` paths and scalar source
metadata, an `OCRConfig`, an `OCRStore`, and the shared `InferenceOrchestrator`.
`GoogleVisionOCRBackend` isolates the Google SDK. A nonblank
`GOOGLE_VISION_API_KEY` environment variable, read at backend construction,
configures both SDK clients via `client_options.api_key`; otherwise they retain
Application Default Credentials. A configured key takes precedence and failures
do not silently fall back to another identity. Keys are not OCR configuration,
checkpoint or CSV fields and are never printed by the backend. The CLI loads
`.env` without overriding the shell; library callers manage their environment.
Optional PDF/image dependencies
are imported only when used; importing the package requires no credentials.
PDF pages are rendered individually at configured DPI, and all pages are visited.
Both provider paths use `batch_annotate_images` with one document-text request,
preserving the SDK's default transport retries.
PNG and JPEG inputs represent one page. Source metadata (for example newspaper,
city and ISO publication date) is supplied explicitly, never guessed from names.

OCR retains the full provider response, text blocks including short headings,
bounding polygons, detected breaks, and confidence. Physical page numbers and
block geometry are provenance, not DataFrame-row identities. Source IDs hash
file bytes and metadata; page IDs hash source identity and physical page number;
block IDs hash page identity, text and geometry. Identical source inputs are
rejected rather than silently deduplicated. Input changes during a run fail.
Each document is copied to a private temporary snapshot and its bytes verified
against the source hash before rendering. All cached pages therefore derive from
verified bytes, even if the original changes or processing is interrupted before
the final source check. Snapshots are removed after acquisition.

One nonempty page is one logical inference request. Its complete ordered blocks,
geometry and source metadata are supplied together: no fixed four-chunk loop,
overlap heuristics or silent truncation. `max_page_characters` bounds the complete
user prompt; oversized pages fail before LLM execution. Cross-page ads are not
automatically joined. OCR provider reading order is retained, not assumed perfect.

The response is strict JSON with an `ads` list, optionally enclosed in one
whole-response Markdown JSON code fence. Only that unambiguous presentation
wrapper is removed for parsing; surrounding prose, malformed JSON and duplicate
keys remain errors. The original model response is retained in checkpoints.
Each ad contains nonblank cleaned `text`. The model may repair OCR errors as
well as spacing and punctuation. No character-equality, numeric-format,
complete-block-partition or mandatory per-ad source-mapping check is performed.
Prompts still instruct the model not to invent facts or alter the meaning of
requirements/contact details or historical language; this is not a software
guarantee. Malformed schemas, non-string/blank ad text, invalid UTF-8 and NULs
remain errors. Identical ad text on the same page is rejected because it cannot
be assigned distinct content-based IDs without positional identity; no fuzzy
deduplication is performed.

For offline inspection of earlier saved responses, the parser also accepts
the former `blocks` list and ad `key` fields, but does not trust or enforce those
mappings. Full-page OCR text is joined locally and repeated as `raw_text` for
each ad; it is **not** the verified raw text of that individual ad.
`source_spans_json` is retained as an empty list for CSV compatibility. Original
provider responses, blocks and geometry remain in page checkpoints. A page with
zero returned ads is valid and still retains its OCR checkpoint.

Every exported ad is `review_required=true`: review is necessary to detect
omissions, incorrect splits/merges, changed details or hallucinations. Successful
execution means basic output validation passed, not verified extraction accuracy
or automatic research readiness.

Sync and async methods use the matching shared inference APIs. OCR acquisition
has explicit sync/async provider methods; async execution does not wrap blocking
OCR/inference in threads. PDF rasterization and local file I/O remain synchronous.
Shared inference alone manages LLM retries, provider rate limits and concurrent
interviews. The OCR provider SDK manages its own transport retries; this feature
adds neither a worker pool nor a retry loop.

## Checkpoints, failure and identity

The store uses atomic JSON replacement for a versioned run manifest and page
checkpoints, and atomic replacement for the exported CSV. A fingerprint includes
source hashes/metadata, OCR settings, model parameters, and prompt/parser version.
An existing checkpoint directory with incompatible configuration is rejected;
use a new directory for a different run. The manifest also binds its output path
to prevent redirecting a resumed run over an unrelated CSV. Output paths may not overwrite inputs,
configuration, or checkpoint files. Concurrent writers are rejected by an
exclusive store lock (a stale lock requires explicit human removal).
An atomic JSON-encoded `<output.csv>.owner` claim binds the destination to one fingerprint
and checkpoint directory, including while no CSV exists yet. Other runs must use
a different destination. The claim survives failure and permits the owner's
interrupted export to resume; absence of a claim never proves ownership of an
existing CSV. Do not delete ownership records to reuse an output path.

Checkpoint schema v2 rejects v1 manifests/pages: v1 source attribution cannot be
proven safe. Use a new checkpoint directory and output CSV for the corrected
implementation. No automatic migration or data deletion is performed.

With `save_after_each_batch=true`, raw OCR is saved after each acquired page and
all outcomes from a completed logical LLM batch are saved before advancing. The
CSV is refreshed with successful ads at that boundary. With it disabled, writes
occur only after a complete successful run. Blank pages are checkpointed without
an LLM request. Resume skips validated successful pages (including zero-ad pages)
and reuses raw OCR. Failed requests and invalid responses retain errors and raw
model output in enabled checkpoints; they stop later batches. A later explicit
invocation retries failed pages, without an internal retry loop.
Only those failed-page requests set generic `use_cache=false`; the shared EDSL
adapter uses its supported isolated-cache execution option so a rejected cached
response is not replayed. Successful pages remain skipped and request IDs do not
change. Both sync and async paths use this same policy.

The CSV may be partial following failure; CLI failure and checkpoint status must
not be interpreted as completion. Stable request IDs include page identity,
OCR content and configuration. Ad IDs hash page identity and cleaned text,
not response order or temporary model keys. Changed text changes ad identity.
Moving identical files without changing metadata preserves
identity. Checkpoints contain source text and model output and must be treated
as sensitive local research artifacts, not logs or repository fixtures.

## CSV boundary

One row per extracted ad: `ad_id`, `source_id`, `page_id`, `page_number`,
`source_path`, `metadata_json`, `raw_text`, `Text` (cleaned text),
`source_spans_json`, `ocr_request_id`, `ocr_model_config_id`, `review_required`.
OCR inference provenance is namespaced so downstream experiment request/model
IDs can coexist without renaming or dropping source fields. Existing page
checkpoints retain their internal IDs; resuming re-exports the new CSV names
without rerunning successful OCR or inference. Previously loaded downstream
datasets/checkpoints are not silently migrated to a different source schema.
`raw_text` is full-page OCR repeated per ad and `source_spans_json` is `[]`;
source/page IDs, path and metadata provide page-level provenance only.
JSON-valued columns are encoded strings, so `DatasetLoader` retains scalar cells.
No `scenario_id` is invented here; the loader establishes it normally.
An empty successful run writes the same CSV header with zero records.

## Historical reference

The workflow is informed by `job-parsing-code` revision
`c9391854ea55806ec252625cd2f48fb9edb156cd`, specifically
`images_to_jobs/prepare_images.py`, `image_rec.py`, and `data_clean_up.py`.
Legacy fixed chunking, short-block deletion, filename-derived dates, research
selection and synthetic modern-ad generation are intentionally not copied.
