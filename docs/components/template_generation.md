# Template Generation

[View the template generation diagram.](../architecture/template_generation.mmd)

## Overview

Template generation converts each job-posting scenario into a configurable number
`N` of resume templates through the shared [inference layer](inference.md). One
logical inference request represents one source scenario and returns all `N`
templates together. Generating the templates jointly allows the prompt to require
comparable quality and relevance across the candidate set.

The stage accepts and returns `pandas.DataFrame` objects. It does not load an input
path; dataset loading remains the single path-to-DataFrame boundary. Persistence is
provided by a caller-supplied `TemplateStore` whose output path is separate from the
domain configuration. A strict YAML composition format records the dataset and output
paths alongside the domain configuration without moving path loading into this stage.

## Input and Dataset Schema

`TemplateDatasetSchema` maps template-generation concepts to input columns:

- `job_posting_column`: the source column containing the job posting;
- `context_columns`: optional semantic aliases such as `city`, `state`, `year`, and
  `category` mapped to source columns used by prompt templates.

The configured job posting must exist and contain a nonempty string in every row.
Configured context columns must exist. Input column names must be unique strings.

Input rows may contain a canonical `scenario_id` column. Supplied IDs must be unique,
nonempty strings and are preserved. When the column is absent, template generation
derives a collision-resistant ID from the complete source row using the same shared
identity algorithm as experiment execution. Column order and the DataFrame index do
not affect a derived ID. Exact duplicate rows are rejected because they cannot be
distinguished durably; callers can add an ordinary stable replicate column when
repeated scenarios are intentional.

## Configuration

`TemplateGenerationConfig` contains:

- `templates_per_scenario`: positive output cardinality `N`;
- `dataset_schema`: the input-column mapping;
- `prompt_template`: the user prompt template text;
- `system_prompt_template`: optional system-prompt template text;
- `required_placeholders`: ordered placeholder names that every generated template
  must preserve;
- shared `InferenceConfig`, including model definitions and logical batch size;
- `model_config_id`: the one model configuration used for generation;
- `save_after_each_result`: whether each handled row result is atomically persisted
  before the next result is applied.

The selected model configuration ID must reference exactly one model in the shared
inference configuration. Other configured models remain available to other callers but
are not used by this generation run.

## YAML Run Configuration

`load_template_generation_run_config` loads a complete user-facing run definition from
YAML and returns `TemplateGenerationRunConfig`. The run configuration contains:

- the dataset path to hand to the dataset-loading stage;
- the output CSV path used to construct `TemplateStore`;
- an explicit `sync` or `async` execution mode; and
- the validated `TemplateGenerationConfig` consumed by this stage.

The YAML separates dataset schema, prompt files, output, generation behavior,
execution policy, and inference models. Relative dataset, prompt, and output paths are
resolved from the YAML file's directory. User and optional system prompts must be
UTF-8 `.txt` files. Unknown fields, duplicate YAML keys, missing required fields,
invalid modes, colliding dataset/output paths, and non-CSV output paths are rejected
before inference.

The YAML loader reads configuration and prompt text only. It does not load the dataset;
the configured path crosses into a DataFrame through dataset loading, after which
`TemplateGenerator` retains its DataFrame-only contract. A loadable configuration
example is available at
[`configs/template_generation/synthetic_template_generation.yaml`](../../configs/template_generation/synthetic_template_generation.yaml).

Skill sections, work-history counts, education layouts, and era-specific resume or
application structures belong in versioned prompt files rather than hard-coded Python
configuration classes. This supports materially different historical formats without
changing runtime code. The YAML loader reads those files into
`TemplateGenerationConfig`; the DataFrame API itself remains path-independent.

## Prompt Rendering

Prompt templates use single-brace fields such as `{job_posting}`, `{city}`, and
`{year}`. Available fields are:

- every source DataFrame column;
- the canonical `{job_posting}` alias;
- configured semantic `context_columns` aliases;
- `{templates_per_scenario}`;
- `{required_placeholders}`, rendered as the configured canonical placeholder tokens.

The user prompt must reference `{job_posting}`, `{templates_per_scenario}`, and
`{required_placeholders}` so changing configuration cannot silently leave a hard-coded
cardinality or placeholder list in the instructions. Unknown fields and conflicting
aliases fail before inference.

The optional system-prompt template uses the same rendering context. Its rendered text
is passed normally as `InferenceRequest.system_prompt`; template generation does not
override or reconstruct EDSL system prompts. When it is omitted, EDSL uses its default
agent instruction. Template generation does not require an EDSL persona.

Generated resume placeholders use the distinct syntax `{{placeholder_name}}`, where
names match `[A-Za-z][A-Za-z0-9_]*`. Double-brace tokens are preserved literally while
the surrounding prompt is rendered. For example, a prompt can use the single-brace
field `{required_placeholders}` to show the model tokens such as `{{name}}` and
`{{address}}` that must remain in each output template.

## Stable Generation Identity

Template generation computes an internal `generation_fingerprint` from every setting
that can change generated content:

- a fingerprint schema version;
- dataset-schema mappings;
- user and system prompt text;
- `templates_per_scenario`;
- ordered required placeholders; and
- the selected model configuration, including provider, model, and parameters.

Batch size and checkpoint frequency are excluded because they do not define generated
content. The fingerprint is persisted in output and combined with `scenario_id` to
derive a stable request ID. A changed prompt, placeholder contract, selected model, or
other generation-defining setting therefore cannot reuse an incompatible checkpoint,
even when `N` remains unchanged. Users do not create or maintain this fingerprint.

## Request Construction and Structured Results

For every incomplete scenario, `TemplateGenerator` builds one generic
`InferenceRequest` containing:

- a request ID derived from `scenario_id` and `generation_fingerprint`;
- the rendered user prompt;
- the optional rendered system prompt;
- the selected model configuration ID;
- metadata containing the scenario ID and generation fingerprint; and
- a `DictResponseFormat` with ordered string fields `template_1` through
  `template_N` and no comment field.

The shared inference adapter maps this generic response format to EDSL's standard
dictionary-question behavior. Template generation never parses an EDSL object and does
not invent a delimiter protocol for multiple free-text templates.

A successful domain result must contain exactly `N` nonempty strings in configured
order. Templates must be pairwise distinct after surrounding whitespace is removed.
Every template must contain each configured `{{placeholder_name}}`, and any
double-brace placeholder token in a template must belong to the configured set.

## Preview

`TemplateGenerator.preview` builds pending requests and returns the selected
shared-inference batch preview without making model calls. It exposes the effective
EDSL-rendered user and system prompts through generic preview types.

Previewing the first small batch is the recommended validation step before a large
run. It verifies prompt rendering, placeholder instructions, selected model, request
identity, response fields, and request cardinality before tokens are spent.

## Synchronous and Asynchronous Execution

`TemplateGenerator.generate` consumes the synchronous
`InferenceOrchestrator.run_batches` iterator. `TemplateGenerator.generate_async`
consumes `InferenceOrchestrator.run_batches_async`. Both paths:

1. validate the complete DataFrame and configuration before inference;
2. initialize or validate the output checkpoint;
3. omit completed scenarios without changing pending order;
4. submit one deterministic logical batch through shared inference;
5. validate and associate every normalized result by request ID;
6. apply and checkpoint the handled row results according to configuration; and
7. request the next batch only after the current batch is handled safely.

The two methods have the same request order, parsing, failure semantics, checkpoint
boundaries, and returned DataFrame shape. The synchronous path uses EDSL's native
blocking execution and the asynchronous path uses its native async execution.

The shared inference `batch_size` is measured in template-generation requests. Because
one request represents one source scenario, it is also the maximum number of pending
scenario rows in one logical batch. Batches are submitted sequentially. EDSL owns
parallel interview execution, provider rate limiting, caching, and retries inside each
submitted job; template generation does not create another row-worker pool or retry
loop.

## Output Contract

The returned and persisted DataFrame contains one row per input scenario in input
order. It preserves all source columns and adds `scenario_id` when it was derived. It
also adds:

- `template_generation_fingerprint`;
- `template_generation_model_config_id`;
- `template_generation_request_id`;
- `template_1` through `template_N`;
- `template_generation_error_type`;
- `template_generation_error_message`.

Successful rows contain all `N` templates and no error. Failed rows retain their stable
identity and error information while template columns remain empty. Result column
names are reserved and cannot collide with source columns.

## Checkpointing and Resume

`TemplateStore` owns the output CSV and writes it using atomic replacement. Existing
checkpoints are loaded with source cells preserved as strings for comparison, then
caller-owned source values are restored so numeric-looking text and leading zeroes are
not changed by resume.

Before resume, the store validates the source scenario set and values, output schema,
generation fingerprint, model configuration, request IDs, and template/error fields.
Input row positions are never used as identity, and output is restored to current input
order.

When `save_after_each_result` is enabled, the stage first validates and associates the
entire completed logical batch. It then applies each successful or failed row result in
canonical order and performs one atomic CSV replacement after each result. When the
option is disabled, handled results remain in memory and the final DataFrame is written
once after generation finishes.

A row is complete only when its generation metadata matches the current configuration,
all `N` templates are valid and nonempty, and no error is present. Completed rows are
skipped. Failed or incomplete rows remain pending and are replaced by a later
successful result. Batch boundaries are not durable identity and may change on resume.

## Failure Handling

After EDSL completes its retry behavior, a terminal inference failure or invalid
template content is recorded as a request-level row error. Other requests continue,
and the failed scenario remains pending for a future run.

A systemic contract failure—such as missing or duplicate request IDs, unexpected
result cardinality, mismatched metadata, invalid batch progress, or an incompatible
checkpoint—raises and stops the run before another batch is submitted. Raw provider or
EDSL objects never cross the shared inference boundary.
