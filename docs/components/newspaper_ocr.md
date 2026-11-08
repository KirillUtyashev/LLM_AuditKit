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
`GoogleVisionOCRBackend` isolates the Google SDK. Optional PDF/image dependencies
are imported only when used; importing the package requires no credentials.
PDF pages are rendered individually at configured DPI, and all pages are visited.
PNG and JPEG inputs represent one page. Source metadata (for example newspaper,
city and ISO publication date) is supplied explicitly, never guessed from names.

OCR retains the full provider response, text blocks including short headings,
bounding polygons, detected breaks, and confidence. Physical page numbers and
block geometry are provenance, not DataFrame-row identities. Source IDs hash
file bytes and metadata; page IDs hash source identity and physical page number;
block IDs hash page identity, text and geometry. Identical source inputs are
rejected rather than silently deduplicated. Input changes during a run fail.

One nonempty page is one logical inference request. Its complete ordered blocks,
geometry and source metadata are supplied together: no fixed four-chunk loop,
overlap heuristics or silent truncation. `max_page_characters` bounds the complete
user prompt; oversized pages fail before LLM execution. Cross-page ads are not
automatically joined. OCR provider reading order is retained, not assumed perfect.

The response is strict JSON with `ads` and `blocks`. Each ad has a temporary `key`
and cleaned `text`. Each block has its original `block_id` and an ordered
`segments` list, each with verbatim `text`, an `ad_key` or null, and a `reason`
(required for excluded non-ad text). Concatenating a block's segment texts must
reproduce that block **exactly**. Every block must appear once; references must
resolve; every ad must own nonempty source text. This supports splitting one
block and merging several blocks, while detecting dropped/duplicated/altered
source text. Raw ad text and source spans are derived locally, never trusted from
an LLM-supplied raw-text field. All excluded text/reasons remain in checkpoints.

Cleanup is additionally validated to preserve the case-folded sequence of source
letters and digits: added, removed, substituted or reordered content fails.
Cleanup may repair OCR spacing, broken words and punctuation, but must not add
facts, alter requirements/contact details, or normalize historical demographic
language. Source-coverage validation cannot establish semantic fidelity or correct
ad boundaries. Every exported ad is marked `review_required=true`: researchers
must compare a sample (and uncertain cases) with scans. The software does not
claim validated extraction accuracy or automatic research readiness.

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

With `save_after_each_batch=true`, raw OCR is saved after each acquired page and
all outcomes from a completed logical LLM batch are saved before advancing. The
CSV is refreshed with successful ads at that boundary. With it disabled, writes
occur only after a complete successful run. Blank pages are checkpointed without
an LLM request. Resume skips validated successful pages (including zero-ad pages)
and reuses raw OCR. Failed requests and invalid responses retain errors and raw
model output in enabled checkpoints; they stop later batches. A later explicit
invocation retries failed pages, without an internal retry loop.

The CSV may be partial following failure; CLI failure and checkpoint status must
not be interpreted as completion. Stable request IDs include page identity,
OCR content and configuration. Ad IDs include source spans and page identity,
not response order. Moving identical files without changing metadata preserves
identity. Checkpoints contain source text and model output and must be treated
as sensitive local research artifacts, not logs or repository fixtures.

## CSV boundary

One row per extracted ad: `ad_id`, `source_id`, `page_id`, `page_number`,
`source_path`, `metadata_json`, `raw_text`, `Text` (cleaned text),
`source_spans_json`, `request_id`, `model_config_id`, `review_required`.
JSON-valued columns are encoded strings, so `DatasetLoader` retains scalar cells.
No `scenario_id` is invented here; the loader establishes it normally.
An empty successful run writes the same CSV header with zero records.

## Historical reference

The workflow is informed by `job-parsing-code` revision
`c9391854ea55806ec252625cd2f48fb9edb156cd`, specifically
`images_to_jobs/prepare_images.py`, `image_rec.py`, and `data_clean_up.py`.
Legacy fixed chunking, short-block deletion, filename-derived dates, research
selection and synthetic modern-ad generation are intentionally not copied.
