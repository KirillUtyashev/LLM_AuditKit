# LLM AuditKit

LLM AuditKit is a Python package for auditing large language model behavior in hiring experiments.

This repository currently provides the package structure only. Functionality will be added in future releases.

## Documentation

See the [package architecture](docs/architecture.md) for the planned hiring pipeline, shared inference layer, and detailed component documentation.

Contributors should also follow the [engineering workflow](docs/development_workflow.md) for issues, branches, pull requests, and review.

The private [paper reference repository](docs/paper_reference.md) preserves the earlier research code for historical context without making it part of this package.

## Getting Started

1. Install the package in editable mode from the repository root:

   ```bash
   python -m pip install -e .
   ```

2. Sync the pinned, code-only implementation used for the earlier paper:

   ```bash
   python scripts/sync_reference_repo.py
   ```

   This private reference requires GitHub SSH access and is checked out under the ignored `.references/` directory. Read the [paper reference guide](docs/paper_reference.md) before using it.

3. Read the [package architecture](docs/architecture.md), [engineering workflow](docs/development_workflow.md), and `AGENTS.md` before beginning development.
