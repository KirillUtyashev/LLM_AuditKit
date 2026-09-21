# LLM AuditKit

LLM AuditKit audits large language model behavior in hiring experiments. The
main pipeline is a Python package, while statistical analysis is implemented
as reproducible R entry points alongside it.

Dataset loading is implemented for normalized local and HTTP(S) tabular sources with
configurable validation and stable scenario IDs. The shared inference package provides
validated deterministic batching, synchronous and asynchronous execution, prompt
preview, normalized outcomes, and an Expected Parrot EDSL adapter. Experiment execution
includes deterministic planning, parsing, execution, and atomic CSV checkpoint/resume
storage. The other domain pipeline stages remain documented for incremental
implementation.

## Quickstart

The current user-facing functionality includes dataset loading, shared inference, and
experiment execution. The following commands install the package from this repository
and make one real OpenAI request:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp -n .env.example .env
```

Add your key to `.env`:

```dotenv
OPENAI_API_KEY=your-key-here
```

Then run the synchronous example:

```bash
python examples/shared_inference_sync.py
```

The example previews the EDSL-rendered prompt, executes it with `gpt-4.1-nano`, and
prints the normalized result. It makes a paid provider call. An asynchronous example
is also available:

```bash
python examples/shared_inference_async.py
```

Read [Using Shared Inference](docs/guides/shared_inference.md) for configuration,
request identity, prompt preview, batching, sync and async execution, results,
failures, and checkpoint integration.

Read [Loading Pipeline Datasets](docs/guides/dataset_loading.md) for local and remote
sources, supported formats, configurable validation, optional-field warnings, and
stable scenario IDs.

For the higher-level YAML workflow, read
[Running Hiring Experiments](docs/guides/experiment_execution.md). The guide covers
dataset and output paths, schema mapping, explicit question and persona templates,
stable IDs, log probabilities, prompt preview, synchronous and asynchronous execution,
atomic CSV checkpoints, and resume behavior. A runnable paid OpenAI configuration is available at
[`synthetic_experiment.yaml`](configs/experiments/synthetic_experiment.yaml).

The R regression stage independently includes a locked environment, separate
preparation and fixed-effects estimation runners, tidy result export, and
in-memory or PNG rendering. A public two-audit synthetic walkthrough verifies
those R entry points together. The implemented experiment-execution CSV and the
current regression-preparation schema are not yet directly compatible; their
mapping and validation of researcher-created audit partitions remain explicit
follow-up integration work.

## Documentation

The [package architecture](docs/architecture.md) describes the planned hiring pipeline.
The [dataset loading component contract](docs/components/dataset_loading.md) and
[shared inference component contract](docs/components/inference.md) document their
detailed behavior and boundaries. The
[experiment execution component contract](docs/components/experiment_execution.md)
documents the implemented hiring-experiment stage.

Contributors should also follow the [engineering workflow](docs/development_workflow.md) for issues, branches, pull requests, and review.

The private [paper reference repository](docs/paper_reference.md) preserves the earlier research code for historical context without making it part of this package.

The [regression integration handoff](docs/integration/regression_analysis.md)
records the verified public workflow, the private legacy-sample compatibility
smoke test, and the remaining experiment-writer and CI touchpoints.

To consult the optional pinned implementation used for the earlier paper, run
`python scripts/sync_reference_repo.py`. It requires authorized GitHub SSH
access and checks the code out under the ignored `.references/` directory.
Read the [paper reference guide](docs/paper_reference.md) before using it.

## Regression analysis

For regression-analysis development, restore the repository-local R
environment and run its tests from the repository root:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript tests/r/run_tests.R
```

Run the complete public synthetic regression workflow in its deliberate three
stages:

```bash
Rscript scripts/prepare_regression_data.R --config examples/regression/end_to_end/prepare_audit_a.yaml
Rscript scripts/prepare_regression_data.R --config examples/regression/end_to_end/prepare_audit_b.yaml

# Inspect the two regression-ready CSVs under outputs/regression/end_to_end/.

Rscript scripts/run_regression.R --config examples/regression/end_to_end/regress_audit_a.yaml
Rscript scripts/run_regression.R --config examples/regression/end_to_end/regress_audit_b.yaml
Rscript scripts/render_regression_plot.R --config examples/regression/end_to_end/render_audits.yaml
```

The walkthrough uses invented public data for two separately prepared audits,
four city-year estimates per audit, and one two-panel PNG. It is a mechanical
example, not a research result. See the [regression examples](examples/regression/README.md)
for the inspection checks and expected artifacts.

Prepare CSVs that satisfy the current regression-preparation schema with:

```bash
Rscript scripts/prepare_regression_data.R --config path/to/preparation.yaml
```

The implemented experiment checkpoint cannot yet be passed directly to this
command; the explicit production mapping and validation work is documented in
the regression integration handoff.

The researcher assigns one stable `audit_id` in each preparation config. The
software never generates or infers it from filenames, model metadata, or other
IDs. One audit covers one LLM product/version configuration, one persona, and
one distinguishable execution run or batch. Its configured files may be
city/year shards. The identifier is retained in the regression-ready data and
every later coefficient result.

After inspecting and, if desired, slicing that regression-ready CSV, estimate
the configured model with:

```bash
Rscript scripts/run_regression.R --config path/to/regression.yaml
```

The command writes `regression_results.csv`. In an interactive R session,
`estimate_regressions()` instead returns the same tidy table directly, and
`write_regression_results()` can save that object later. Every configured
estimation-group combination is a separate fit, and every requested
explanatory variable receives its own estimate, standard error, p-value, and
90%, 95%, and 99% confidence intervals.

The regression YAML contract and tidy result schema are documented in the
[regression analysis guide](docs/components/regression_analysis.md#2-fixed-effects-estimation).
The [regression integration handoff](docs/integration/regression_analysis.md)
records the walkthrough evidence and the assumptions that will be reconciled
and revalidated against the implemented experiment writer during the holistic
integration pass after all baseline pipeline components are implemented.

For an interactive estimate-and-plot workflow, start R from the repository and
load the public R interface once:

```r
source("R/regression/load.R")

results <- estimate_regressions("path/to/regression.yaml")
plot_config <- regression_plot_config(
  outcome_variable = "pick_top",
  term = "black",
  period_variable = "year",
  series_variable = "city"
)
figure <- plot_regression_results(results, plot_config)
figure
```

The loader activates the repository's locked `renv` environment. In the plot
configuration, `outcome_variable` selects the dependent variable and `term`
selects the independent-variable coefficient shown on the y-axis. Result CSV
paths can be passed in place of `results`, and compatible result objects from
separate audit calls can be supplied as a list with `panel_variable =
"audit_id"`. For paper-style city/year figures, use `series_variable = "city"`
and `period_variable = "year"`; distinct audit panels may retain distinct
`dataset_id` values. The comparison must otherwise use the same explanatory
variables, controls, fixed effects, clustering, covariance type, estimation
grouping, inference contract, and preparation settings. The selected
`panel_variable`, rather than the mere presence of `audit_id`, `dataset_id`, or
`model_id`, determines the panels.

Render a paper-style PNG from saved numerical results with:

```bash
Rscript scripts/render_regression_plot.R --config path/to/render.yaml
```

A runnable four-panel example uses only public, synthetic saved results:

```bash
Rscript scripts/render_regression_plot.R --config examples/regression/render_synthetic.yaml
```

It writes `outputs/regression/synthetic_paper_style.png` without needing raw
data, private-repository access, or an estimation run. See the
[rendering example](examples/regression/README.md) for configuration and
interpretation notes. All CSV/YAML paths are resolved relative to the YAML
file. Generated research outputs under `outputs/` are ignored by Git.
