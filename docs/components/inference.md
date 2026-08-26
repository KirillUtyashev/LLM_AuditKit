# Shared Inference

[View the shared inference diagram.](../architecture/inference.mmd)

## Overview

The inference package provides reusable LLM inference for template generation, experiment execution, and future package workflows. Expected Parrot EDSL is the execution backend, but EDSL-specific objects do not leak into calling pipeline stages.

The shared layer validates and batches generic requests, delegates each batch to EDSL, and normalizes the returned outcomes. EDSL owns parallel interview execution, provider rate limiting, caching, and retry behavior within a submitted batch. LLM AuditKit does not implement a second worker pool or retry loop around individual EDSL interviews.

## Requests

Callers submit domain-neutral `InferenceRequest` objects containing:

- a stable request ID;
- a user prompt;
- an optional system prompt;
- the target model configuration ID;
- caller-defined metadata used to associate the result with domain data.

A request ID must be unique within one inference run and stable when the same logical request is resumed. Calling stages must derive it from durable domain identifiers rather than DataFrame row positions. If prompt-defining inputs or the selected model configuration change in a way that invalidates an existing result, the calling stage must also invalidate the corresponding completion identity.

`prompt` is always a string. `system_prompt=None` means that the caller supplies no explicit system instructions. A non-null system prompt is the exact system instruction requested by the caller: the adapter must not prepend a default EDSL persona or otherwise change its meaning. Adapter tests must inspect the prompts rendered by EDSL to verify this boundary.

Template generation constructs requests from job-posting rows. Experiment execution constructs requests from populated scenarios and personas.

## Configuration

`InferenceConfig` contains:

- one or more `ModelConfig` definitions;
- a positive inference `batch_size`.

`models` is a list rather than a mapping because each `ModelConfig` already contains its own stable `config_id`. Configuration validation rejects duplicate IDs and builds any lookup mapping internally.

Each `ModelConfig` has:

- a stable configuration ID;
- an EDSL provider or service name;
- a model name;
- JSON-compatible provider-specific inference parameters.

Changing a model's provider, model name, or behavior-affecting parameters requires a new configuration ID so resume logic cannot mistake results from different model configurations. Credentials and secrets are not model parameters; they remain in the environment or supported EDSL credential stores.

`batch_size` is the maximum number of logical `InferenceRequest` objects in one EDSL submission. It is not the number of batches and is not necessarily a number of DataFrame rows. For example, one experiment row expanded across five personas and three models represents fifteen logical requests.

Concurrency and retry counts are deliberately not duplicated in `InferenceConfig`. EDSL manages those behaviors for each batch using the supported EDSL version and its execution configuration.

## Validation

Before making any model call, the orchestrator validates the complete configuration and request collection, including:

- at least one model and a positive batch size;
- unique, non-empty model configuration IDs;
- unique, non-empty request IDs;
- non-empty prompts;
- references to known model configuration IDs.

Configuration and request validation failures are programming or setup errors. They raise before the first batch is submitted rather than appearing as per-request inference failures.

## Batch Preview

Callers can preview a batch without performing inference. `InferenceOrchestrator.preview_batch` applies normal validation and batching, asks the adapter to render the selected EDSL batch, and returns generic `RenderedPrompt` records containing the request ID and effective user and system prompts.

Previewing the first small batch is the recommended preflight for a new experiment. It verifies prompt rendering, system-prompt behavior, request-to-model mapping, and batch cardinality before tokens are spent. No EDSL object crosses the adapter boundary.

## Synchronous and Asynchronous Batch Execution

The orchestrator provides two behaviorally equivalent execution interfaces:

- `run_batches`, a blocking iterator for synchronous callers;
- `run_batches_async`, an async iterator for callers already using an event loop.

Both interfaces:

1. validate the configuration and all requests;
2. preserve request order and partition pending requests into deterministic batches of at most `batch_size`;
3. delegate one batch at a time to the matching synchronous or asynchronous adapter method;
4. run or await the corresponding EDSL batch execution method;
5. verify and normalize exactly one terminal result for every submitted request;
6. yield an `InferenceBatchResult` before starting the next batch.

The synchronous path delegates to EDSL's synchronous `run` method. The asynchronous path delegates to EDSL's native `run_async` method. The synchronous API does not create or drive an event loop, and the asynchronous API does not hide blocking EDSL execution in a worker thread.

Batches are submitted sequentially. EDSL runs the interviews within each batch in parallel and applies its own retry and rate-limit behavior. This bounds the amount of uncheckpointed work and prevents later batches from spending tokens before the caller has inspected, parsed, and persisted the current batch.

An `InferenceBatchResult` contains:

- a one-based batch number;
- the total number of batches;
- elapsed execution time for the batch;
- normalized results in the same order as the submitted requests.

The batch number, total, and elapsed time support progress reporting and an observed-throughput estimate after early batches. They do not promise a precise completion time because provider latency and rate limits can vary.

The orchestrator does not begin the next batch until the caller requests the next item from the iterator or async iterator. This gives the calling stage an explicit point to parse results, stop on a systemic problem, and perform atomic checkpoint writes.

## EDSL Boundary

`EDSLAdapter` translates a generic request batch and model definitions into Expected Parrot questions, surveys, agents when system prompts are present, models, interviews, and jobs. It exposes matching synchronous and asynchronous batch methods that call EDSL's native `run` and `run_async` methods and convert EDSL responses and terminal failures into the same generic results.

The adapter must preserve the submitted request set without accidentally creating additional scenario, persona, or model combinations. Request IDs are carried through the EDSL job so returned outcomes can be associated without relying on EDSL list positions.

No other package component depends directly on EDSL-specific classes. The implementation must declare and test a supported EDSL version range rather than relying on an arbitrary installed version.

## Results and Failures

Each `InferenceResult` contains:

- the request ID;
- the model configuration ID;
- normalized response content as `str | None`;
- caller metadata copied from the request;
- terminal error information as `InferenceError | None`.

Because `InferenceRequest` defines a free-text prompt and no response schema, successful normalized content is a string. A successful result has non-null content and no error. A failed result has null content and an `InferenceError` containing a stable error type and human-readable message.

EDSL performs its configured retry behavior before the adapter reports a terminal request failure. Retryability and attempt scheduling are therefore not represented or reimplemented by LLM AuditKit.

Individual terminal model failures are returned with their request IDs so callers can record them and continue. A systemic batch failure, such as missing or duplicate result identities, unexpected result cardinality, or an inability to normalize the EDSL response set, raises and stops execution before another batch is submitted.

The inference layer reports outcomes but does not decide how domain responses are parsed, checkpointed, or persisted.

## Checkpoint and Resume Contract

The shared inference layer performs no file writes. After a completed batch is yielded, the calling stage applies its stage-specific `save_after_each_result` policy. When enabled, the caller may atomically persist each normalized result from that completed batch before requesting the next batch. When disabled, it can retain results in memory until the stage finishes.

No new local checkpoint becomes available while an EDSL batch is still running. Consequently, `batch_size` bounds the logical work between checkpoint opportunities. On resume, the calling stage rebuilds requests from stable identifiers and omits completed requests; batch boundaries themselves do not form durable identity.
