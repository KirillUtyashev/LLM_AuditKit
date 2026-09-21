# Package Architecture

LLM AuditKit is organized around six primary components: five sequential pipeline stages and one cross-cutting shared inference layer.

1. [Dataset loading](components/dataset_loading.md)
2. [Shared inference](components/inference.md)
3. [Template generation](components/template_generation.md)
4. [Template population](components/template_population.md)
5. [Experiment execution](components/experiment_execution.md)
6. [Regression analysis](components/regression_analysis.md)

Each component has a separate detailed Mermaid diagram under [`docs/architecture/`](architecture/). The five pipeline stages run in this sequence:

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

The package uses `pandas.DataFrame` as the common tabular representation passed between
Python pipeline stages. Dataset loading is the single path-to-DataFrame boundary;
downstream stage APIs accept DataFrames. A user-facing pipeline run configuration may
contain source and destination paths so a composition entrypoint can load once and then
invoke those DataFrame APIs.

## Shared Inference Layer

[Template generation](components/template_generation.md) and [experiment execution](components/experiment_execution.md) both use the shared [inference layer](components/inference.md) for LLM calls:

```text
Template Generation ─┐
                     ├──> Inference Batching ──> EDSL Sync or Async Jobs
Experiment Execution ┘
```

The inference layer owns generic model and response-format configuration, deterministic request batching, compatible EDSL job grouping through its adapter, and normalized batch results including structured content and token log probabilities when requested. A logical batch is grouped by model configuration and response format. Within each EDSL job, the adapter represents every request as one explicitly paired agent, scenario, and interview. The scenario retains the literal prompt and request ID while the agent supplies the persona and system instruction. EDSL owns parallel interview execution, provider rate limiting, caching, and retries within each submitted job. Pipeline stages own domain-specific configured prompt templates, rendering, response parsing, checkpointing, and output storage.

Batches are submitted sequentially. A calling stage validates and checkpoints the current completed batch before requesting the next one, which bounds uncheckpointed work and prevents a systemic prompt or integration error from consuming tokens across the remaining dataset. Experiment execution applies all outcomes from a completed logical batch and performs one atomic CSV replacement before advancing when `save_after_each_batch` is enabled.

The shared inference layer provides equivalent synchronous and asynchronous batch APIs. Each delegates to the corresponding EDSL execution method while preserving the same validation, batching, normalization, and failure contract.

## Logging and Observability

A repository-wide logging contract is still to be designed before the pipeline is considered complete. It should cover the shared inference layer and every pipeline stage, including template generation and experiment execution, rather than introducing unrelated stage-specific logging behavior.

The design must decide how progress, batch timing, checkpoint activity, terminal request failures, and systemic failures are exposed; how library logging relates to any command-line progress display; and which events belong to LLM AuditKit versus EDSL. Prompts, system prompts, model responses, credentials, private dataset values, and provider parameters must not be logged by default. Until that contract is defined, documented progress fields are data available to callers and do not imply a particular logger, callback, or terminal interface.

## Python-to-R Regression Boundary

User-facing experiment runs are configured in YAML and produce CSV
checkpoints. CSV is the intended Python-to-R boundary; no in-memory
Python-to-R object exchange is required. The implemented experiment checkpoint
is not yet a direct input to the current regression-data preparation command.
It can aggregate multiple personas and model configurations, writes `pick1`
through `pickN` and `logprob1` through `logprobN`, and reports failures through
error fields, while preparation requires an audit-partitioned CSV with its
documented status, candidate-count, durable candidate-identity, dynamic
candidate-family, ranking-field, and explicitly supplied scalar-covariate
contract. Researchers are responsible for creating that single-audit input;
preparation validates singleton persona/model scope rather than selecting
personas or models, while researchers retain responsibility for run/batch
scope. No production writer change or adapter currently reconciles those
interfaces. The [regression integration handoff](integration/regression_analysis.md)
records the verified downstream workflow and the remaining production boundary
work.

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
