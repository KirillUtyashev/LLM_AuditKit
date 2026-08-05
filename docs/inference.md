# Shared Inference

[View the shared inference diagram.](architecture/inference.mmd)

## Overview

The inference package provides reusable LLM inference orchestration for template generation, experiment execution, and future package workflows. Expected Parrot EDSL is the execution backend, but EDSL-specific objects do not leak into the calling pipeline stages.

## Requests

Callers submit domain-neutral `InferenceRequest` objects containing:

- a stable request ID;
- a prompt;
- an optional system prompt;
- the target model configuration ID;
- caller-defined metadata used to associate the result with domain data.

Template generation constructs requests from job-posting rows. Experiment execution constructs requests from populated scenarios and personas.

## Configuration

`InferenceConfig` contains:

- one or more `ModelConfig` definitions;
- maximum concurrency (`max_concurrency`);
- maximum retry attempts (`max_retries`).

Each `ModelConfig` has a stable ID, provider, model name, and provider-specific parameters.

## Orchestration

`InferenceOrchestrator`:

1. validates requests and model references;
2. schedules requests up to the configured concurrency limit;
3. delegates execution to `EDSLAdapter`;
4. retries retryable failures;
5. yields normalized `InferenceResult` objects as requests complete.

Streaming completed results allows each caller to implement its own `save_after_each_result` behavior without coupling the inference package to a particular DataFrame or output format.

## EDSL Boundary

`EDSLAdapter` translates generic requests and model configurations into Expected Parrot questions, surveys, models, and jobs. It executes those jobs and converts EDSL responses and failures into `InferenceResult` objects.

No other package component should depend directly on EDSL-specific classes.

## Results and Failures

Each `InferenceResult` contains:

- the request ID;
- the model configuration ID;
- normalized response content;
- caller metadata copied from the request;
- error information when execution does not succeed after all retries.

The inference layer reports outcomes but does not decide how domain results are parsed, checkpointed, or persisted.
