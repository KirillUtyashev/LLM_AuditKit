# LLM AuditKit

LLM AuditKit audits large language model behavior in hiring experiments. The
main pipeline is a Python package, while statistical analysis is implemented
as reproducible R entry points alongside it.

The project is under active development. Most Python components remain
architecture-first; the regression stage currently includes its locked R
environment, a complete YAML-driven raw-to-regression-ready preparation
runner, and a separate fixed-effects estimation runner that writes plot-ready
numerical results. The estimator also returns the same tidy results as an R
object for interactive analysis. An independent paper-style renderer recreates
PNG figures from those results without rerunning a regression.

## Documentation

See the [package architecture](docs/architecture.md) for the planned hiring pipeline, shared inference layer, and detailed component documentation.

Contributors should also follow the [engineering workflow](docs/development_workflow.md) for issues, branches, pull requests, and review.

The private [paper reference repository](docs/paper_reference.md) preserves the earlier research code for historical context without making it part of this package.

## Getting Started

1. Create and activate a virtual environment. For example, using Python's built-in `venv` on macOS or Linux:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install the package in editable mode from the repository root:

   ```bash
   python -m pip install -e .
   ```

3. Sync the pinned, code-only implementation used for the earlier paper:

   ```bash
   python scripts/sync_reference_repo.py
   ```

   This private reference requires GitHub SSH access and is checked out under the ignored `.references/` directory. Read the [paper reference guide](docs/paper_reference.md) before using it.

4. Read the [package architecture](docs/architecture.md), [engineering workflow](docs/development_workflow.md), and `AGENTS.md` before beginning development.

For regression-analysis development, restore the repository-local R
environment and run its tests from the repository root:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript tests/r/run_tests.R
```

Prepare raw experiment CSVs with:

```bash
Rscript scripts/prepare_regression_data.R --config path/to/preparation.yaml
```

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

Render a paper-style figure from saved numerical results with:

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
