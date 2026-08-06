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

Experiment results cross the Python-to-R boundary as CSV files. Regression configuration is provided as YAML, and the R analysis produces both raw regression results and plots.
