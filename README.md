# LLM AuditKit

LLM AuditKit is a Python package for auditing large language model behavior in hiring experiments.

The shared inference package is implemented with validated deterministic batching,
synchronous and asynchronous execution, prompt preview, normalized outcomes, and an
Expected Parrot EDSL adapter. The five domain pipeline stages remain architecture-first
and are documented for incremental implementation.

## Quickstart

The current user-facing functionality is the shared inference API. The following
commands install the package from this repository and make one real OpenAI request:

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

## Documentation

The [package architecture](docs/architecture.md) describes the planned hiring pipeline.
The [shared inference component contract](docs/components/inference.md) documents its
detailed behavior and boundaries.

Contributors should follow the
[engineering workflow](docs/development_workflow.md). The optional private
[paper reference repository](docs/paper_reference.md) preserves earlier research code
for historical context without making it part of this package.
