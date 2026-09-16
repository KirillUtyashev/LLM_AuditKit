# Template Generation

[View the template generation diagram.](../architecture/template_generation.mmd)

## Overview

The template generation stage converts each dataset row into one or more resume templates using the shared [inference layer](inference.md). The process is configurable through `TemplateGenerationConfig` and supports batched EDSL execution with incremental checkpointing.

## Input

- Input dataset: `pandas.DataFrame`
- Required columns:
  - `scenario_id`
  - `Text`

`scenario_id` is the durable row identity used for requests, result association, checkpointing, and resume behavior. A DataFrame row index is never used as durable identity.

## Output

The output is a copy of the input dataset with additional columns:

- `template_1`
- `template_2`
- ...
- `template_N`

where `N = templates_per_job_posting`.

## Configuration

Template generation behavior is controlled through `TemplateGenerationConfig`, including:

- Number of templates per job posting.
- Skill section definitions.
- Number of work experiences.
- Number of student experiences.
- Education degrees.
- Shared `InferenceConfig`, including model definitions and inference batch size.
- Target model configuration ID (`model_config_id`) used for template generation.
- Whether to save after each result (`save_after_each_result`).

The target model configuration ID must reference exactly one model in the shared inference configuration. If the model or behavior-affecting parameters change, the model configuration ID and any incompatible checkpoint state must also change.

## Request Construction

For every incomplete dataset row, `TemplateGenerator`:

1. constructs the prompt from the row contents and template configuration;
2. derives a stable request ID from durable stage identity, including `scenario_id` and the target model configuration;
3. builds one generic `InferenceRequest` whose metadata includes `scenario_id`;
4. expects one free-text response containing all configured `N` templates for that row.

One logical inference request therefore represents one source row, regardless of the configured number of templates. The shared inference `batch_size` is also the maximum number of template-generation rows in one logical inference batch.

## Preview

`TemplateGenerator.preview` builds the pending requests and returns the selected shared-inference batch preview without making model calls. It exposes the effective EDSL-rendered user and system prompts through generic preview types.

Previewing the first batch with a small `inference.batch_size` is the recommended validation step before a large run. It allows prompt, model, request-identity, and cardinality problems to be found before tokens are spent.

## Processing and Batching

`TemplateGenerator.generate` consumes the synchronous `InferenceOrchestrator.run_batches` iterator, while `TemplateGenerator.generate_async` consumes `InferenceOrchestrator.run_batches_async`. Both paths follow the same processing contract:

1. build requests for all incomplete rows;
2. await one EDSL-managed batch;
3. parse and validate every normalized result in that completed batch;
4. update and checkpoint the output dataset according to configuration;
5. request the next batch only after the current batch has been handled safely.

Both entry points are first-class. The synchronous path delegates to EDSL's native blocking execution, and the asynchronous path delegates to EDSL's native async execution. They use the same request construction, batch boundaries, parsing, failures, checkpoint behavior, and returned DataFrame shape.

Batches are sequential at the LLM AuditKit layer. EDSL owns parallel interview execution, provider rate limiting, caching, and retries within each submitted batch. Template generation does not create a separate asynchronous row-worker pool.

The stage can report completed batches and rows and use observed batch duration to estimate remaining time. Any estimate is informational because provider latency and rate limits can vary.

## Checkpointing

Generation supports incremental checkpointing through `save_after_each_result`. In this stage, one result means one completed source row and all `N` templates generated for that row.

When `save_after_each_result` is enabled, after a batch returns, each successfully parsed row result is applied and the updated dataset is written using atomic replacement before the next logical batch is requested. Failed row outcomes and their error messages are checkpointed through the same stage-owned store.

When it is disabled, completed rows remain in memory and the dataset is persisted after generation finishes.

No local result becomes available while the EDSL job groups for a logical batch are in flight. The configured inference batch size therefore bounds the number of template-generation rows between checkpoint opportunities.

## Resume Behavior

When starting generation, rows that already contain all required template columns are skipped automatically.

This allows interrupted jobs to resume without repeating completed logical requests. Batch boundaries are not durable identifiers and may differ between the original and resumed runs.

## Failure Handling

Failures attributable to an individual request are isolated to that row. After EDSL completes its retry behavior:

- template columns remain empty for a terminally failed request;
- an error message is recorded;
- processing can continue for the remaining requests.

Before requesting another batch, the stage validates result association and parsed template cardinality. A systemic failure that indicates a broken prompt or integration contract, such as missing request identities, unexpected batch cardinality, or consistently unparseable template structure, stops the run so later batches do not spend additional tokens.

## Notes

Prompt construction and template parsing remain internal responsibilities of `TemplateGenerator`. EDSL execution details are contained in the shared inference package.
