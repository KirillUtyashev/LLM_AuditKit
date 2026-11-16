# Running the Pipeline

Use the repository runner to connect the existing stages without writing a
composition script yourself:

```bash
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --check
```

This is a configuration-only check: no provider calls, data loading, package
installation, or R estimation. It validates stage configuration files and their
path/schema wiring. Input data, candidate assignments, and full R configuration
validation occur when their phases run. The runner requires the repository
checkout and an editable Python installation; it is not a separate installed
console command.

## Before a live run

Install `.[ocr]` and system Poppler using the [OCR guide](newspaper_ocr.md),
restore the [locked R environment](../components/regression_analysis.md), and
configure your Google Vision and model-provider credentials outside Git. The
runner loads `.env` without overriding environment variables. Do not put secrets
in YAML. CI setup is independent and is not required for local execution.

The newspaper example uses GPT-4o August 2024, asynchronous execution, batches
of five, and two candidate templates per posting. These are example settings,
not fixed limits. Edit the referenced stage YAML files to choose models,
sync/async execution, prompts, checkpoint policy, and template counts.

In `configs/ocr/newspaper.yaml`, supply a local scan/PDF path and explicit source
metadata, including city and year. The runner does not derive dates, select
research samples, generate new ads, or infer historical context. OCR processes
every physical page in the selected source: provide a small, separately prepared
PDF/image for a bounded smoke test rather than a full issue accidentally.

## Run and inspect each phase

Each invocation executes **only** the requested phase and exits. A successful
exit is not a research approval; inspect the named artifacts before invoking
the next command. There is no `--yes` or automatic continuation through gates.
The [phase diagram](../architecture/pipeline_runner.mmd) shows these boundaries.

```bash
# 1. Paid OCR and reconstruction. Compare extracted ads with the original scans.
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --phase ocr

# 2. After OCR review: paid template generation. Inspect templates and prepare replacements.
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --phase templates

# 3. After template/assignment review: populate without inference. Inspect completed resumes.
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --phase population

# 4. After resume review: paid experiment inference, then R preparation. Inspect prepared data.
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --phase experiments

# 5. Only after inspecting the prepared dataset: estimate and render.
python scripts/run_pipeline.py --config configs/pipeline/newspaper.yaml --phase analysis
```

| Phase | What it reuses | Review artifact |
| --- | --- | --- |
| `ocr` | Existing OCR command, Vision backend and shared inference | `outputs/ocr/ads.csv`, source scans and page checkpoints |
| `templates` | DatasetLoader, configured metadata extraction, TemplateGenerator/Store | `outputs/pipeline/templates.csv` |
| `population` | LocalDatasetSource and TemplatePopulator | `outputs/pipeline/populated.csv` |
| `experiments` | Existing experiment command, then `prepare_regression_data.R` | Native experiment checkpoint and `outputs/pipeline/regression_ready.csv` |
| `analysis` | `run_regression.R`, then `render_regression_plot.R` | Tidy coefficient CSV and `outputs/pipeline/regression.png` |

If a command fails, later steps in that phase do not run. R diagnostics and
preparation exclusion counts remain visible through the existing R commands.
The runner does not print prompts or responses itself. Generated artifacts
contain private research data and belong in ignored local output directories.

## Pipeline YAML

The master YAML references existing stage configurations rather than duplicating
their model/prompt/retry settings:

```yaml
ocr: ../ocr/newspaper.yaml  # optional: omit for an existing tabular dataset
templates: ../template_generation/newspaper.yaml
metadata_columns:         # optional: output column -> metadata_json key
  city: city
  year: year
population:
  replacements_path: ../../inputs/candidates.csv
  output_path: ../../outputs/pipeline/populated.csv
  template_columns:
    layout-a: template_1
    layout-b: template_2
  placeholder_columns:
    name: name
    qualification: qualification
experiments: ../experiments/newspaper.yaml
regression:
  preparation: ../regression/newspaper_prepare.yaml
  estimation: ../regression/newspaper_estimate.yaml
  rendering: ../regression/newspaper_render.yaml
```

Paths in each file resolve relative to **that file**, not the current working
directory. Unknown master keys and duplicate YAML keys are rejected. Output
paths must be distinct and cannot overwrite source data, candidate replacements,
configurations or prompt files. Stage links must agree: OCR output → template
input, population output → experiment input, experiment output → preparation
input, preparation output → estimator input, and coefficient output → renderer
input. The original stage files remain usable independently.

For a CSV/JSON dataset instead of OCR, omit `ocr`, set the template-generation
dataset path to your input, and start at `templates`. Omit `metadata_columns`
when city/year already exist as ordinary columns. Extraction copies only the
explicitly configured JSON keys, refuses overwrites and missing keys, and
preserves DatasetLoader's scenario IDs. No implicit date conversion or research
indicator derivation occurs.

## Candidate replacements

After template generation, use its `scenario_id` values to create the explicit
assignment table at `population.replacements_path`. For the two-template
example, each scenario needs exactly these two assignments (replace the example
scenario ID and choose stable candidate identities/values):

```csv
scenario_id,template_id,candidate_id,candidate_order,name,qualification,treatment
scenario-from-templates,layout-a,assigned-candidate-a,1,Alex Rowan,Researcher-supplied qualification A,0
scenario-from-templates,layout-b,assigned-candidate-b,2,Casey Brook,Researcher-supplied qualification B,1
```

The runner never creates candidate IDs, treatment indicators or substantive
qualifications. `treatment` is an illustrative researcher-defined numeric
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
durable candidate IDs pass through; unsuccessful jobs follow the existing R
exclusion/reporting policy.

Inspect the prepared CSV and, if desired, replace it with your inspected slice
before `analysis`. The wiring check requires estimation's `data_path` to match
that preparation output, so a separately named slice needs a separate standalone
estimation configuration/command. The script does not hide the inspection gate
or offer a sample-filtering language. A tiny live smoke sample may be unsuitable
for an estimable regression: sufficient outcome/predictor variation and clusters
remain the researcher's responsibility. The example formula is illustrative.

Repeat the same phase to resume: OCR, templates and experiments retain their
existing compatible-checkpoint behavior. The runner adds no worker pool, retry
loop, inference cache or durable approval ledger. Population writes one atomic
CSV after successful validation; R retains its atomic output behavior. Rerunning
preparation replaces any manually edited slice, so inspect it again before
analysis. Changing upstream data/configuration also requires renewed inspection
of downstream artifacts; explicit phase selection is the user's confirmation,
not proof that inputs have not changed.
