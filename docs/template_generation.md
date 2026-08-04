# Template Generation

## Overview

The template generation stage converts each dataset row into one or more resume templates using an LLM. The process is configurable through `TemplateGenerationConfig` and supports concurrent generation with incremental checkpointing.

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
- Maximum concurrent LLM requests.
- Checkpointing options.

## Processing

For every dataset row:

1. Construct the prompt using the row contents and configuration.
2. Submit the prompt to the configured `LLMClient`.
3. Parse the generated templates.
4. Store the generated templates.
5. Incrementally save the updated dataset.

Rows are processed concurrently using an asynchronous worker pool.

## Concurrency

Each dataset row is treated as an independent task.

Generation requests execute concurrently up to `max_concurrency`.

All writes to the shared output dataset are protected by a single synchronization lock to prevent concurrent modification and file corruption.

## Checkpointing

Generation is fault tolerant.

After every completed row:

- the output dataset is updated;
- the dataset is written to disk.

If generation is interrupted, the process can resume from the latest checkpoint.

## Resume Behavior

When starting generation, rows that already contain all required template columns are skipped automatically.

This allows interrupted jobs to resume without repeating completed LLM calls.

## Failure Handling

Failures are isolated to individual rows.

If a row fails after all retry attempts:

- template columns remain empty;
- an error message is recorded;
- processing continues for the remaining rows.

## Notes

Prompt construction is an internal implementation detail of `TemplateGenerator` and is intentionally not exposed as a public interface.
