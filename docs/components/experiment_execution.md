# Experiment Execution

[View the experiment execution diagram.](../architecture/experiment_execution.mmd)

## Overview

The experiment execution stage runs completed hiring scenarios through one or more LLM personas using the shared [inference layer](inference.md), which delegates batched execution to Expected Parrot EDSL.

Each dataset row represents one complete scenario containing:

- one job posting;
- `N` populated resumes, where `N` is configured during template generation;
- all metadata needed to construct the experiment prompt.

## Configuration

Experiments are configured through `ExperimentConfig`.

The configuration includes:

- path to the populated experiment dataset;
- personas;
- shared `InferenceConfig`, including model definitions and inference batch size;
- whether to save after each result (`save_after_each_result`).

## Job Identity

Each scheduled job has a stable `ExperimentJobKey` composed of:

- `scenario_id`;
- `persona_id`;
- `model_config_id`.

The runner derives a unique inference request ID from this key and also carries the key fields in request metadata. The job key, rather than a DataFrame row index or an EDSL result position, associates results and errors and determines whether a job is complete.

Persona and model configuration IDs remain stable only while they describe the same logical configuration. Changing a persona description or a model's provider, model name, or behavior-affecting parameters requires a new corresponding ID so incompatible prior results are not treated as complete.

## Personas and System Prompts

Each `Persona` contains:

- `id`;
- `name`;
- `description`.

The persona description is supplied through the request's system prompt and mapped to the standard EDSL `Agent` `persona` trait. EDSL owns its default agent instruction and normal system-prompt rendering behavior. A batch preview exposes the effective prompt rendered by EDSL without performing inference.

## Inference Configuration

The shared `InferenceConfig` specifies:

- one or more uniquely identified `ModelConfig` definitions;
- a positive batch size measured in logical inference requests.

Each `ModelConfig` has a stable configuration ID, EDSL provider or service name, model name, and JSON-compatible provider-specific inference parameters. Credentials remain outside model configuration.

Experiment request cardinality is:

```text
pending scenarios × personas × configured models
```

For example, 1,000 pending scenarios, five personas, and three model configurations produce 15,000 logical requests. `inference.batch_size` limits requests per logical inference batch rather than DataFrame rows.

## Request Construction and Preview

For every incomplete combination of scenario, persona, and configured model, the runner creates a generic `InferenceRequest` containing:

- a request ID derived from `ExperimentJobKey`;
- the fully constructed experiment prompt;
- the persona description as the system prompt;
- the target model configuration ID;
- the job key in generic metadata.

`ExperimentRunner.preview` returns the selected shared-inference batch preview without making model calls. Previewing the first small batch is the recommended way to inspect EDSL-rendered prompts and verify persona mapping, model mapping, and request cardinality before a large run.

## Execution and Batching

`ExperimentRunner.run` consumes the synchronous `InferenceOrchestrator.run_batches` iterator, while `ExperimentRunner.run_async` consumes `InferenceOrchestrator.run_batches_async`. Both paths follow the same processing contract:

1. build requests only for incomplete job keys;
2. execute one logical inference batch, which the adapter can partition into EDSL-compatible job groups;
3. validate and associate every normalized result in that completed batch;
4. update and checkpoint the output according to configuration;
5. request the next batch only after the current batch has been handled safely.

Both entry points are first-class. The synchronous path delegates to EDSL's native blocking execution, and the asynchronous path delegates to EDSL's native async execution. They use the same request construction, batch boundaries, result association, failures, checkpoint behavior, and returned DataFrame shape.

Batches are sequential at the LLM AuditKit layer. Within a batch, the adapter groups requests by model configuration and system prompt and submits those EDSL jobs sequentially. EDSL owns parallel scenario-interview execution, provider rate limiting, caching, and retry behavior inside each job. The runner does not create its own request-worker pool or retry individual EDSL interviews.

The runner can report completed batches and logical requests and use observed batch durations to estimate remaining time. Such estimates are informational because providers, models, prompt sizes, and rate limits can vary.

The shared inference layer is responsible for:

- validating generic request and model references;
- deterministic batching;
- EDSL execution through the adapter;
- normalized batch results and terminal errors.

`ExperimentRunner` is responsible for:

- constructing domain prompts and stable job identities;
- excluding completed jobs before inference;
- associating and parsing normalized results;
- incremental persistence and resume behavior;
- recording terminal errors;
- stopping before another batch when a systemic contract failure is detected.

## Incremental Saving

Completed normalized results are written to an output DataFrame. When `save_after_each_result` is enabled, after a batch returns, each result is applied and persisted using atomic replacement before the runner requests another batch. When it is disabled, results remain in memory and are persisted after execution finishes.

No new local result becomes available while the EDSL job groups for a logical batch are running. The configured inference batch size therefore bounds the logical work between checkpoint opportunities.

## Resume Behavior

Before constructing pending requests, the runner checks whether each `ExperimentJobKey` already has a completed result.

Completed jobs are skipped when resuming an interrupted experiment. Batch boundaries are not durable identity and can change when a run resumes with fewer pending jobs.

## Failure Handling

After EDSL completes its retry behavior, a terminal failure for an individual logical request is recorded against its job key, remains incomplete for resume purposes, and execution can continue for other requests.

A systemic batch failure, such as missing or duplicate request identities, unexpected result cardinality, invalid job-key association, or an inability to normalize the EDSL response set, stops the run before another batch is submitted. This prevents a broken prompt or integration from consuming tokens across the remaining dataset.

## Output

The output preserves the scenario data and adds corresponding experiment results and error information. Results are persisted as CSV with one record per `ExperimentJobKey`, providing the input contract for regression analysis.
