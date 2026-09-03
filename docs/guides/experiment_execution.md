# Running Hiring Experiments

This guide shows how to turn a populated hiring-scenario CSV and an experiment YAML
file into durable model decisions. The command loads the CSV into a DataFrame once,
constructs prompts, uses shared inference, parses applicant decisions and token log
probabilities, and checkpoints a canonical output CSV that can be resumed safely.

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

Credentials are read by the provider integration. They do not belong in YAML model
parameters, input datasets, or committed output.

## Prepare the Dataset CSV

Every row is one scenario. It must contain one job posting and an ordered non-empty set
of populated resumes. Other columns remain caller-owned metadata and are repeated on
each corresponding output record. You do not need to create scenario IDs.

```csv
job_posting,resume_1,resume_2,city
Hire a careful research assistant.,Candidate A has research experience.,Candidate B has retail experience.,Toronto
```

The command-line entrypoint currently accepts CSV input. AuditKit derives each
`scenario_id` from the complete source row and stores it in experiment output. Reordering
columns or changing the DataFrame index does not change the ID, while changing any
source value does. Exact duplicate rows must include an ordinary stable replicate
column if they should run as distinct scenarios. A canonical `scenario_id` column from
an upstream stage is optional and, when present, is preserved as strings.

## Create the Experiment YAML

Store the dynamic persona trait and static instruction in separate text files. For
example, `prompts/hiring_manager_trait.txt` can contain:

```text
You are the hiring manager responsible for a role in {city}.
```

and `prompts/hiring_manager_instruction.txt` can contain:

```text
Evaluate each applicant using all information in the applicant materials.
```

Store the user question in another text file. The question template must reference
every configured resume column. For example, `prompts/applicant_question.txt` can
contain:

```text
Applicant 1: {resume_1}

Applicant 2: {resume_2}

Select each applicant you would invite for an interview, if any.
```

```yaml
experiment_id: research-assistant-audit-v1

dataset:
  path: data/populated_scenarios.csv
  job_posting_column: job_posting
  resume_columns:
    - resume_1
    - resume_2
  context_columns:
    city: city

prompt:
  template_path: prompts/applicant_question.txt

output:
  path: results/research-assistant-audit-v1.csv

execution:
  mode: async
  batch_size: 25
  save_after_each_batch: true

personas:
  - id: hiring-manager-v1
    name: Hiring manager
    trait_template_path: prompts/hiring_manager_trait.txt
    instruction_path: prompts/hiring_manager_instruction.txt

inference:
  models:
    - config_id: openai-gpt-4.1-nano-v1
      provider: openai
      model: gpt-4.1-nano
      parameters:
        temperature: 0
        logprobs: true
```

Dataset and output paths resolve relative to the YAML file, not the current working
directory. Unknown fields, missing fields, duplicate YAML keys, and invalid values fail
before inference. The input and output paths cannot resolve to the same file.

The dataset fields map semantic inputs to actual CSV columns. `resume_columns` order
defines Applicant 1 through Applicant N and the order of output picks and log
probabilities. `context_columns` provides semantic aliases; the question and persona
templates determine where those values appear.

Question and persona paths resolve relative to the YAML file and must reference
readable, non-empty UTF-8 `.txt` files. Question and trait templates use simple Python
format fields. They can refer to source column names, the canonical `{job_posting}`
alias, and semantic aliases from `context_columns`. The question template must include
every configured resume column. AuditKit renders the question and trait once per
scenario, passes the trait as EDSL's standard `persona` trait, and passes the static
instruction as `Agent.instruction`. EDSL produces the effective prompts shown by
preview and stored with results. The input DataFrame is not modified.

Paper-compatible templates may also use `{date14}` when `year`, `month`, and `day` are
mapped: AuditKit adds 14 days and formats the value as `%B %d, %Y`. With a mapped
`city`, `{newspaper}` resolves Chicago, Boston, and Birmingham to the same newspaper
names used by the reference implementation.

Experiment execution requires `parameters.logprobs: true` for every model. EDSL owns
provider scheduling, caching, rate limiting, and retries within each submitted job.

Use a new stable configuration ID whenever its logical definition changes:

- change `experiment_id` when the dataset schema or question template changes;
- change a persona `id` when its trait template or instruction changes;
- change a model `config_id` when its provider, model, or behavior-affecting parameters
  change.

These IDs determine whether an existing job is safely complete. DataFrame row numbers
and EDSL positions are never used as durable identity. Scenario IDs are handled by
AuditKit from source-row content unless a canonical ID already arrives from an upstream
stage.

## Preview Before Spending Tokens

```bash
llm-auditkit-experiment \
  --config path/to/experiment.yaml \
  --preview-only
```

Preview renders one pending logical batch through EDSL without model inference. Use it
before a large run to check the complete user prompt, effective system prompt, request
cardinality, and batch size. Existing completed jobs are excluded from preview just as
they are from execution. Select another pending batch with `--preview-batch N`.

## Run the Experiment

```bash
llm-auditkit-experiment \
  --config path/to/experiment.yaml \
  --preview
```

`--preview` renders the selected batch and then executes. Omit it when no preview is
needed. The command reads `execution.mode`:

- `sync` uses EDSL's blocking `job.run()` execution;
- `async` uses EDSL's native awaited `job.run_async()` execution.

Both modes construct the same logical requests, use the same batches and EDSL job
grouping, validate the same outcomes, and create the same output. Async mode keeps the
command's event loop available while EDSL waits; it does not create a second worker
pool.

The equivalent module entrypoint is:

```bash
python -m llm_auditkit.experiments --config path/to/experiment.yaml --preview
```

## Use the Configuration Programmatically

The YAML loader returns paths, mode, and the existing typed domain configuration:

```python
from llm_auditkit.experiments import load_experiment_run_config

run_config = load_experiment_run_config("path/to/experiment.yaml")
print(run_config.dataset_path)
print(run_config.output_path)
print(run_config.mode)
print(run_config.experiment_config)
```

`ExperimentRunner` remains the lower-level DataFrame API for applications that already
own dataset loading and an event loop.

## Understand Batches and Checkpoints

Experiment request count is:

```text
pending scenarios × personas × model configurations
```

`execution.batch_size` counts these logical requests, not DataFrame rows or EDSL jobs.
Batches are submitted sequentially. A completed batch is validated and applied before
the runner requests the next one.

Within one logical batch, the adapter groups requests by model configuration and
response format. Ten compatible requests therefore become one EDSL job containing ten
explicitly paired interviews, even when their rendered persona traits differ.
Incompatible requests may become multiple EDSL jobs. This grouping is identical in
sync and async modes.

With `execution.save_after_each_batch: true`, the runner performs one atomic CSV
replacement after each handled batch. A crash or systemic failure therefore leaves the
last complete checkpoint intact. With `false`, handled batches remain only in memory
and one CSV is written after successful execution.

Rerunning with the same YAML loads the output CSV, skips complete job keys, and retries
failed or incomplete job keys. A fully complete checkpoint causes a no-op run with no
provider calls.

## Understand the Output

The stored CSV contains one row per attempted combination of scenario, persona, and
model configuration. It preserves source columns and adds:

- stable experiment, scenario, persona, model-configuration, and request IDs;
- persona name, trait template, and static instruction;
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

## Run the Included OpenAI Example

The repository includes a synthetic CSV and YAML configuration:

```bash
llm-auditkit-experiment \
  --config configs/experiments/synthetic_experiment.yaml \
  --preview
```

The example uses async mode and makes a paid OpenAI request. Change `execution.mode` to
`sync` to exercise the blocking path. Its generated CSV is written under the ignored
`examples/output/` directory. Rerun without `--preview` to resume the checkpoint; a
fully complete checkpoint causes no provider calls.

## Run the Optional Live Tests

The normal test suite never makes provider calls. To run the experiment runner smoke
tests against OpenAI explicitly:

```bash
python -m pip install -e ".[test]"
python -m pytest --run-live-inference tests/integration/test_openai_experiment.py -v
```

The explicit flag and `OPENAI_API_KEY` are both required. These tests make paid calls.
