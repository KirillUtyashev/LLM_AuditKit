# LLM AuditKit

LLM AuditKit audits large language model behavior in hiring experiments. The
main pipeline is a Python package, while statistical analysis is implemented
as reproducible R entry points alongside it.

The project is under active development. Most Python components remain
architecture-first; the regression stage currently includes its locked R
environment and a complete YAML-driven raw-to-regression-ready preparation
runner.

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
