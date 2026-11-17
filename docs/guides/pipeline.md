# Running the Pipeline

The newspaper smoke-test setup lives in
[`tests/manual/newspaper_pipeline/`](../../tests/manual/newspaper_pipeline/README.md),
separate from reusable pipeline code and examples. Its `local/` folder is
ignored by Git; pytest never runs the paid workflow automatically.

For that manual test, `./tests/manual/newspaper_pipeline/run.sh` launches the
continuous run using the repository `.venv` when present. Add `--check` for
configuration-only validation. The Python commands below remain equivalent.

Use the repository runner to connect the existing stages without writing a
composition script yourself:

```bash
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --check
```

This is a configuration-only check: no provider calls, data loading, package
installation, or R estimation. It validates stage configuration files and their
path/schema wiring. Input data, candidate assignments, and full R configuration
validation occur when their phases run. The runner requires the repository
checkout and its Python dependencies in the active environment; it is not a
separate installed console command. It resolves this checkout's `src` directory
directly, without relying on an editable-install import path or `PYTHONPATH`.
Use `source .venv/bin/activate` to activate the environment, not
`.venv/bin/activate` as an executable.

## Before a live run

Install `.[ocr]` and system Poppler using the [OCR guide](newspaper_ocr.md),
restore the [locked R environment](../components/regression_analysis.md), and
configure your Google Vision and model-provider credentials outside Git. The
runner loads `.env` without overriding environment variables. Do not put secrets
in YAML. Set `GOOGLE_VISION_API_KEY` for key-based OCR, or leave it blank to use
Google Application Default Credentials. CI setup is independent and is not
required for local execution.

The newspaper example uses GPT-4o August 2024 for reconstruction/experiments
and GPT-5.5 medium with schema-enforced parts for templates. Templates and
experiments run asynchronously, with batches of five and two candidate
templates per posting. These are example settings,
not fixed limits. Edit the referenced stage YAML files to choose models,
sync/async execution, prompts, checkpoint policy, and template counts.

In `tests/manual/newspaper_pipeline/ocr.yaml`, supply a local scan/PDF path and explicit source
metadata, including city and year. The runner does not derive dates, select
research samples, generate new ads, or infer historical context. OCR processes
every physical page in the selected source: provide a small, separately prepared
PDF/image for a bounded smoke test rather than a full issue accidentally.

## Real newspaper smoke-test input

The checked-in newspaper configurations use a complete one-page PDF from the
existing research scans: **Chicago Daily Tribune, April 2, 1950, page A6**,
the ProQuest export titled `Classified Ad 36 -- No Title`. Its printed title,
date and pagination were checked visually. It contains multiple job ads; it is
not a single-ad crop or a complete newspaper issue. The PDF's physical page is
1, while `archive_page: A6` records the original pagination. Candidate profiles
are synthetic and use generic relevant-experience pools, not the paper's design.

The original PDF remains locally, unchanged and excluded from Git, at:

```text
tests/manual/newspaper_pipeline/local/chicago-1950-smoke/source/chicago-daily-tribune-1950-04-02-page-a6.pdf
```

The source and copied file have identical SHA-256:
`1582ef343286542354fcbc588169f37a378c46a639b9654ed2196752afd17b7c`.
The PDF retains its original reproduction notice and third-party attribution;
it is not distributed with the code. Another checkout needs an authorized source
copy at this path, or a different permitted source with updated OCR metadata.
All private scans and generated artifacts stay outside Git.

This PDF input requires Poppler as well as the Python OCR dependencies. Supply
credentials in `.env`, then use `--check` and `--run` below. The full page may
produce many more inference requests than the earlier one-ad smoke test; batching
bounds concurrent work, not the total number of ads or model calls. All new
outputs are isolated under `tests/manual/newspaper_pipeline/local/chicago-1950-smoke/`; the final prepared table
will be `regression_ready.csv` there. The explicit audit ID labels a mechanics
test, not a substantive audit. Review OCR/templates and candidate assignments
before using the results for research; regression remains separate.

## Continuous execution through cleaned results

After configuring the source documents, prompts, credentials, audit ID and
sampling pools (or supplied assignments), run:

```bash
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --run
```

This executes configured OCR (if present) → template generation → candidate
sampling/loading and population → experiments → R preparation. There are no
terminal prompts or intermediate review pauses. It stops after the prepared
CSV: estimation and plotting **never** run as part of `--run`. They remain a
separate `--phase analysis` invocation after inspecting the data.

The runner checks for Rscript and, when sampling is omitted, an existing
replacement file before any paid stage. Sampling configuration is checked by
`--check` without loading data. Source validity and full R preparation validation
still happen when those stages run; `--check` is not a guarantee of a complete
live run. Configured source metadata and candidate pools must be appropriate for
the study; the checked-in pools are synthetic mechanics-test examples only.

Continuous execution passes the generated templates and populated resumes as
DataFrames to the next Python stage; it does not reload their CSV checkpoints
as handoffs. Each stage still persists its normal artifacts for inspection and
resume. OCR retains its existing CSV boundary to dataset loading, and experiments
retain their CSV boundary to R preparation. Any stage exception stops downstream
work; failed template/experiment rows also stop continuation. No automatic
workflow retries are added.

## Optional review phases

With `--phase`, each invocation executes **only** that phase and exits. A
successful exit is not a research approval; inspect the named artifacts before
invoking the next command. Use these commands when you want intermediate review
instead of `--run`.
The [phase diagram](../architecture/pipeline_runner.mmd) shows these boundaries.

```bash
# 1. Paid OCR and reconstruction. Compare extracted ads with the original scans.
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --phase ocr

# 2. After OCR review: paid template generation. Inspect templates and sampling choices.
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --phase templates

# 3. After template/assignment review: populate without inference. Inspect completed resumes.
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --phase population

# 4. After resume review: paid experiment inference, then R preparation. Inspect prepared data.
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --phase experiments

# 5. Only after inspecting the prepared dataset: estimate and render.
python scripts/run_pipeline.py --config tests/manual/newspaper_pipeline/pipeline.yaml --phase analysis
```

| Phase | What it reuses | Review artifact |
| --- | --- | --- |
| `ocr` | Existing OCR command, Vision backend and shared inference | `tests/manual/newspaper_pipeline/local/chicago-1950-smoke/ads-v3.csv`, source scans and page checkpoints |
| `templates` | DatasetLoader, configured metadata extraction, TemplateGenerator/Store | `tests/manual/newspaper_pipeline/local/chicago-1950-smoke/templates-gpt55-medium-parts.csv` |
| `population` | Configured pool sampler or supplied assignments, then TemplatePopulator | Candidate assignments and `tests/manual/newspaper_pipeline/local/chicago-1950-smoke/populated.csv` |
| `experiments` | Existing experiment command, then `prepare_regression_data.R` | Native experiment checkpoint and `tests/manual/newspaper_pipeline/local/chicago-1950-smoke/regression_ready.csv` |
| `analysis` | `run_regression.R`, then `render_regression_plot.R` | Tidy coefficient CSV and PNG; requires a suitable inspected study, not this tiny smoke sample |

If a command fails, later steps in that phase do not run. R diagnostics and
preparation exclusion counts remain visible through the existing R commands.
The runner does not print prompts or responses itself. Generated artifacts
contain private research data and belong in ignored local output directories.

## Pipeline YAML

The master YAML references existing stage configurations rather than duplicating
their model/prompt/retry settings:

```yaml
ocr: ocr.yaml  # optional: omit for an existing tabular dataset
templates: templates.yaml
metadata_columns:         # optional: output column -> metadata_json key
  city: city
  year: year
population:
  replacements_path: local/chicago-1950-smoke/candidates.csv
  output_path: local/chicago-1950-smoke/populated.csv
  template_columns:
    layout-a: template_1
    layout-b: template_2
  placeholder_columns:
    name: name
    qualification: qualification
  sampling:  # optional: omit to load your existing replacements_path instead
    assignment_namespace: chicago-1950-synthetic-candidates-smoke-v1
    seed: 42
    unique_columns: [name]
    pools:
      name: [Alex Rowan, Casey Brook, Jamie Vale, Morgan Reed]
      qualification:
        - Seven years of experience relevant to the advertised work; references available.
        - Three years of experience relevant to the advertised work; references available.
      treatment: ["0", "1"]  # synthetic independent label, not a research design
experiments: experiments.yaml
regression:
  preparation: prepare.yaml
  estimation: estimate.yaml
  rendering: render.yaml
```

Paths in each file resolve relative to **that file**, not the current working
directory. Unknown master keys and duplicate YAML keys are rejected. Output
paths must be distinct and cannot overwrite source data, supplied candidate replacements,
configurations or prompt files. Stage links must agree: OCR output → template
input, population output → experiment input, experiment output → preparation
input, preparation output → estimator input, and coefficient output → renderer
input. The original stage files remain usable independently.

For a CSV/JSON dataset instead of OCR, omit `ocr`, set the template-generation
dataset path to your input. `--run` starts at templates when OCR is omitted;
alternatively select `--phase templates`. Omit `metadata_columns`
when city/year already exist as ordinary columns. Extraction copies only the
explicitly configured JSON keys, refuses overwrites and missing keys, and
preserves DatasetLoader's scenario IDs. No implicit date conversion or research
indicator derivation occurs.

## Candidate replacements

With `population.sampling`, the runner reads generated scenario IDs directly,
draws from your explicit pools, assigns stable candidate IDs and shuffles their
presentation slots. It validates the complete population, then saves exact
assignments to `replacements_path` and filled resumes to `output_path`. Each
file write is atomic, but the pair is not a transaction; rerun after an
interrupted save. The same behavior is available in `--phase population`.

Pools contain distinct nonblank strings keyed by replacement payload column.
They are sampled independently; columns in `unique_columns` use draws without
replacement within each scenario, while other columns allow repeats. Supply
at least N values for unique pools. Namespaces/seeds and UUID identity use the
same implementation as the [standalone sampling example](template_population.md#automatically-sample-an-assignment-table).
The runner does not infer demographics, create substantive research indicators,
balance strata, or link independently drawn qualifications and labels. Adapt
the study design or supply a prepared assignment table for those requirements.

If a sampled assignment CSV already exists, it must match the current design
and scenario set (row/column order does not matter). Changed pools, seed,
namespace, payloads, IDs or slots are rejected instead of silently replacing
the saved assignments. Choose new assignment and downstream output paths for
a deliberately changed run. Scenario reordering does not alter draws; adding
scenarios preserves prior draws but requires a new complete assignment export.

Without `population.sampling`, `replacements_path` is an input file and remains
researcher-owned. It can be prepared manually or generated by the standalone
example. No candidate identities or values are created in this mode.

For the two-template
example, each scenario needs exactly these two assignments (replace the example
scenario ID and choose stable candidate identities/values):

```csv
scenario_id,template_id,candidate_id,candidate_order,name,qualification,treatment
scenario-from-templates,layout-a,assigned-candidate-a,1,Alex Rowan,Researcher-supplied qualification A,0
scenario-from-templates,layout-b,assigned-candidate-b,2,Casey Brook,Researcher-supplied qualification B,1
```

The sampler only draws values you explicitly supply; it never infers treatment
definitions or substantive qualifications. `treatment` is an illustrative numeric
indicator, not a package-defined research design. The example preparation and
estimation YAML use it; change those configurations to match your study.
Candidate assignments and template IDs must cover every scenario and configured
template. Row order is irrelevant; `candidate_order` determines résumé slots.
Only that structural order field is converted to an integer by the runner;
other CSV values remain lexical scalars. Empty payload cells become missing
values and are validated by population. See the
[population guide](template_population.md) for the full contract.

Changing N requires matching generation count, template mappings, and the
experiment's numeric résumé columns/question labels. The runner rejects
mismatched count/order rather than guessing a mapping.

## Audit scope, analysis and resume

This thin workflow intentionally handles **one experiment, one persona and one
model configuration** per preparation call. It does not split aggregate audits
or select rows automatically. Assign your stable `audit_id` and distinguishable
run/batch scope before preparing data. The native experiment CSV is consumed
unchanged using `input_format: auditkit`. Researcher-defined covariates and
durable candidate IDs pass through. Continuous mode stops before preparation
if any experiment job fails. The individual `experiments` phase retains its
existing R exclusion/reporting policy for completed output containing failed jobs.

Inspect the prepared CSV and, if desired, replace it with your inspected slice
before `analysis`. The wiring check requires estimation's `data_path` to match
that preparation output, so a separately named slice needs a separate standalone
estimation configuration/command. The script does not hide the inspection gate
or offer a sample-filtering language. A tiny live smoke sample may be unsuitable
for an estimable regression: sufficient outcome/predictor variation and clusters
remain the researcher's responsibility. The example formula is illustrative.

Repeat `--run` or the same phase to resume: OCR, templates and experiments retain their
existing compatible-checkpoint behavior. The runner adds no worker pool, retry
loop, inference cache or durable approval ledger. Population verifies saved
sampled assignments and writes its CSV after successful validation; R retains
its atomic output behavior. Rerunning
preparation replaces any manually edited slice, so inspect it again before
analysis. Changing upstream data/configuration also requires renewed inspection
of downstream artifacts; selecting continuous execution or a phase is the user's confirmation,
not proof that inputs have not changed.
