# Package Architecture

LLM AuditKit models hiring experiments as five main pipeline stages:

1. [Dataset loading](dataset_loading.md)
2. [Template generation](template_generation.md)
3. [Template population](template_population.md)
4. [Experiment execution](experiment_execution.md)
5. [Regression analysis](regression_analysis.md)

Each stage has a separate detailed Mermaid diagram under [`docs/architecture/`](architecture/).

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

[Template generation](template_generation.md) and [experiment execution](experiment_execution.md) both use the shared [inference layer](inference.md) for LLM calls:

```text
Template Generation ─┐
                     ├──> Inference Orchestrator ──> EDSL
Experiment Execution ┘
```

The inference layer owns model configuration, concurrency, retries, EDSL execution, and normalized inference results. Pipeline stages own domain-specific prompt construction, response parsing, checkpointing, and output storage.

Experiment results cross the Python-to-R boundary as CSV files. Regression configuration is provided as YAML, and the R analysis produces both raw regression results and plots.
