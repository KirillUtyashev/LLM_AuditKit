# Experiment Execution

[View the experiment execution diagram.](../architecture/experiment_execution.mmd)

## Overview

The experiment execution stage runs completed hiring scenarios through one or more LLM personas using the shared [inference layer](inference.md), which delegates execution to Expected Parrot EDSL.

Each dataset row represents one complete scenario containing:

- one job posting;
- `N` populated resumes, where `N` is configured during template generation;
- all metadata needed to construct the experiment prompt.

## Configuration

Experiments are configured through `ExperimentConfig`.

The configuration includes:

- path to the populated experiment dataset;
- personas;
- shared `InferenceConfig`, including model selection, concurrency, and retries;
- whether to save after each result (`save_after_each_result`).

## Job Identity

Each scheduled job has a stable `ExperimentJobKey` composed of:

- `scenario_id`;
- `persona_id`;
- `model_config_id`.

`model_config_id` identifies the provider, model, and provider-specific parameters as one configuration. Persona and model configuration IDs must remain stable across resumed runs. The job key, rather than a DataFrame row index, is used to associate results and errors and to determine whether a job is complete.

## Personas

Each `Persona` contains:

- `id`
- `name`
- `description`

The persona description is included in the system prompt.

## Inference Configuration

The shared `InferenceConfig` specifies:

- one or more `ModelConfig` definitions;
- maximum concurrency;
- maximum retry attempts.

Each `ModelConfig` has a stable configuration ID, provider, model, and provider-specific parameters.

## Execution

For each combination of:

- dataset row;
- persona;
- configured model;

the runner creates a generic `InferenceRequest` with the `ExperimentJobKey` in its metadata.

Requests are executed asynchronously by `InferenceOrchestrator`. `EDSLAdapter` translates them into Expected Parrot jobs and normalizes the results.

The shared inference layer is responsible for:

- model execution through EDSL;
- concurrency control;
- retries;
- normalized results and errors.

`ExperimentRunner` is responsible for:

- constructing inference requests;
- associating results with the correct scenario;
- incremental persistence;
- resume behavior;
- recording terminal errors.

## Incremental Saving

Completed results are written to an output DataFrame. When `save_after_each_result` is enabled, each result is persisted to disk using atomic replacement. When it is disabled, results remain in memory and are persisted after execution finishes.

Writes are synchronized to prevent concurrent modification or file corruption.

## Resume Behavior

Before scheduling a job, the runner checks whether its `ExperimentJobKey` already has a completed result.

Completed jobs are skipped when resuming an interrupted experiment.

## Failure Handling

If a job fails after `inference.max_retries` attempts:

- the failure is recorded;
- the job remains incomplete;
- execution continues for the remaining jobs.

## Output

The output preserves the scenario data and adds the corresponding experiment results and error information. Results are persisted as CSV with one record per `ExperimentJobKey`, providing the input contract for regression analysis.
