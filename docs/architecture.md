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

The package uses `pandas.DataFrame` as the common tabular representation passed between Python pipeline stages.

## Shared Inference Layer

[Template generation](components/template_generation.md) and [experiment execution](components/experiment_execution.md) both use the shared [inference layer](components/inference.md) for LLM calls:

```text
Template Generation ─┐
                     ├──> Inference Orchestrator ──> EDSL
Experiment Execution ┘
```

The inference layer owns model configuration, concurrency, retries, EDSL execution, and normalized inference results. Pipeline stages own domain-specific prompt construction, response parsing, checkpointing, and output storage.

Experiment results cross the Python-to-R boundary as raw CSV files. Within the
R-based regression-analysis stage, a YAML-configured preparation command writes
a candidate-level regression-ready CSV for researcher inspection and stamps it
with one stable, researcher-assigned `audit_id`. One audit represents one LLM
product/version configuration, one persona, and one distinguishable run or
batch; city/year input files may be its shards. A separate
YAML-configured estimator transforms one inspected dataset into plot-ready
numerical results. It returns the tidy table in an interactive R session and
can persist it as CSV. An independent renderer accepts one result table, a
compatible list of tables, or saved result CSVs and produces either a
composable in-session plot or an atomic PNG. Separate audits can be explicit
panels while city and year remain within-panel estimation dimensions, provided
their right-hand-side formula, fixed effects, clustering, covariance type, and
inference settings, estimation grouping, and repeated preparation provenance
match. The dependent variable and plotted coefficient are explicit, separate
selections; only an explicit outcome-by-panel map may vary the dependent
variable across panels. No Python-to-R in-memory object exchange is required.
The [regression integration handoff](integration/regression_analysis.md)
records the verified public two-audit composition and the production
experiment-writer assumptions that still require revalidation.
