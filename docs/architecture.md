# Package Architecture

LLM AuditKit is organized around six primary components: five sequential pipeline stages and one cross-cutting shared inference layer.

1. [Dataset loading](components/dataset_loading.md)
2. [Shared inference](components/inference.md)
3. [Template generation](components/template_generation.md)
4. [Template population](components/template_population.md)
5. [Experiment execution](components/experiment_execution.md)
6. [Regression analysis](components/regression_analysis.md)

The [overview diagram](architecture/architecture_overview.mmd) shows where
researchers can enter or leave the workflow. The five stages have this intended
sequence when used together:

```text
Dataset Loading
    ↓
Template Generation
    ↓
Template Population
    ↓
Experiment Execution
    ↓
Regression Analysis
```

An optional [newspaper OCR preprocessing workflow](components/newspaper_ocr.md)
can precede dataset loading: local scans/PDFs become source-traceable job-ad
CSVs. It is not a sixth hiring stage. It uses Google Vision for OCR and shared
inference for ad reconstruction/cleanup; it does not generate new ads or apply
research-specific selection rules. The existing loader remains the tabular
path-to-DataFrame boundary.

The package uses `pandas.DataFrame` as the common tabular representation passed between
Python pipeline stages. Dataset loading is the single tabular path-to-DataFrame boundary;
downstream stage APIs accept DataFrames. A user-facing pipeline run configuration may
contain source and destination paths so a composition entrypoint can load once and then
invoke those DataFrame APIs. Dataset loading supports local CSV, TSV, record-oriented
JSON, and JSON Lines files and deterministic same-schema directories. It normalizes scalar cells, validates a caller-configured schema, and
preserves or derives canonical `scenario_id` values before downstream processing.

Template population fills researcher-supplied values and keeps one row per
scenario. Experiment execution consumes that DataFrame directly. Configure
the resume columns and the question's applicant labels in the same numeric
order to keep each decision with its intended candidate. Researchers can
also supply a DataFrame they populated in EDSL to the experiment runner, or
use AuditKit's population output in their own EDSL experiment. See the
[population-to-experiment walkthrough](guides/template_population.md#pass-the-populated-table-to-experiment-execution).

## Repository Pipeline Runner

[`scripts/run_pipeline.py`](../scripts/run_pipeline.py) composes the existing
stages from a master YAML referencing their own configurations. Explicit
`ocr`, `templates`, `population`, `experiments` (including R preparation), and
`analysis` phases exit at inspection boundaries; the runner never automatically
continues from preparation into estimation. It validates path/schema wiring,
supports configured scalar extraction from OCR metadata, delegates native
sync/async execution and resume to the existing stages, and atomically persists
the population output. It does not introduce new inference workers, retries,
audit partitioning, substantive predictors, or candidate identities. This
repository workflow covers one persona/model configuration per audit. See the
[user guide](guides/pipeline.md) and [phase diagram](architecture/pipeline_runner.mmd).

## Shared Inference Layer

[Template generation](components/template_generation.md) and [experiment execution](components/experiment_execution.md) both use the shared [inference layer](components/inference.md) for LLM calls:

```text
Template Generation ─┐
                     ├──> Inference Batching ──> EDSL Sync or Async Jobs
Experiment Execution ┘
```

Optional newspaper OCR reconstruction also uses this shared inference boundary.

The inference layer owns generic model and response-format configuration, deterministic request batching, compatible EDSL job grouping through its adapter, and normalized batch results including structured content and token log probabilities when requested. A logical batch is grouped by model configuration, response format and request cache policy. Each EDSL job pairs one agent and one scenario per request using EDSL's `zip_assign()` API, retaining distinct personas and instructions while allowing concurrent interviews. The adapter preserves caller prompt text literally through EDSL rendering. EDSL owns parallel interview execution, provider rate limiting, caching, and retries within each submitted job. Pipeline stages own domain-specific configured prompt templates, rendering, response parsing, checkpointing, and output storage. Explicit domain-rejected retries may set `use_cache=False` to request a fresh isolated EDSL cache without changing durable request IDs or introducing another retry loop.

Batches are submitted sequentially. A calling stage validates and checkpoints the current completed batch before requesting the next one, which bounds uncheckpointed work and prevents a systemic prompt or integration error from consuming tokens across the remaining dataset. Template generation validates a complete logical batch and, when `save_after_each_result` is enabled, performs one atomic CSV replacement for each handled scenario result. Experiment execution applies all outcomes from a completed logical batch and performs one atomic CSV replacement before advancing when `save_after_each_batch` is enabled.

The shared inference layer provides equivalent synchronous and asynchronous batch APIs. Each delegates to the corresponding EDSL execution method while preserving the same validation, batching, normalization, and failure contract.

## Logging and Observability

A repository-wide logging contract is still to be designed before the pipeline is considered complete. It should cover the shared inference layer and every pipeline stage, including template generation and experiment execution, rather than introducing unrelated stage-specific logging behavior.

The design must decide how progress, batch timing, checkpoint activity, terminal request failures, and systemic failures are exposed; how library logging relates to any command-line progress display; and which events belong to LLM AuditKit versus EDSL. Prompts, system prompts, model responses, credentials, private dataset values, and provider parameters must not be logged by default. Until that contract is defined, documented progress fields are data available to callers and do not imply a particular logger, callback, or terminal interface.

## Python-to-R Regression Boundary

User-facing template-generation and experiment runs are configured in YAML and produce
CSV checkpoints. CSV is the Python-to-R boundary; no in-memory Python-to-R
object exchange is required. With `input_format: auditkit`, R preparation
reads native experiment checkpoints and normalizes their `pick<i>`,
`logprob<i>`, and error fields to its canonical candidate/status contract.
The default `canonical` format remains supported. Researchers supply
candidate counts, durable candidate IDs, city/year, configured covariates,
and one audit-scoped input; population output carries candidate metadata
through experiment execution. Preparation rejects mixed experiment IDs (for
native input), personas, or model configurations rather than selecting or
partitioning them. Researchers retain responsibility for distinguishable
run/batch scope and the assigned `audit_id`. The
[regression integration handoff](integration/regression_analysis.md) records
the mapping, validation policy, and cross-language verification.

Within the R-based regression-analysis stage, a YAML-configured preparation
command writes a candidate-level regression-ready CSV for researcher inspection
and stamps it with one stable, researcher-assigned `audit_id`. One audit
represents one LLM product/version configuration, one persona, and one
distinguishable run or batch; city/year input files may be its shards. A
separate YAML-configured estimator transforms one inspected dataset into
plot-ready numerical results. It returns the tidy table in an interactive R
session and can persist it as CSV. An independent renderer accepts one result
table, a compatible list of tables, or saved result CSVs and produces either a
composable in-session plot or an atomic PNG. Separate audits can be explicit
panels while city and year remain within-panel estimation dimensions, provided
their right-hand-side formula, fixed effects, clustering, covariance type,
inference settings, estimation grouping, and repeated preparation provenance
match. The dependent variable and plotted coefficient are explicit, separate
selections; only an explicit outcome-by-panel map may vary the dependent
variable across panels.
