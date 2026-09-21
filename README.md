# LLM AuditKit

LLM AuditKit is a Python package for auditing large language model behavior in hiring experiments.

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

## Documentation

The [package architecture](docs/architecture.md) describes the planned hiring pipeline.
The [dataset loading component contract](docs/components/dataset_loading.md) and
[shared inference component contract](docs/components/inference.md) document their
detailed behavior and boundaries. The
[experiment execution component contract](docs/components/experiment_execution.md)
documents the implemented hiring-experiment stage.

Contributors should follow the
[engineering workflow](docs/development_workflow.md). The optional private
[paper reference repository](docs/paper_reference.md) preserves earlier research code
for historical context without making it part of this package.
