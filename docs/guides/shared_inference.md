# Using Shared Inference

This guide shows how to send prompts through LLM AuditKit's implemented shared
inference package. The dataset, template, experiment, and regression pipeline stages
are not implemented yet; today, users construct generic inference requests directly.

For internal contracts and design rationale, see the
[shared inference component documentation](../components/inference.md).

## Install from the Repository

LLM AuditKit is not yet published as a released package. From the repository root,
create a Python 3.10 environment and install it in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Configure OpenAI Credentials

Copy the credential template and add your key:

```bash
cp -n .env.example .env
```

```dotenv
OPENAI_API_KEY=your-key-here
```

The repository ignores `.env` and common variants. Never add a real credential to
source control. Provider calls consume quota and may incur cost.

The included examples use `gpt-4.1-nano`, which was verified with EDSL 1.0.8. To use
another model or provider in application code, change the `ModelConfig` values and
provide credentials using that provider's EDSL-supported environment variables or
credential store.

## Run the Examples

The synchronous example previews the effective prompt and then makes one OpenAI call:

```bash
python examples/shared_inference_sync.py
```

The asynchronous example makes the equivalent call through EDSL's native async API:

```bash
python examples/shared_inference_async.py
```

See the complete source for
[`shared_inference_sync.py`](../../examples/shared_inference_sync.py) and
[`shared_inference_async.py`](../../examples/shared_inference_async.py).

## Build a Configuration

Each `ModelConfig` names one provider/model configuration. Its `config_id` is the
stable identifier used by requests and persisted results:

```python
from llm_auditkit.inference import InferenceConfig, ModelConfig

config = InferenceConfig(
    models=[
        ModelConfig(
            config_id="openai-screening-v1",
            provider="openai",
            model="gpt-4.1-nano",
            parameters={"temperature": 0.2},
        )
    ],
    batch_size=25,
)
```

`batch_size` is the maximum number of logical requests submitted before control
returns to your code. It is not a DataFrame row count. EDSL manages parallel model
interviews, retries, caching, rate limits, and provider scheduling within each
submitted job.

Use a new `config_id` when changing the provider, model, or parameters in a way that
should invalidate previously saved results. Do not put API keys in `parameters`.

Think of `InferenceConfig` as the run-level model catalog plus batching policy. A
request does not repeat its provider, model name, or parameters. Instead, its
`model_config_id` selects exactly one `ModelConfig.config_id` from that catalog. The
orchestrator receives the request collection and configuration together:

```python
preview = inference.preview_batch(requests, config)
batches = inference.run_batches(requests, config)
```

This keeps repeated requests small, allows one run to target multiple configured
models, and lets the orchestrator reject unknown model configuration IDs before making
provider calls.

## Build Requests

Each request contains one user prompt, an optional system prompt, a target model
configuration ID, and caller-owned metadata:

```python
from llm_auditkit.inference import InferenceRequest

requests = [
    InferenceRequest(
        request_id="candidate-001:openai-screening-v1",
        prompt="Evaluate this synthetic candidate profile.",
        system_prompt="You are a hiring manager.",
        model_config_id="openai-screening-v1",
        metadata={"candidate_id": "candidate-001"},
    )
]
```

Use durable request IDs derived from domain identifiers. Do not use a DataFrame row
number, list position, or random value if results will later be resumed. Request IDs
must be unique within a run.

Requests can use different models and system prompts. LLM AuditKit groups compatible
requests for EDSL without changing their input or output order.

## Use Metadata to Handle Results

`metadata` is optional caller-owned context. It is not added to the prompt and does not
affect model selection, batching, or execution. The inference layer copies it from each
request onto the matching `InferenceResult`, making it convenient to reconnect results
to application data:

```python
for batch in inference.run_batches(requests, config):
    for result in batch.results:
        candidate_id = result.metadata["candidate_id"]

        if result.error is not None:
            record_failure(
                candidate_id=candidate_id,
                error_type=result.error.type,
                message=result.error.message,
            )
        else:
            record_response(
                candidate_id=candidate_id,
                content=result.content,
            )
```

For direct shared-inference use, choose the metadata fields that make downstream
processing convenient and keep their values serialization-friendly. Domain pipeline
stages such as experiment execution will define a consistent metadata schema rather
than asking users to assemble it manually. `request_id` remains the authoritative
request identity; metadata is convenience context and should not replace it.

## Preview Before Spending Tokens

Preview the first logical batch when introducing a new prompt or model configuration:

```python
from llm_auditkit.inference import EDSLAdapter, InferenceOrchestrator

inference = InferenceOrchestrator(EDSLAdapter())
preview = inference.preview_batch(requests, config)

for rendered in preview.prompts:
    print(rendered.request_id)
    print(rendered.system_prompt)
    print(rendered.user_prompt)
```

Preview uses EDSL's normal rendering but does not perform model inference. It is useful
for checking system-prompt placement, request identity, model mapping, and batch size.

## Run Synchronously

`run_batches` returns a blocking iterator. Handle and persist each completed batch
before requesting the next one:

```python
from llm_auditkit.inference import InferenceException

try:
    for batch in inference.run_batches(requests, config):
        print(
            f"batch {batch.batch_number}/{batch.total_batches} "
            f"completed in {batch.elapsed_seconds:.2f}s"
        )
        for result in batch.results:
            if result.error is not None:
                print(result.request_id, result.error.type, result.error.message)
            else:
                print(result.request_id, result.content)

        # Parse and atomically checkpoint batch.results here if needed.
except InferenceException as error:
    print(f"Inference stopped before a trustworthy batch was available: {error}")
```

The inference layer does not write checkpoints. Your application decides how to
parse, validate, and atomically persist the results before advancing the iterator.

## Run Asynchronously

Use `run_batches_async` from code that already owns an event loop:

```python
async def run_inference() -> None:
    async for batch in inference.run_batches_async(requests, config):
        for result in batch.results:
            if result.error is not None:
                print(result.request_id, result.error.type, result.error.message)
            else:
                print(result.request_id, result.content)

        # Await application-owned parsing and checkpointing here.
```

The synchronous and asynchronous APIs use the same validation, batching, result
ordering, and failure semantics. Choose based on the calling application; do not wrap
the synchronous API in a thread or run a separate request-worker pool.

## Understand Outcomes

Every completed logical request produces an `InferenceResult` with:

- `request_id`: the stable submitted identity;
- `model_config_id`: the selected model configuration;
- `content`: response text on success, otherwise `None`;
- `metadata`: a copy of the submitted metadata;
- `error`: terminal per-request error details, otherwise `None`.

A terminal provider failure is returned as a result with `error` populated, allowing
other requests in the batch to remain usable. Validation errors and systemic failures
raise an `InferenceException` subclass and stop execution before a later batch begins.

## Run the Optional Live Tests

To verify the installed integration with three small paid OpenAI completions, run:

```bash
python -m pip install -e ".[test]"
python -m pytest --run-live-inference tests/integration/test_openai_inference.py -v
```

The normal `python -m pytest` command collects these tests but skips them. The explicit
flag is always required before the test suite can make provider calls.
