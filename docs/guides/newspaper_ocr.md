# Extracting job ads from newspapers

This optional workflow creates a CSV **before** dataset loading. It extracts
existing advertisements, not new synthetic ads. It does not select entry-level
jobs, score suitability, or remove similar ads.

## Install and authenticate

```bash
python -m pip install -e ".[ocr]"
```

PDFs also require system [Poppler](https://pdf2image.readthedocs.io/en/latest/installation.html)
(`brew install poppler` on macOS). Single-page PNG/JPEG images do not need it.
Google Vision needs the Cloud Vision API and billing enabled on its project.
For API-key authentication, configure a dedicated key in your local `.env`:

```dotenv
GOOGLE_VISION_API_KEY=your-vision-key
OPENAI_API_KEY=your-key
```

Restrict the key to the Cloud Vision API and apply suitable application
restrictions. Both sync and async clients use that key through Google's SDK;
no service-account JSON is required for this mode. Generic `GOOGLE_API_KEY` and
Vertex-specific keys are not read by this backend.

When `GOOGLE_VISION_API_KEY` is unset or blank, the backend instead uses
[Application Default Credentials](https://docs.cloud.google.com/vision/docs/authentication).
For example, set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account JSON
path outside the repository. A nonblank Vision key takes precedence over ADC;
an invalid key fails normally rather than silently switching credentials.

The CLI loads `.env` without overriding existing environment variables; library
callers must load `.env` themselves or export the variable before constructing
`GoogleVisionOCRBackend`. The backend reads the key at construction time. Never
commit credentials, scans, OCR checkpoints, or generated CSVs. Sending scans to
Google and extracted text to a model provider requires appropriate permissions;
both services can incur charges. Tests mock both services and require neither.

## Configure and run

Copy [the YAML example](../../tests/manual/newspaper_pipeline/ocr.yaml) and replace its input
path and source metadata with your own. Paths are relative to the YAML file.

```yaml
documents:
  - path: ../../inputs/newspaper.pdf
    metadata:
      newspaper: Example Daily
      city: Example City
      publication_date: "1950-06-15"
output:
  path: ../../outputs/ocr/ads.csv
  checkpoint_directory: ../../outputs/ocr/checkpoints
execution:
  mode: sync
  batch_size: 5
  save_after_each_batch: true
ocr:
  dpi: 300
  language_hints: [en]
  timeout: 120
  max_page_characters: 40000
inference:
  model:
    config_id: newspaper-extraction
    provider: openai
    model: gpt-4o-2024-08-06
    parameters:
      temperature: 0
      max_tokens: 16384
```

The model is an explicit example, not a promise of ongoing provider availability.
Choose a model supported by your EDSL/provider configuration with enough input
and output capacity to reproduce the full page. The manual test references a
local-only Chicago source PDF; its attribution and required path are documented
in the [test README](../../tests/manual/newspaper_pipeline/README.md). No scan is shipped.

```bash
llm-auditkit-ocr --config tests/manual/newspaper_pipeline/ocr.yaml
# Equivalent without the installed command:
python -m llm_auditkit.ocr.cli --config tests/manual/newspaper_pipeline/ocr.yaml
```

Use `mode: async` for the matching asynchronous OCR and shared-inference APIs.
Both modes use the same page planning, validation, checkpointing and CSV format.
PDF rasterization and local I/O are still blocking. There is no background OCR
worker pool. `batch_size: 5` means up to five nonblank **page requests**, not
five ads; each page may yield zero, one, or many ads. Logical LLM batches run
sequentially; EDSL manages execution, retries and concurrency within them.

Every PDF page is processed. Short OCR blocks are retained. Page reconstruction
uses all blocks/geometry together rather than independent fixed-size chunks. A
page exceeding the configured complete-prompt character limit fails without
truncating text; increase the limit only if the model can handle it. The feature
does not automatically join ads continued onto another physical page.

Input characters and output tokens are separate budgets. Reconstruction must
repeat the source segments and block IDs as well as cleaned ads; a page fitting
the 40,000-character input limit may still exceed the completion budget. The
example explicitly requests 16,384 output tokens for its
[selected model](https://developers.openai.com/api/docs/models/gpt-4o), rather
than EDSL's smaller default. Check your model's supported limit and use smaller
page inputs when the required response cannot fit. A truncated response fails
validation; the input size check alone does not guarantee success.

## Inspect and resume

Checkpoints contain the raw Google response, normalized blocks with polygons and
confidence, raw model response, and success/failure state. The model returns
`{"ads": [{"text": "cleaned advertisement"}]}` and may correct OCR errors.
There is no character-equality, numeric-format, complete-source-partition or
mandatory per-ad mapping check. One whole-response JSON Markdown fence is
accepted; arbitrary surrounding prose is not. Malformed JSON/schema, blank or
non-string ad text, NULs and invalid UTF-8 still fail validation. Duplicate ad
text on one page is rejected rather than assigned positional identities.

With incremental saving enabled, raw OCR is saved per page and reconstructed
outcomes/CSV are saved after each logical batch. A failed run can leave a partial
CSV; do not treat its existence as proof of completion. The CLI exits nonzero
on failure. Inspect failed responses in page JSON files under the checkpoint
directory. Every planned source/page must have a successful outcome for completion.

Rerun the same command to reuse saved OCR and skip successful pages, including
pages with no ads. Failed pages are retried only by this new explicit invocation.
Those requests bypass existing EDSL cache entries through shared inference, so
a previously rejected response is not replayed; durable IDs remain the same.
Changing the model, prompt contract, source bytes/metadata, DPI/language hints,
or page-size limit requires a new checkpoint directory **and** a new output CSV.
The manifest binds the original output path; do not redirect a resumed run over
another file.
Changing execution mode, batch size, or incremental saving does not invalidate
completed results. Moving identical inputs preserves IDs when metadata is unchanged.
The relaxed v3 extraction prompt/parser changes the run fingerprint. Use new
output/checkpoint paths for earlier strict runs; the checked-in Chicago example
already uses `ads-v3.csv` and `ocr-checkpoints-v3/`. The checkpoint file schema
itself remains v2. Old model responses are not relabeled as answers to the new
prompt. The existing local Chicago raw Vision page was copied into the new
store only after matching its source identity/hash and metadata; extraction is
still pending, and rerunning needs no new Vision call for that page.
Concurrent writers to the same store or output are rejected; after a killed
process, inspect and explicitly remove stale `.lock` files before resuming.
The persistent `<output.csv>.owner` file reserves the CSV for its original
checkpoint store even if the run failed before writing any CSV. Leave that file
in place when resuming; choose a different output path for an unrelated run.

This corrected implementation uses checkpoint format v2. Existing v1 checkpoint
directories are rejected rather than reused, because cached pages might have
incorrect source attribution. Start a new directory and output CSV; old files
are left untouched. Verified temporary snapshots protect new page checkpoints
from input-file changes while rendering/OCR is in progress.

With `save_after_each_batch: false`, checkpoints and CSV are written only after
a complete successful run; interruption therefore loses that invocation's progress.

## Use the CSV

`Text` contains cleaned ad text. `raw_text` contains the **entire page's OCR text**
(blocks joined by newlines), repeated for each ad, not a verified raw version of
that individual ad. `source_spans_json` is `[]`; no exact per-ad mapping is claimed.
`ad_id`, `source_id`, `page_id`, `page_number`, `source_path`, and `metadata_json`
provide page-level provenance. `ocr_request_id` and `ocr_model_config_id`
record OCR inference provenance without colliding with experiment IDs later.
Metadata and spans are JSON strings, not nested DataFrame objects.

```python
from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource

dataset = DatasetLoader(
    DatasetSchema(required_columns=["Text"], nonempty_columns=["Text"])
).load(LocalDatasetSource("outputs/ocr/ads.csv"))
```

The loader establishes `scenario_id` normally. Configure template generation's
job-posting column as `Text`. If downstream prompts need city/date as individual
columns, explicitly unpack your chosen keys from `metadata_json` in your code;
OCR does not invent a global historical-source schema.

Every ad has `review_required=true`. Successful execution does not prove that ads
were grouped correctly, that OCR read the scan correctly, or that cleanup made
no semantic changes. Compare cleaned ads and full raw pages with scans before research use,
particularly contact details, numerical requirements and demographic language.
Raw page checkpoints also retain material omitted by the model. No real-scan
accuracy claim is made by the mocked test suite.

See the [component contract](../components/newspaper_ocr.md) for the exact
reconstruction response and identity/checkpoint rules.
