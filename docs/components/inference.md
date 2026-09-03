# Shared Inference

[View the shared inference diagram.](../architecture/inference.mmd)

## Overview

The inference package provides reusable LLM inference for template generation, experiment execution, and future package workflows. Expected Parrot EDSL is the execution backend, but EDSL-specific objects do not leak into calling pipeline stages.

For installation and task-oriented examples, see
[Using Shared Inference](../guides/shared_inference.md). This page defines the detailed
component contract and implementation boundaries.

The shared layer validates and batches generic requests, partitions each logical batch into EDSL-compatible job groups, delegates those jobs to EDSL, and normalizes the returned outcomes. Requests can share one EDSL job when they use the same model configuration and response format. The adapter creates one explicitly paired EDSL interview for each request, preserving that request's user prompt, persona, system instruction, and request ID without generating extra combinations. EDSL owns parallel interview execution, provider rate limiting, caching, and retry behavior within each submitted job. LLM AuditKit does not implement a second worker pool or retry loop around individual EDSL interviews.

## Public API

The supported entry points are exported from `llm_auditkit.inference`. Construct one
`InferenceOrchestrator` with an `EDSLAdapter`, then use the same requests and
configuration with either execution interface:

```python
from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceOrchestrator,
    InferenceRequest,
    ModelConfig,
)

config = InferenceConfig(
    models=[
        ModelConfig(
            config_id="screening-model-v1",
            provider="your-edsl-service",
            model="your-model-name",
            parameters={"temperature": 0.2},
        )
    ],
    batch_size=25,
)
requests = [
    InferenceRequest(
        request_id="candidate-001:screening-model-v1",
        prompt="Evaluate this synthetic candidate profile.",
        system_prompt="Evaluate the candidate using the supplied evidence.",
        persona="You are a hiring manager.",
        model_config_id="screening-model-v1",
        metadata={"candidate_id": "candidate-001"},
    )
]

inference = InferenceOrchestrator(EDSLAdapter())
preview = inference.preview_batch(requests, config)

for batch in inference.run_batches(requests, config):
    # Parse and checkpoint this completed batch before requesting the next one.
    persist(batch.results)
```

For an application that already uses an event loop, replace the synchronous loop with
the native asynchronous interface:

```python
async def run_inference() -> None:
    async for batch in inference.run_batches_async(requests, config):
        await persist_async(batch.results)
```

`preview_batch` renders prompts without performing inference. Both execution methods
are lazy at the logical-batch boundary: the next batch is not submitted until the
caller advances its iterator. The `persist` functions above are caller-owned examples,
not functions provided by LLM AuditKit.

## Optional Live OpenAI Tests

The regular test suite includes opt-in integration tests that exercise prompt preview,
synchronous batching, and asynchronous execution through the public orchestrator and
the real EDSL OpenAI backend. They are collected but skipped unless the paid-network
test gate is explicitly enabled.

Copy [`.env.example`](../../.env.example) to `.env` and provide a local value for
`OPENAI_API_KEY`. The `.env` file and common variants are ignored by Git; never commit
provider credentials. The smoke tests use `gpt-4.1-nano`. Run them with:

```bash
python -m pip install -e ".[test]"
python -m pytest --run-live-inference tests/integration/test_openai_inference.py -v
```

Supplying `--run-live-inference` without the required API key fails during test setup.
Running `python -m pytest` without the flag skips the live-test fixtures and never
performs live model inference. The live tests intentionally use three short logical
completions, but they still consume provider quota, may incur cost, and can result in
additional provider attempts when EDSL applies its retry behavior.

## Requests

Callers submit domain-neutral `InferenceRequest` objects containing:

- a stable request ID;
- a user prompt;
- an optional system instruction;
- an optional persona;
- the target model configuration ID;
- an optional generic response format;
- caller-defined metadata used to associate the result with domain data.

A request ID must be unique within one inference run and stable when the same logical request is resumed. Calling stages must derive it from durable domain identifiers rather than DataFrame row positions. If prompt-defining inputs or the selected model configuration change in a way that invalidates an existing result, the calling stage must also invalidate the corresponding completion identity.

`InferenceConfig` is the run-level model catalog and batching policy. Each request's
`model_config_id` selects one `ModelConfig.config_id` from that catalog; provider,
model, and parameter values are not duplicated on individual requests. The caller
passes the request collection and configuration together to preview or execute it.

`prompt` is always a string. The adapter supplies a non-null `system_prompt` as the standard EDSL `Agent.instruction` and a non-null `persona` as the standard `Agent` `persona` trait. If neither is supplied, it creates an empty EDSL `Agent`; if only a persona is supplied, EDSL uses its default agent instruction. EDSL's normal agent and prompt rendering remain authoritative, and preview exposes the effective combined system prompt.

`response_format=None` requests free text and preserves the existing
`QuestionFreeText` behavior. The supported generic structured format is
`DictResponseFormat`, which contains an ordered list of `ResponseField` definitions,
whether a comment is included, and whether the backend should include explicit
value-type hints in the rendered question. Each response field has a JSON-compatible
value type supported by the adapter, and a human-readable description. Disabling type
hints omits them from EDSL's prompt but does not change the normalized field contract.
The EDSL adapter maps this generic format to `QuestionDict`; callers never construct or
receive an EDSL question type directly.

Response format is part of adapter job compatibility. Requests with different response
formats are submitted in different EDSL job groups even when their model configuration
matches. Persona and system-instruction differences do not split a group because each
request is represented by its own paired interview.

Request metadata is optional caller-owned convenience context. It is not sent to the
model or used for execution decisions. The inference layer copies it to the normalized
result so callers can associate outcomes with application records without parsing the
request ID; the request ID remains the authoritative identity.

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

`batch_size` is the maximum number of logical `InferenceRequest` objects in one LLM AuditKit batch. It is not the number of batches and is not necessarily a number of DataFrame rows. For example, one experiment row expanded across five personas and three models represents fifteen logical requests. A logical batch can require multiple EDSL jobs when its requests use different model configurations or response formats.

Concurrency and retry counts are deliberately not duplicated in `InferenceConfig`. EDSL manages those behaviors for each submitted job using the supported EDSL version and its execution configuration.

## Validation

Before making any model call, the orchestrator validates the complete configuration and request collection, including:

- at least one model and a positive batch size;
- unique, non-empty model configuration IDs;
- non-empty provider and model names;
- JSON-compatible provider parameters that do not override EDSL model identity fields;
- unique, non-empty request IDs;
- non-empty prompts;
- optional system prompts that are strings when provided;
- optional personas that are strings when provided;
- supported, internally consistent response formats with unique non-empty field names;
- string-keyed request metadata dictionaries;
- references to known model configuration IDs.

Configuration and request validation failures are programming or setup errors. They raise `InferenceConfigurationError` or `InferenceRequestValidationError` before the first batch is submitted rather than appearing as per-request inference failures.

## Batch Preview

Callers can preview a batch without performing inference. `InferenceOrchestrator.preview_batch` applies normal validation and batching, asks the adapter to render the selected logical batch through its compatible EDSL job groups, and returns generic `RenderedPrompt` records containing the request ID and effective user and system prompts.

Previewing the first small batch is the recommended preflight for a new experiment. It shows the effective prompts rendered by EDSL and verifies request-to-model mapping and batch cardinality before tokens are spent. No EDSL object crosses the adapter boundary.

## Synchronous and Asynchronous Batch Execution

The orchestrator provides two behaviorally equivalent execution interfaces:

- `run_batches`, a blocking iterator for synchronous callers;
- `run_batches_async`, an async iterator for callers already using an event loop.

Both interfaces:

1. validate the configuration and all requests;
2. preserve request order and partition pending requests into deterministic batches of at most `batch_size`;
3. delegate one logical batch at a time to the matching synchronous or asynchronous adapter method;
4. partition that batch into deterministic EDSL job groups keyed by model configuration and response format, build one paired EDSL interview per request, then run or await each group with the corresponding EDSL execution method;
5. verify and normalize exactly one terminal result for every submitted request;
6. yield an `InferenceBatchResult` before starting the next batch.

The synchronous path delegates to EDSL's synchronous `run` method. The asynchronous path delegates to EDSL's native `run_async` method. The synchronous API does not create or drive an event loop, and the asynchronous API does not hide blocking EDSL execution in a worker thread.

Logical batches are submitted sequentially. The adapter also submits a batch's EDSL job groups sequentially so LLM AuditKit does not create another concurrency layer. EDSL runs the scenario interviews within each job group in parallel and applies its own retry and rate-limit behavior. This bounds the amount of uncheckpointed work and prevents later batches from spending tokens before the caller has inspected, parsed, and persisted the current batch.

An `InferenceBatchResult` contains:

- a one-based batch number;
- the total number of batches;
- elapsed execution time for the batch;
- normalized results in the same order as the submitted requests.

The batch number, total, and elapsed time support progress reporting and an observed-throughput estimate after early batches. They do not promise a precise completion time because provider latency and rate limits can vary.

The orchestrator does not begin the next batch until the caller requests the next item from the iterator or async iterator. This gives the calling stage an explicit point to parse results, stop on a systemic problem, and perform atomic checkpoint writes.

## EDSL Boundary

`InferenceAdapter` is the domain-neutral protocol consumed by `InferenceOrchestrator`. It accepts only generic requests and a model-configuration lookup and returns only generic rendered prompts or normalized results. This protocol is also the test seam for exercising orchestration without importing EDSL or making network calls.

`EDSLAdapter` implements that protocol by translating a generic request batch and model definitions into Expected Parrot questions, surveys, agents, models, scenarios, interviews, and jobs. Each adapter-created job is limited to one model configuration and one response format. Every request becomes one explicit interview pairing its scenario with its own agent and the group's model and survey, so varying personas or instructions cannot create a Cartesian product. Free-text formats use `QuestionFreeText`; generic dictionary formats use `QuestionDict`. The adapter exposes matching synchronous and asynchronous batch methods that call EDSL's native `run` and `run_async` methods for each group and convert EDSL responses and terminal failures into the same generic results.

When a provider returns token log probabilities, the adapter extracts them from the EDSL
result and normalizes them into ordered `TokenLogprob` records containing the emitted
token and its natural log probability. Provider raw responses and EDSL result objects
remain behind the adapter boundary. Absence of token log probabilities is represented
generically so the calling stage can decide whether they are optional or required for
its domain result.

The adapter must preserve the submitted request set without accidentally creating additional scenario, persona, or model combinations. Request IDs are carried through the EDSL job so returned outcomes can be associated without relying on EDSL list positions.

No other package component depends directly on EDSL-specific classes. The package
installs EDSL's `inference` dependency extra and supports `edsl>=1.0.8,<1.1`;
compatibility outside that range is not implied.

## Results and Failures

Each `InferenceResult` contains:

- the request ID;
- the model configuration ID;
- generated response content as `str | None`;
- structured content as a JSON-compatible dictionary when requested;
- an optional structured-response comment;
- normalized emitted-token log probabilities when returned by the provider;
- the effective rendered prompt when available from execution;
- caller metadata copied from the request;
- terminal error information as `InferenceError | None`.

For free-text requests, a successful result has generated string content and no
structured content. For dictionary requests, a successful result retains the generated
string for auditability and also contains the validated generic dictionary and optional
comment returned through EDSL. If EDSL returns no validated dictionary but preserves
complete generated content, the adapter may recover the first dictionary whose keys
exactly match the requested response fields. This narrow fallback handles fenced or
pretty-printed multiline dictionaries that EDSL 1.0.8 splits before `QuestionDict`
validation; Markdown fences are discarded and other surrounding text is retained as
the comment. Content that does not match the requested fields remains a failed result.
Token log probabilities are supplemental normalized
data and may be absent when they were not requested or the provider does not supply
them. The effective rendered prompt uses the same generic `RenderedPrompt` type as
preview and lets calling stages persist the prompts actually rendered by EDSL without
retaining an EDSL result object. A failed result has no successful content and an
`InferenceError` containing a stable error type and human-readable message.

EDSL performs its configured retry behavior before the adapter reports a terminal request failure. Retryability and attempt scheduling are therefore not represented or reimplemented by LLM AuditKit.

When EDSL returns a request result without response content, the adapter reports a terminal `EDSLInferenceError`. If EDSL's task history provides an exception that can be associated with that request ID, the adapter preserves its exception type and message instead. An exception from `run` or `run_async` that prevents the adapter from receiving and associating the complete result set is a systemic batch failure.

Individual terminal model failures are returned with their request IDs so callers can record them and continue. A systemic batch failure, such as missing or duplicate result identities, unexpected result cardinality, or an inability to normalize the EDSL response set, raises and stops execution before another batch is submitted.

The inference layer reports outcomes but does not decide how domain responses are parsed, checkpointed, or persisted.

## Checkpoint and Resume Contract

The shared inference layer performs no file writes. After a completed batch is yielded,
the calling stage applies its own configurable checkpoint policy before requesting the
next batch. Experiment execution can parse and apply the entire batch and then perform
one atomic CSV replacement; other stages can define a different result boundary. When
incremental checkpointing is disabled, the caller can retain results in memory until
the stage finishes.

No new local checkpoint becomes available while any EDSL job group for the current logical batch is still running. Consequently, `batch_size` bounds the logical work between checkpoint opportunities. On resume, the calling stage rebuilds requests from stable identifiers and omits completed requests; batch and job-group boundaries themselves do not form durable identity.
