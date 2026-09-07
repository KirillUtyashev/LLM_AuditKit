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

The inference layer owns generic model and response-format configuration, deterministic request batching, compatible EDSL job grouping through its adapter, and normalized batch results including structured content and token log probabilities when requested. A logical batch is grouped by model configuration and response format. Within each EDSL job, the adapter represents every request as one agent and uses one neutral scenario, yielding exactly one interview per request while retaining its prompt, persona, system instruction, and request ID. EDSL owns parallel interview execution, provider rate limiting, caching, and retries within each submitted job. Pipeline stages own domain-specific configured prompt templates, rendering, response parsing, checkpointing, and output storage.

Batches are submitted sequentially. A calling stage validates and checkpoints the current completed batch before requesting the next one, which bounds uncheckpointed work and prevents a systemic prompt or integration error from consuming tokens across the remaining dataset. Experiment execution applies all outcomes from a completed logical batch and performs one atomic CSV replacement before advancing when `save_after_each_batch` is enabled.

The shared inference layer provides equivalent synchronous and asynchronous batch APIs. Each delegates to the corresponding EDSL execution method while preserving the same validation, batching, normalization, and failure contract.

## Logging and Observability

A repository-wide logging contract is still to be designed before the pipeline is considered complete. It should cover the shared inference layer and every pipeline stage, including template generation and experiment execution, rather than introducing unrelated stage-specific logging behavior.

The design must decide how progress, batch timing, checkpoint activity, terminal request failures, and systemic failures are exposed; how library logging relates to any command-line progress display; and which events belong to LLM AuditKit versus EDSL. Prompts, system prompts, model responses, credentials, private dataset values, and provider parameters must not be logged by default. Until that contract is defined, documented progress fields are data available to callers and do not imply a particular logger, callback, or terminal interface.

User-facing experiment runs are configured in YAML and produce CSV checkpoints.
Experiment results cross the Python-to-R boundary as CSV files. Regression
configuration is also provided as YAML, and the R analysis produces both raw
regression results and plots.
