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

The output preserves structured scenario and candidate metadata and adds the
corresponding experiment results and error information. Results are persisted
as a raw CSV with one record per `ExperimentJobKey`. This CSV is the upstream
source for [regression-data preparation](regression_analysis.md#1-regression-data-preparation),
not directly for regression estimation; when it contains multiple personas or
models, an audit-partitioned writer output or handoff adapter becomes the
preparation command's direct input.

The raw output must preserve:

- `scenario_id`, `persona_id`, and `model_config_id`;
- the `result_status` completion indicator;
- configurable candidate cardinality;
- a stable candidate/resume identity for every candidate;
- structured candidate covariates needed for later analysis;
- candidate-level raw selections and emitted-answer log probabilities; and
- structured ranking fields such as city and year.

An experiment configuration may schedule several personas and model
configurations into one aggregate result table. The current regression
preparation boundary does not filter such a table: each configured CSV set must
already represent one persona, one model configuration, and one distinguishable
run or batch before the researcher assigns its `audit_id`.

The [regression integration handoff](../integration/regression_analysis.md)
verifies the downstream workflow with audit-partitioned public fixtures and
records a compatibility-only smoke test for the legacy private sample. It does
not select the production handoff design. Issue #13 must either make the
finalized writer emit audit-partitioned CSVs or provide an explicit, validated
adapter that partitions aggregate output first. Because `ExperimentJobKey`
currently has no run/batch field, the writer or adapter must also preserve that
provenance rather than asking preparation to infer it. The temporary legacy
sample mapping is not a production adapter.

Candidate indices may describe the wide CSV layout but are not durable
identities. The exact consumer-facing column convention and validation rules are
defined by the linked regression-data preparation contract and must be
coordinated with this component before production integration.
