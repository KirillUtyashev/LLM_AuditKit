# Running Hiring Experiments

This guide shows how to turn a populated hiring-scenario DataFrame into durable model
decisions with LLM AuditKit's experiment execution API. The runner constructs prompts,
uses shared inference, parses applicant decisions and token log probabilities, and
checkpoints a canonical CSV that can be resumed safely.

For the internal contract and design rationale, see the
[experiment execution component documentation](../components/experiment_execution.md).

## Install and Configure Credentials

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp -n .env.example .env
```

Add only the provider credential to `.env`:

```dotenv
OPENAI_API_KEY=your-key-here
```

Credentials are read by the provider integration. They do not belong in
`ExperimentConfig`, `ModelConfig.parameters`, input DataFrames, or committed output.

## Prepare a DataFrame

Experiment execution accepts a `pandas.DataFrame`, not a path. Dataset loading is the
pipeline's path-to-DataFrame boundary.

```python
import pandas as pd

dataset = pd.DataFrame(
    {
        "scenario_id": ["scenario-001"],
        "job_posting": ["Hire a careful research assistant."],
        "resume_1": ["Candidate A has research and data-management experience."],
        "resume_2": ["Candidate B has retail and customer-service experience."],
        "city": ["Toronto"],
    }
)
```

Every row is one scenario. It must contain a stable, unique scenario ID, one job
posting, and an ordered non-empty set of populated resumes. Other columns remain
caller-owned metadata and are repeated on each corresponding output record.

## Configure the Experiment

```python
from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    Persona,
)
from llm_auditkit.inference import InferenceConfig, ModelConfig

config = ExperimentConfig(
    experiment_id="research-assistant-audit-v1",
    dataset_schema=ExperimentDatasetSchema(
        scenario_id_column="scenario_id",
        job_posting_column="job_posting",
        resume_columns=["resume_1", "resume_2"],
        context_columns={"city": "city"},
    ),
    personas=[
        Persona(
            id="hiring-manager-v1",
            name="Hiring manager",
            description="You are the hiring manager responsible for this role.",
        )
    ],
    inference=InferenceConfig(
        models=[
            ModelConfig(
                config_id="openai-gpt-4.1-nano-v1",
                provider="openai",
                model="gpt-4.1-nano",
                parameters={"temperature": 0, "logprobs": True},
            )
        ],
        batch_size=25,
    ),
    save_after_each_batch=True,
)
```

`ExperimentDatasetSchema` maps semantic fields to the caller's actual column names.
`resume_columns` order defines Applicant 1 through Applicant N and the order of output
picks and log probabilities. `context_columns` preserves declaration order in the
prompt.

Each persona description is passed unchanged as the ordinary system prompt. The
package does not prepend or replace it with a custom system prompt; EDSL performs its
normal agent and prompt rendering.

Experiment execution requires `parameters["logprobs"] = True` for every model. EDSL
owns provider scheduling, caching, rate limiting, and retries within each submitted
batch.

Use a new stable ID whenever its logical definition changes:

- change `experiment_id` when the dataset schema or prompt-defining experiment changes;
- change `Persona.id` when its description changes;
- change `ModelConfig.config_id` when its provider, model, or behavior-affecting
  parameters change.

These IDs determine whether an existing job is safely complete. DataFrame row numbers
and EDSL positions are never used as durable identity.

## Create a Runner and Preview

```python
from llm_auditkit.experiments import ExperimentResultStore, ExperimentRunner
from llm_auditkit.inference import EDSLAdapter, InferenceOrchestrator

runner = ExperimentRunner(
    InferenceOrchestrator(EDSLAdapter()),
    ExperimentResultStore("experiment_results.csv"),
)

preview = runner.preview(dataset, config, batch_number=1)
for rendered in preview.prompts:
    print(rendered.request_id)
    print(rendered.system_prompt)
    print(rendered.user_prompt)
```

Preview renders one pending logical batch through EDSL without model inference. Use it
before a large run to check the complete user prompt, effective system prompt, request
cardinality, and batch size. Existing completed jobs are excluded from preview just as
they are from execution.

## Run Synchronously

```python
output = runner.run(dataset, config)
```

The synchronous method consumes shared inference's native blocking iterator. It does
not create a separate worker pool or drive an event loop.

## Run Asynchronously

```python
output = await runner.run_async(dataset, config)
```

The async method consumes shared inference's native async iterator. It uses the same
validation, pending requests, logical batches, parsing, checkpoints, failures, and
output shape as `run`.

## Understand Batches and Checkpoints

Experiment request count is:

```text
pending scenarios × personas × model configurations
```

`InferenceConfig.batch_size` counts these logical requests, not DataFrame rows. Batches
are submitted sequentially. A completed batch is validated and applied before the
runner requests the next one.

With `save_after_each_batch=True`, the runner performs one atomic CSV replacement after
each handled batch. A crash or systemic failure therefore leaves the last complete
checkpoint intact. With `False`, handled batches remain only in memory and one CSV is
written after successful execution.

Rerunning with the same DataFrame, configuration IDs, and output path loads the CSV,
skips complete job keys, and retries failed or incomplete job keys. A fully complete
checkpoint causes a no-op run with no provider calls.

## Understand the Output

The returned DataFrame and stored CSV contain one row per attempted combination of
scenario, persona, and model configuration. They preserve source columns and add:

- stable experiment, scenario, persona, model-configuration, and request IDs;
- persona name and description;
- effective rendered user and system prompts;
- the generated structured response and optional comment;
- `picks`, a JSON array ordered by `resume_columns`;
- `pick1` through `pickN` as scalar `0` or `1` columns;
- `logprob1` through `logprobN` for the emitted `Yes` or `No` decisions;
- `error_type` and `error_message` for terminal inference or parsing failures.

A row is complete only when all N picks and finite natural-log probabilities are
present and no error is recorded. Terminal request failures remain in the CSV for
inspection and are eligible for retry on the next run. A systemic association or
normalization failure raises immediately before another batch can spend tokens.

## Run the OpenAI Examples

The repository includes paid one-scenario examples with explicit output paths:

```bash
python examples/experiment_execution_sync.py /tmp/auditkit-sync.csv
python examples/experiment_execution_async.py /tmp/auditkit-async.csv
```

Each example previews a new run, executes it, prints the important output columns, and
resumes the same CSV when rerun.

## Run the Optional Live Tests

The normal test suite never makes provider calls. To run the experiment runner smoke
tests against OpenAI explicitly:

```bash
python -m pip install -e ".[test]"
python -m pytest --run-live-inference tests/integration/test_openai_experiment.py -v
```

The explicit flag and `OPENAI_API_KEY` are both required. These tests make paid calls.
