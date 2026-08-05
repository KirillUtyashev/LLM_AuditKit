# Template Generation

[View the template generation diagram.](architecture/template_generation.mmd)

## Overview

The template generation stage converts each dataset row into one or more resume templates using the shared [inference layer](inference.md). The process is configurable through `TemplateGenerationConfig` and supports concurrent generation with incremental checkpointing.

## Input

- Input dataset: `pandas.DataFrame`
- Required column:
  - `Text`

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
- Shared `InferenceConfig`, including model selection, concurrency, and retries.
- Target model configuration ID (`model_config_id`) used for template generation.
- Whether to save after each result (`save_after_each_result`).

## Processing

For every dataset row:

1. Construct the prompt using the row contents and configuration.
2. Build a generic `InferenceRequest` and submit it to `InferenceOrchestrator`.
3. Parse the returned `InferenceResult` into generated templates.
4. Store the generated templates.
5. Save the updated dataset according to the configured persistence behavior.

Rows are processed concurrently using an asynchronous worker pool.

## Concurrency

Each dataset row is treated as an independent task.

Generation requests execute concurrently up to `inference.max_concurrency`.

All writes to the shared output dataset are protected by a single synchronization lock to prevent concurrent modification and file corruption.

## Checkpointing

Generation supports incremental checkpointing through `save_after_each_result`. In this stage, one result means one completed source row and all `N` templates generated for that row.

When `save_after_each_result` is enabled, after every completed row:

- the output dataset is updated;
- the dataset is written to disk using atomic replacement.

When it is disabled, completed rows remain in memory and the dataset is persisted after generation finishes.

If generation is interrupted while incremental saving is enabled, the process can resume from the latest checkpoint.

## Resume Behavior

When starting generation, rows that already contain all required template columns are skipped automatically.

This allows interrupted jobs to resume without repeating completed LLM calls.

## Failure Handling

Failures are isolated to individual rows.

If a row fails after `inference.max_retries` attempts:

- template columns remain empty;
- an error message is recorded;
- processing continues for the remaining rows.

## Notes

Prompt construction and template parsing remain internal responsibilities of `TemplateGenerator`. EDSL execution details are contained in the shared inference package.
