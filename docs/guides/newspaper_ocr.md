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
Google Vision needs an enabled project/billing and
[Application Default Credentials](https://docs.cloud.google.com/vision/docs/authentication).
For example, point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account JSON
file outside the repository. Configure the inference provider separately:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/outside/repository/vision-service-account.json
OPENAI_API_KEY=your-key
```

The CLI loads `.env` without overriding existing environment variables. Never
commit credentials, scans, OCR checkpoints, or generated CSVs. Sending scans to
Google and extracted text to a model provider requires appropriate permissions;
both services can incur charges. Tests mock both services and require neither.

## Configure and run

Copy [the YAML example](../../configs/ocr/newspaper.yaml) and replace its input
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
```

The model is an explicit example, not a promise of ongoing provider availability.
Choose a model supported by your EDSL/provider configuration with enough input
and output capacity to reproduce the full page. No private sample scan is shipped.

```bash
llm-auditkit-ocr --config configs/ocr/newspaper.yaml
# Equivalent without the installed command:
python -m llm_auditkit.ocr.cli --config configs/ocr/newspaper.yaml
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

## Inspect and resume

Checkpoints contain the raw Google response, normalized blocks with polygons and
confidence, raw model response, exact source partition, and success/failure state.
Every character in each normalized block must be assigned to an ad or explicitly
excluded with a reason. Invalid JSON, unknown references, lost/altered text, and
unreferenced ads fail validation and stop later LLM batches.
Cleanup must preserve the case-folded sequence of source letters/digits; only
spacing, word joining and punctuation changes are accepted automatically. Actual
misrecognized letters/numbers must be reviewed rather than silently guessed.

With incremental saving enabled, raw OCR is saved per page and reconstructed
outcomes/CSV are saved after each logical batch. A failed run can leave a partial
CSV; do not treat its existence as proof of completion. The CLI exits nonzero
on failure. Inspect failed responses in page JSON files under the checkpoint
directory. Every planned source/page must have a successful outcome for completion.

Rerun the same command to reuse saved OCR and skip successful pages, including
pages with no ads. Failed pages are retried only by this new explicit invocation.
Changing the model, prompt contract, source bytes/metadata, DPI/language hints,
or page-size limit requires a new checkpoint directory **and** a new output CSV.
The manifest binds the original output path; do not redirect a resumed run over
another file.
Changing execution mode, batch size, or incremental saving does not invalidate
completed results. Moving identical inputs preserves IDs when metadata is unchanged.
Concurrent writers to the same store or output are rejected; after a killed
process, inspect and explicitly remove stale `.lock` files before resuming.

With `save_after_each_batch: false`, checkpoints and CSV are written only after
a complete successful run; interruption therefore loses that invocation's progress.

## Use the CSV

`Text` contains cleaned ad text; `raw_text` preserves verbatim assigned OCR
segments (joined by newlines). `ad_id`, `source_id`, `page_id`, `page_number`,
`source_path`, `metadata_json`, and `source_spans_json` trace an ad back to its
scan and block/character ranges. Request/model IDs record inference provenance.
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

Every ad has `review_required=true`. Exact source coverage is not proof that ads
were grouped correctly, that OCR read the scan correctly, or that cleanup made
no semantic changes. Compare raw/cleaned text with scans before research use,
particularly contact details, numerical requirements and demographic language.
Keep rejected/non-ad segments available for inspection too: they may reveal
missed ads. No real-scan accuracy claim is made by the mocked test suite.

See the [component contract](../components/newspaper_ocr.md) for the exact
reconstruction response and identity/checkpoint rules.
