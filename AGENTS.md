# AGENTS.md

This file contains repository-wide guidance for human contributors and coding agents. Keep it concise, operational, and tool-neutral. Treat this file as the canonical agent guidance; add tool-specific instruction files only when a tool cannot consume this file, and keep those files limited to the necessary adapter instructions.

## Project Status and Scope

LLM AuditKit is a Python package for auditing LLM behavior in hiring experiments. The repository is currently architecture-first: its documentation describes planned behavior, while the Python package remains a scaffold unless a task explicitly requests implementation.

- Do not assume documented components are already implemented.
- Do not add functionality, dependencies, interfaces, or placeholder modules outside the scope of the current task.
- Preserve the `src/` package layout and Python support declared in `pyproject.toml`.

## Authoritative Documentation

Start with [`docs/architecture.md`](docs/architecture.md). Detailed contracts are documented in:

- [`docs/components/dataset_loading.md`](docs/components/dataset_loading.md)
- [`docs/components/template_generation.md`](docs/components/template_generation.md)
- [`docs/components/template_population.md`](docs/components/template_population.md)
- [`docs/components/inference.md`](docs/components/inference.md)
- [`docs/components/experiment_execution.md`](docs/components/experiment_execution.md)
- [`docs/components/regression_analysis.md`](docs/components/regression_analysis.md)

Follow [`docs/development_workflow.md`](docs/development_workflow.md) for issue hierarchy, branches, pull requests, review, and agent coordination.
Read [`docs/paper_reference.md`](docs/paper_reference.md) before consulting the earlier paper implementation.

Matching Mermaid diagrams live in `docs/architecture/`.

When an architectural contract represented in a Mermaid diagram changes, update the relevant Markdown page and diagram in the same change. Keep the README summary and package metadata consistent with the detailed documentation.

## Architecture Guardrails

- The hiring workflow has five pipeline stages: dataset loading, template generation, template population, experiment execution, and regression analysis.
- Template generation and experiment execution must use the shared inference layer in `src/llm_auditkit/inference/`.
- Keep Expected Parrot EDSL-specific types and behavior behind the inference adapter. Domain packages must use generic inference requests, results, and configuration rather than importing EDSL concepts directly.
- The shared inference layer owns model configuration, concurrency, retries, execution, and normalized outcomes. Calling stages own domain prompts, response parsing, checkpoint policy, and output storage.
- Template counts are configurable as `N`; do not hard-code four resumes or templates.
- Resume and completion behavior must use stable scenario, persona, model-configuration, job, and candidate/resume identifiers. Never use a DataFrame row index or candidate position as durable identity.
- Keep `save_after_each_result` stage-specific and configurable. Incremental file writes must use an atomic replacement strategy.
- The Python-to-R boundary uses raw experiment CSVs. Separate YAML-configured `Rscript` entry points prepare a regression-ready CSV, estimate one inspected dataset into plot-ready numerical results, and render figures independently from those saved results.

## Repository Layout

```text
src/llm_auditkit/   Python package
tests/              Automated tests
examples/           User-facing examples
docs/               Architecture and behavior documentation
```

Place code according to responsibility. Avoid catch-all utility modules and avoid exposing internal implementation details from package `__init__.py` files without an intentional public API decision.

## Paper Reference Implementation

The sanitized, code-only implementation used for the earlier paper is an optional historical reference. It is not part of this package and is not an architectural authority.

- As an initial setup step, run `python scripts/sync_reference_repo.py` to clone or update the pinned revision under `.references/job-parsing-code/`.
- Treat the checkout as read-only. Do not edit it or commit it to this repository.
- Use the current architecture documentation to decide public behavior, interfaces, and package boundaries. Do not copy legacy secrets, data paths, generated outputs, or implementation defects.
- When a design or implementation decision is materially based on the reference, record the reference repository revision and relevant file path in the issue or pull request.

## Development Workflow

All implementation work must follow [`docs/development_workflow.md`](docs/development_workflow.md). Each major pipeline issue normally receives one branch and pull request, with its subissues represented by focused commits.

- Inspect the working tree before editing and preserve unrelated contributor changes.
- Make the smallest coherent change that satisfies the task.
- Do not add runtime or development dependencies without a concrete need in the current task.
- Never commit credentials, tokens, private dataset contents, or generated experiment outputs. Small synthetic fixtures intentionally maintained under `tests/fixtures/` are permitted.
- Every commit that implements or changes runtime behavior must add or update unit tests under `tests/` for that behavior.
- Before committing a behavior change, run the new or affected tests and the complete existing test suite; commits intended for review must not knowingly leave tests failing.
- Bug fixes must include a regression test. Documentation-only, formatting, and repository-organization commits do not require artificial unit tests; run the relevant checks instead.
- Mock EDSL and external model calls in unit tests; unit tests must not require live credentials or network inference.
- Keep commits focused and use descriptive commit messages. Do not force-push or rewrite shared history unless explicitly requested.

## Current Commands

Install the package in editable mode:

```bash
python -m pip install -e .
```

Install the package with test dependencies:

```bash
python -m pip install -e ".[test]"
```

Run a directly affected test file:

```bash
python -m pytest tests/path/to/test_module.py
```

Run the complete test suite:

```bash
python -m pytest
```

Sync the optional paper reference implementation:

```bash
python scripts/sync_reference_repo.py
```

Check patches for whitespace errors:

```bash
git diff --check
git diff --cached --check
```

The first command checks unstaged tracked changes; the second checks the staged snapshot. Untracked files are not covered until they are staged or validated separately.

No formatter, linter, or type checker is configured yet. Do not invent commands or add tooling solely to satisfy this document. When those tools are introduced, update this section with the exact repository commands.

## Definition of Done

Before handing off a change:

- Verify the requested scope is complete and no unrelated files were changed.
- Run all checks currently configured for the affected area.
- For packaging changes, verify editable installation in an isolated environment.
- For documentation changes, verify relative links and balanced code fences. If the change affects architecture represented in Mermaid, update and verify the corresponding diagram.
- Confirm `git diff --check` passes and, when changes are staged, confirm `git diff --cached --check` passes.
- Report what changed, what was verified, and any remaining limitation.

## Code Review Rules

Flag changes that:

- bypass the shared inference layer for template generation or experiment execution;
- leak EDSL-specific objects into domain packages;
- use row positions as persistent identifiers;
- hard-code template cardinality;
- make checkpointing unconditional or perform non-atomic incremental writes;
- change architecture represented in Mermaid without updating both its prose and diagram;
- introduce live network calls into unit tests;
- commit secrets, private data, or generated result artifacts other than explicitly reviewed synthetic test fixtures.
