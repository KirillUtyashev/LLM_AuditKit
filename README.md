# LLM AuditKit

LLM AuditKit is a Python package for auditing large language model behavior in hiring experiments.

The shared inference package is implemented with validated deterministic batching,
synchronous and asynchronous execution, prompt preview, normalized outcomes, and an
Expected Parrot EDSL adapter. Template generation and experiment execution use that
layer for deterministic planning, preview, normalized parsing, synchronous and
asynchronous execution, and atomic CSV checkpoint/resume storage. User-facing template
generation and experiment runs are defined in strict YAML. Experiment execution is
also launched through one command. The remaining domain pipeline stages are documented
for incremental implementation.

## Quickstart

The current user-facing functionality includes shared inference, template generation,
and experiment execution. The following commands install the package from this
repository and make one real OpenAI request:

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

Read [Generating Resume Templates](docs/guides/template_generation.md) for the
YAML run format, DataFrame schema, prompt and placeholder contracts, configurable
template counts, preview, sync and async generation, checkpoints, and resume behavior.
A complete paid OpenAI configuration example is available at
[`synthetic_template_generation.yaml`](configs/template_generation/synthetic_template_generation.yaml).

For the higher-level YAML workflow, read
[Running Hiring Experiments](docs/guides/experiment_execution.md). The guide covers
dataset and output paths, schema mapping, explicit question and persona templates,
stable IDs, log probabilities, prompt preview, synchronous and asynchronous execution,
atomic CSV checkpoints, and resume behavior. A runnable paid OpenAI configuration is available at
[`synthetic_experiment.yaml`](configs/experiments/synthetic_experiment.yaml).

## Documentation

The [package architecture](docs/architecture.md) describes the planned hiring pipeline.
The [shared inference component contract](docs/components/inference.md) documents its
detailed behavior and boundaries. The
[experiment execution component contract](docs/components/experiment_execution.md)
documents the implemented hiring-experiment stage.
The [template generation component contract](docs/components/template_generation.md)
documents the implemented resume-template stage.

Contributors should follow the
[engineering workflow](docs/development_workflow.md). The optional private
[paper reference repository](docs/paper_reference.md) preserves earlier research code
for historical context without making it part of this package.
