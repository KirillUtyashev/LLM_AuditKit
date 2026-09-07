# Experiment Execution

[View the experiment execution diagram.](../architecture/experiment_execution.mmd)

## Overview

The experiment execution stage runs completed hiring scenarios through one or more LLM personas using the shared [inference layer](inference.md), which delegates batched execution to Expected Parrot EDSL.

Each dataset row represents one complete scenario containing:

- one job posting;
- an ordered set of `N` populated resumes;
- all metadata needed to construct the experiment prompt.

All Python pipeline stages exchange `pandas.DataFrame` objects. `ExperimentRunner`
therefore accepts a DataFrame rather than a path. The user-facing command is a
composition boundary: it reads dataset and output paths from YAML, loads the CSV once,
then constructs the runner and result store.

## Configuration

User-facing runs are declared in YAML and loaded strictly into `ExperimentRunConfig`.
It contains:

- a dataset CSV path;
- an output CSV path;
- execution mode, exactly `sync` or `async`;
- the validated domain `ExperimentConfig`.

Relative paths are resolved from the YAML file's directory. Unknown or duplicate YAML
keys, path collisions, and invalid values fail before inference. The input and output
paths never enter `ExperimentRunner`; the command resolves them at the composition
boundary.

`ExperimentConfig` contains:

- a stable `experiment_id`;
- an `ExperimentDatasetSchema` describing the experiment input columns;
- a required user-question template;
- personas;
- shared `InferenceConfig`, including model definitions and the YAML execution batch
  size;
- whether to save after each completed logical batch (`save_after_each_batch`).

### Dataset Schema

`ExperimentDatasetSchema` maps semantic experiment fields to the actual DataFrame
columns. It contains:

- `job_posting_column`;
- an ordered, non-empty list of `resume_columns`;
- optional `context_columns`, mapping semantic context names such as `city`, `year`,
  `month`, and `day` to DataFrame columns used by prompt construction.

The number of applicants `N` is `len(resume_columns)`. There is no separate applicant
count that can disagree with the configured columns. The runner validates that all
configured columns exist and every job posting and populated resume required for
inference is a non-empty string.

Input rows do not need a user-created ID. When a canonical `scenario_id` source column
is present, its unique, non-empty string values are preserved for compatibility with
upstream pipeline stages. Otherwise, experiment execution derives a collision-resistant
`scenario_id` from the complete source row. Column names are sorted before hashing, so
column order and the DataFrame index do not affect identity. All source columns are
included, so changing a source value changes the generated ID. Exact duplicate rows are
rejected because they cannot be distinguished durably; an ordinary stable replicate
column can distinguish intentional repeated scenarios. The ID is persisted in
experiment output and checkpoints, not added to the caller's input DataFrame.

The package documents canonical default column names such as `job_posting` and
`resume_1` through `resume_N`, while allowing callers entering the pipeline with an
existing DataFrame to map different names explicitly. Other source columns are
caller-owned scenario metadata and are preserved unchanged in experiment output. This
is an experiment-boundary schema, not one universal column schema imposed on every
pipeline stage.

## Job Identity

Each scheduled job has a stable `ExperimentJobKey` composed of:

- `experiment_id`;
- `scenario_id`;
- `persona_id`;
- `model_config_id`.

The scenario ID is either preserved from the optional canonical input column or
derived internally from source-row content. The runner derives a deterministic,
collision-safe inference request ID from the complete job key and also carries the key
fields in request metadata. The job key and derived request ID are persisted in output.
The job key, rather than a DataFrame row index or an EDSL result position, associates
results and errors and determines whether a job is complete.

An experiment ID identifies one logical experiment definition, including its dataset
schema and prompt construction contract. Changing prompt-defining experiment behavior
requires a new experiment ID. Persona and model configuration IDs remain stable only
while they describe the same logical configuration. Changing a persona trait template or instruction, or
a model's provider, model name, or behavior-affecting parameters requires a new
corresponding ID so incompatible prior results are not treated as complete.

## Question Prompt

Every experiment explicitly supplies its user-question template. YAML references a
readable, non-empty UTF-8 `.txt` file through `prompt.template_path`; the loader stores
the text in `ExperimentConfig.prompt_template`, so the DataFrame runner remains
path-independent.

The template uses simple Python format fields. It can reference source DataFrame
columns, the canonical `{job_posting}` alias, semantic `context_columns` aliases, and
the paper-compatible derived `{date14}` and `{newspaper}` fields. It must reference
every configured resume column, preventing an applicant from being silently omitted.
The rendered text becomes the EDSL question text without package-owned wording being
added. Different years, perspectives, or experimental treatments can therefore select
different versioned template files while using the same execution machinery.

## Personas and System Prompts

Each `Persona` contains:

- `id`;
- `name`;
- a trait template;
- a static instruction.

YAML persona entries reference separate UTF-8 `.txt` files through
`trait_template_path` and `instruction_path`. Paths resolve relative to the YAML file.
The trait template can reference source DataFrame columns and semantic
`context_columns` aliases with Python format fields, such as `{city}`, `{year}`, and
`{job_posting}`. Experiment execution renders it separately for every scenario without
mutating the input DataFrame. The instruction text is passed unchanged for every
scenario using that persona.

For compatibility with the paper experiment, `{date14}` is available when `year`,
`month`, and `day` semantic context columns are configured; it is the source date plus
14 days formatted as `%B %d, %Y`. `{newspaper}` is available when `city` is configured
and uses the paper's Chicago Tribune, Boston Globe, and Birmingham News mapping.

Shared inference maps the rendered trait to the standard EDSL `Agent` `persona` trait
and the static instruction to `Agent.instruction`. EDSL owns normal system-prompt
rendering, and batch preview exposes the effective combined system prompt without
performing inference. A persona ID must change when either file's logical content
changes.

## Inference Configuration

The shared `InferenceConfig` specifies:

- one or more uniquely identified `ModelConfig` definitions;
- a positive batch size measured in logical inference requests.

Each `ModelConfig` has a stable configuration ID, EDSL provider or service name, model name, and JSON-compatible provider-specific inference parameters. Credentials remain outside model configuration.

Experiment execution requires token log probabilities. Every configured model must be
configured with `parameters["logprobs"] = True`; the EDSL adapter passes that parameter
to the selected provider. A provider or model that does not return enough token
log-probability data for a completed applicant decision produces a request-level
experiment parsing error rather than silently writing an incomplete successful record.

Experiment request cardinality is:

```text
pending scenarios × personas × configured models
```

For example, 1,000 pending scenarios, five personas, and three model configurations
produce 15,000 logical requests. YAML `execution.batch_size` becomes
`InferenceConfig.batch_size` and limits requests per logical inference batch rather
than DataFrame rows or EDSL jobs.

## Request Construction and Preview

For every incomplete combination of scenario, persona, and configured model, the runner creates a generic `InferenceRequest` containing:

- a request ID derived from `ExperimentJobKey`;
- the fully constructed experiment prompt;
- the rendered persona trait;
- the static persona instruction as the system prompt;
- the target model configuration ID;
- a generic dictionary response format with one ordered `Yes` or `No` field per
  applicant and an optional comment;
- the job key in generic metadata.

Prompt construction is deterministic. Experiment execution renders the configured
question template and selected persona trait from the same scenario row, and passes
the persona's static instruction unchanged. It does not add question wording or
reconstruct EDSL's combined system prompt.

The shared inference adapter maps the generic dictionary response format to EDSL's
standard `QuestionDict`. EDSL renders and validates the structured response. The runner
then performs domain validation, converts the ordered applicant answers to `0` or `1`,
and associates each answer with its normalized emitted-token log probability. Raw EDSL
or provider response objects do not cross the inference boundary.

`ExperimentRunner.preview` returns the selected shared-inference batch preview without making model calls. Previewing the first small batch is the recommended way to inspect EDSL-rendered prompts and verify persona mapping, model mapping, and request cardinality before a large run.

## Execution and Batching

The runner constructs the canonical job sequence deterministically in this order:

1. scenarios in the input DataFrame's existing row order;
2. personas in their declared configuration order for each scenario;
3. model configurations in their declared `InferenceConfig.models` order for each
   scenario-persona pair.

The sequence is partitioned into consecutive logical batches. DataFrame row position
therefore controls execution and presentation order only; stable identifiers remain the
sole durable identity. The runner associates returned outcomes by `request_id`, never
by EDSL return position or completion order, and restores canonical order before
updating the output.

`ExperimentRunner.run` consumes the synchronous `InferenceOrchestrator.run_batches` iterator, while `ExperimentRunner.run_async` consumes `InferenceOrchestrator.run_batches_async`. Both paths follow the same processing contract:

1. build requests only for incomplete job keys;
2. execute one logical inference batch, which the adapter can partition into EDSL-compatible job groups;
3. validate and associate every normalized result in that completed batch;
4. apply all outcomes from the completed batch and, when configured, checkpoint the
   updated output with one atomic CSV replacement;
5. request the next batch only after the current batch has been handled safely.

Both entry points are first-class. The synchronous path delegates to EDSL's native blocking execution, and the asynchronous path delegates to EDSL's native async execution. They use the same request construction, batch boundaries, result association, failures, checkpoint behavior, and returned DataFrame shape.

Batches are sequential at the LLM AuditKit layer. Within a batch, the adapter groups
requests by model configuration and response format and submits those EDSL jobs
sequentially. Ten mutually compatible logical requests become one EDSL job with ten
explicitly paired interviews even when every request has a different rendered persona;
incompatible requests may create multiple EDSL jobs. EDSL owns parallel interview
execution, provider rate limiting, caching, and retry behavior inside each job. The
runner does not create its own request-worker pool or retry individual EDSL interviews.

The YAML `execution.mode` selects the public runner method: `sync` calls
`ExperimentRunner.run` and EDSL's blocking execution, while `async` calls
`ExperimentRunner.run_async` and EDSL's native async execution. It does not change
batching, grouping, validation, checkpointing, or output.

The shared inference layer is responsible for:

- validating generic request and model references;
- deterministic batching;
- EDSL execution through the adapter;
- normalized batch results and terminal errors.

`ExperimentRunner` is responsible for:

- constructing domain prompts and stable job identities;
- excluding completed jobs before inference;
- validating one structured `Yes` or `No` answer and one selected-token log probability
  for each configured resume column;
- associating and parsing normalized results;
- incremental persistence and resume behavior;
- recording terminal errors;
- stopping before another batch when a systemic contract failure is detected.

## Incremental Saving

Completed normalized results are parsed and applied to the output DataFrame as a batch.
When `save_after_each_batch` is enabled, the result store writes the updated CSV once,
using atomic replacement, after every successfully handled logical batch and before the
runner requests the next batch. It does not rewrite the CSV separately for every result
inside that batch. When the option is disabled, results remain in memory and the final
output is persisted after execution finishes.

No new local result becomes available while the EDSL job groups for a logical batch are running. The configured inference batch size therefore bounds the logical work between checkpoint opportunities.

## Resume Behavior

Before constructing pending requests, the runner checks whether each `ExperimentJobKey` already has a completed result. It creates the full canonical job sequence first and removes completed jobs without changing the relative order of the remaining jobs.

Completed jobs are skipped when resuming an interrupted experiment. Failed or
incomplete records remain pending and are replaced when a later attempt succeeds. The
result store writes records in canonical job order regardless of prior CSV row order or
asynchronous completion order. Batch boundaries are not durable identity and can change
when a run resumes with fewer pending jobs.

## Failure Handling

After EDSL completes its retry behavior, a terminal failure for an individual logical request is recorded against its job key, remains incomplete for resume purposes, and execution can continue for other requests.

A systemic batch failure, such as missing or duplicate request identities, unexpected result cardinality, invalid job-key association, or an inability to normalize the EDSL response set, stops the run before another batch is submitted. This prevents a broken prompt or integration from consuming tokens across the remaining dataset.

## Output

The output preserves every source scenario column without EDSL prefixes and adds one
record per `ExperimentJobKey`. It is persisted as CSV and provides the input contract
for regression analysis.

Each record contains:

- `experiment_id`, `scenario_id`, `persona_id`, `model_config_id`, and the derived
  `request_id`;
- the static persona instruction;
- the effective rendered `user_prompt` and `system_prompt`;
- `generated_response` and the optional structured-response `comment`;
- `picks`, serialized as a JSON array of `0` and `1` values in configured resume-column
  order;
- dynamic scalar columns `pick1` through `pickN`;
- dynamic scalar columns `logprob1` through `logprobN`, where each value is the natural
  log probability of the emitted `Yes` or `No` token associated with that applicant;
- `error_type` and `error_message` for unsuccessful inference or domain parsing.

Successful rows have all `N` picks and log probabilities and no error. Failed rows keep
their identity and error information, leave result fields empty, and remain incomplete
for resume purposes. The output does not persist provider raw responses or unstable EDSL
bookkeeping such as scenario indices, agent indices, or generated agent names.
