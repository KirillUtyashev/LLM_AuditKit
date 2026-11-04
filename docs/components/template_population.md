# Template Population

[View the template population diagram.](../architecture/template_population.mmd)
[See the worked synthetic example and acceptance cases.](../guides/template_population.md)

## Status and Scope

### Local Development Checklist

- [x] Step 1: define the two input schemas, matching, syntax, and output contract.
- [x] Step 2: implement validation and deterministic filling with unit tests.
- [x] Step 3: verify representative reference template structures using synthetic data.
- [x] Step 4: verify arbitrary labels/counts and configurable applicant counts.
- [x] Step 5: check experiment-input compatibility and update documentation, diagrams, and examples.
- [x] Reconciled the step-one contract with the implementation, tests, diagrams,
  and examples from steps two through five on 2026-11-04.

The direct DataFrame handoff, ordered prompt example and checkpoint checks
are documented in the [handoff guide](../guides/template_population.md#pass-the-populated-table-to-experiment-execution).
The native local runners preserve applicant order, decisions, and token
probabilities with multiple requests in a logical batch. The
[backend regression checks](../guides/template_population.md#native-edsl-literal-text-and-interview-counts)
verify that literal question text reaches the model unchanged and that each
scenario uses only its assigned reviewer. At the end of step five, the full Python suite passed
546 tests with 5 opt-in live tests skipped on both EDSL 1.0.8 and 1.0.9.
The four earlier expected failures now have passing regression coverage.

### Step-one reconciliation

The two input schemas and the placeholder grammar matched the implementation.
The worked example produced both expected rows with all 28 columns in order.
The five reference families and the custom label and applicant counts use the
same API. The experiment checkpoint carries through supplied candidate IDs,
counts, and metadata in slot order. The review corrected CSV handling so
embedded NULs and carriage returns survive in the recorded prompt, and a
missing value in one row cannot round a large integer in another.

After those corrections, the full Python suite passed 550 tests on each of
EDSL 1.0.8 and 1.0.9, with five opt-in live tests skipped on each version.
The [researcher-owned EDSL handoffs](#later-cross-subissue-consistency-review)
remain open for the later cross-subissue review.

### Earlier verification

On 2026-11-03, the step-two baseline was rerun before step-three edits:
514 Python tests passed and 5 opt-in live-inference tests were skipped. The
eight new [reference-structure cases](../guides/template_population.md#reference-structure-verification)
cover five families, one mixed-form cohort, and two missing-required-value
failures. At completion of step three, 264 population tests passed; the full
suite had 522 passes and 5 live-inference skips.

The seven [step-four cases](../guides/template_population.md#custom-labels-and-applicant-counts)
verified 3, 6, and 10 distinct labels with two applicants, and 1, 5, 10,
and 11 applicants with one label. The full Python suite passed 529 tests,
with 5 opt-in live-inference tests skipped. Neither verification step
required a runtime or contract change.

### Population scope

This contract was defined in step one of issue #12. Step two implements the
DataFrame API, validation, and deterministic filling in
[`llm_auditkit.templates.population`](../../src/llm_auditkit/templates/population/__init__.py).

Population takes two already prepared `pandas.DataFrame` objects: a wide table
of job/applicant templates and a researcher-prepared table of exact replacement
values. It matches records, validates coverage, and substitutes literal text,
returning one complete set of `N` applicant resumes per template-table row.
Researchers have already chosen every assignment and combination. Population
makes no model calls, samples no values, computes no dates or experience,
constructs no quality conditions, and enumerates no combinations.

Researchers choose values and assignments while preparing the replacement
table. AuditKit validates those assignments and fills the templates in a
single pass. Researchers can also populate their templates independently and
enter the workflow at experiment execution. These choices are recorded in
[issue #12](https://github.com/KirillUtyashev/LLM_AuditKit/issues/12).
Step three verified milestone 1's two-table workflow against representative
synthetic templates. Step four verified milestone 2's user-defined label
sets and applicant counts using the same public API. Neither the labels
nor their number are hard-coded.

## DataFrame API and Configuration

```text
TemplatePopulator().populate(
    templates: pandas.DataFrame,
    replacements: pandas.DataFrame,
    config: TemplatePopulationConfig,
) -> pandas.DataFrame
```

Import `TemplatePopulator` and `TemplatePopulationConfig` from
`llm_auditkit.templates.population`. Construct the configuration with the
fields below; validation happens on `populate`, before processing inputs.
There is no population CLI or file-loading configuration.

Configuration describes columns, not data sources or research decisions:

| Field | Required value and meaning |
| --- | --- |
| `template_columns` | Nonempty mapping from explicit stable template IDs to distinct template text column names; e.g. `{"application": "template_1", "resume": "template_2"}`. |
| `placeholder_columns` | Mapping from placeholder labels to replacement-table payload columns; e.g. `{"name": "full_name"}`. Empty only when every template has no placeholders. Several labels may map to one column. |
| `job_posting_column` | Nonblank string, default `"Text"`. Must differ from `scenario_id` and every configured template text column. |

`N = len(template_columns)` is configurable and at least one. Template IDs
are explicit names, not inferred from column suffixes or input positions.
The template map does not define applicant order. One map applies to all rows
in a call; `(scenario_id, template_id)` identifies the particular template
text. Its column name is a storage location, not durable identity.

Every configured column must exist. Template text columns must differ from
`scenario_id`. Every template-map key must be a nonblank string; every
placeholder-map key, even an unused entry, must follow the label grammar below.
Mapping keys and column names are case-sensitive; there is no
trimming, coercion, fuzzy matching, or implicit same-name placeholder mapping.
File loading and saving stay at the composition/loading boundary, outside
this API and configuration.

## Input 1: Prepared Templates

Researchers can prepare this table directly. It also follows the
[generation stage's planned wide DataFrame shape](template_generation.md#output).
In either case, completed templates supplied to AuditKit use the
[placeholder syntax below](#placeholder-language-and-coverage).

| Columns | Constraints |
| --- | --- |
| `scenario_id` | Required nonblank string, unique within the table. Durable identity of one job and its intended applicant set. |
| `Text` (or `job_posting_column`) | Required nonblank job-posting string. Preserved without substitution. |
| Configured template text columns | Exactly `N` selected columns, conventionally `template_1` through `template_N`. Every cell is a nonblank string. Different cells may use different label sets, including none. |
| Other columns | Scenario/job metadata, preserved under the original names and with original values, subject to the scalar and collision rules below. |

A configured template ID is used once per scenario. All configured templates
must participate; additional unconfigured columns are metadata and are never
parsed as templates. Callers explicitly select the templates through the map.
No additional template-ID columns are required in the generation output.

`scenario_id` is the explicit job/applicant-set join key for these two tables;
it is not an experiment execution request or audit ID. If a researcher wants
several sets for the same underlying job, they must supply a separate template
row with a distinct `scenario_id` for each set and its matching replacement
rows. They should retain their underlying `job_id` as ordinary metadata to
link those sets. Population never duplicates rows or invents scenario IDs.
Identifiers must continue to denote the same content/assignments when reusing
experiment checkpoints; changed content, assignments, or `candidate_order`
require a new scenario identity. Candidate/template IDs can remain stable
across those explicitly supplied sets; a reused candidate ID must continue to
denote the same logical applicant, not simply whoever occupies that slot.

## Input 2: Researcher-Prepared Replacements

One row supplies one applicant's values for one named template in one scenario.

| Columns | Constraints |
| --- | --- |
| `scenario_id` | Nonblank string matching exactly one templates row. |
| `template_id` | Nonblank string matching exactly one key in `template_columns`. |
| `candidate_id` | Researcher-supplied nonblank stable string; unique within each scenario. May recur across scenarios to explicitly identify the same applicant. |
| `candidate_order` | Integer scalar (not a boolean or string). Within each scenario, exactly the permutation `1..N`; controls output slots only. |
| Payload columns | Exact insertion values and/or candidate metadata. Mapping determines which fields are inserted. All payload fields are preserved in the output, including mapped fields. |

`(scenario_id, template_id)` is unique, as is
`(scenario_id, candidate_id)`. Each templates row must match exactly `N`
replacement rows, one for every configured template ID, with no duplicate
candidate order. A row cannot target multiple templates, and one template
cannot silently produce several applicants. DataFrame index labels and
replacement-table row order have no matching or ordering significance.

An unknown scenario or template ID, duplicate key, unmatched template row,
missing applicant, or extra applicant is an error. There is no partial join,
silent drop, deduplication, or automatic expansion. Both inputs must have
unique nonblank string column names. Empty input tables are errors for this
contract, even if both have valid headers. Callers select a nonempty job scope
before invoking population.

## Placeholder Language and Coverage

A placeholder is exactly `{{label}}`, with a case-sensitive label matching
`[A-Za-z_][A-Za-z0-9_]*`. Users choose any label within that grammar. Whitespace
inside delimiters, expressions, format specifiers, attribute access, nested
placeholders, and empty labels are invalid. Thus `{{name}}` is valid, while
`{{ name }}`, `{{name.upper()}}`, and `{{}}` are errors. Ordinary words such as
`name` or `year` have no special meaning.

Parse each source template left to right with these rules:

1. `\{{` and `\}}` produce literal `{{` and `}}`, respectively; the leading
   backslash is removed. Escaped delimiters are literal text, never tokens.
2. An unescaped `{{` starts a placeholder and must end at the next unescaped
   `}}`, with exactly a valid label between them. Otherwise it is malformed.
3. An unescaped `}}` outside a placeholder is malformed. A lone `{` or `}`
   is ordinary text; all other characters, including other backslashes, are
   literal. For example, `{{{name}}}` is malformed, while `{name}` is literal.

Every distinct parsed label must be present in `placeholder_columns`, whose
values must name payload columns rather than the four structural columns.
Every configured mapping target must exist, even if unused in this batch.
Unused mapping entries are allowed. For each template, validate only the
mapped cells required by **that template's labels**. Matching the number of
columns to the number of placeholders is insufficient. Repeated occurrences
use the same supplied value.

A required replacement cell must be a nonblank string. `None`, `pandas.NA`,
`NaN`, `NaT`, `""`, and whitespace-only strings are errors when required.
Numeric, boolean, datetime, container, and other object values are not implicitly
converted to insertion text; researchers supply the exact string (e.g.
`"2004"`, `"3.0"`, or `"003"`) they want displayed. Nonblank strings retain
all leading/trailing whitespace, newlines, Unicode, and punctuation verbatim.

Replacement is a single pass over parsed source tokens. Inserted strings are
never parsed, escaped, evaluated, or recursively substituted. A value such as
`"Writes {{notes}} and {examples}"` remains exactly that text. Likewise,
`\{{name\}}` in a source template becomes literal `{{name}}` and needs no
mapped value. Completeness is assessed from source tokens, not by rejecting
braces remaining in the final text. Each final resume must still be a nonblank
string.

## Metadata, Missing Values, and Output

Metadata and payload cells support strings, booleans, integer scalars, finite
floating-point scalars (including pandas/NumPy scalar equivalents), and scalar
missing values (`None`, `pandas.NA`, `NaN`, `NaT`). Missing/empty unused payload
cells and missing metadata are preserved; they do not become insertion text.
Containers, nonmissing date/time objects, infinities, and other object types
are errors. There is no implicit JSON, date, number, or boolean formatting.
Numeric covariates remain numeric metadata; insertion text must be supplied
as a string. Scalar values and missingness are preserved without coercion;
exact pandas dtypes are not an output guarantee. Loading code is responsible
for retaining IDs/leading zeros and preparing `candidate_order` as integers.

Output has exactly one row per templates row, in the same row order, with a
new `RangeIndex`. It retains **every input template-table column**, including
unmodified template text, in its original column order. It then appends:

| Columns | Contents |
| --- | --- |
| `candidate_count` | Integer `N` on every row. |
| For each `i = 1..N`: `resume_<i>` | Populated text from the replacement row with `candidate_order == i`. |
| `candidate_<i>_id` | That row's supplied `candidate_id`. |
| `candidate_<i>_template_id` | That row's supplied `template_id`. |
| `candidate_<i>_template_column` | The source text column selected by `template_columns[template_id]`. |
| `candidate_<i>_<field>` | Each payload column's unchanged value, using its exact column name as `<field>`. |

Append each slot's fields together in the order above, with payload columns
in replacement-table column order after excluding the four structural fields.
This convention preserves all replacement information: `scenario_id` remains
the row key, and slot `i` records `candidate_order`. Slot numbers are presentation
positions only; candidate and template IDs provide identity even when order
changes. Original template text plus template ID/column and supplied values
retain the population provenance. No IDs or substantive indicators are derived
from names, text, or position.

Validate the entire prospective output namespace before rendering. Any collision
between a retained source column and an appended field, or between generated
fields, is an error; never overwrite or add suffixes automatically. For example,
source `resume_1`/`candidate_count` and payload `id`/`template_column` collide.
No payload metadata is promoted to scenario scope or merged by guessing.

The output must also avoid the existing experiment store's reserved names:
`experiment_id`, `persona_id`, `model_config_id`, `request_id`, `persona_name`,
`model`, `provider`, `persona_instruction`, `user_prompt`, `system_prompt`,
`generated_response`, `comment`, `picks`, `error_type`, `error_message`, and
names matching `(pick|logprob)[1-9][0-9]*`. `scenario_id` is allowed. These
restrictions apply to final column names: e.g. scenario metadata `comment`
is invalid, but payload `comment` becomes `candidate_1_comment` and is valid.
Rename conflicting input metadata explicitly before population.

The API does not mutate either input or configuration, write files, or perform
I/O. Validation is all-or-nothing: any failure returns no partial output and
leaves inputs untouched. Diagnostics should name offending fields, labels,
and scenario/template/candidate IDs where available, without dumping resumes
or replacement contents. Identical inputs/configuration produce identical
values and ordering; reordering replacement rows or changing input index labels
does not alter the result.

The public error hierarchy is `TemplatePopulationError`, with
`TemplatePopulationConfigurationError` for invalid configuration and
`TemplatePopulationDatasetError` for invalid tables, matching, scalar types,
or output columns. `TemplatePopulationPlaceholderError` subclasses the dataset
error for malformed source tokens, missing label mappings, or required cells
that are not nonblank strings. Unsupported scalar types fail dataset validation
even in mapped cells. Parser diagnostics include a zero-based source character
offset without quoting template contents. These errors are exported from the
same population package; parsing and validation helpers remain internal.

## Downstream Boundary

### Choosing which stages to use

Researchers can use AuditKit's population and experiment stages independently.
The two-table contract applies when calling `TemplatePopulator`. A researcher
can instead populate templates in their own EDSL workflow and pass the finished
job and applicant text to `ExperimentRunner` in a DataFrame. The runner uses
the configured job column and ordered résumé columns and any configured
context. It does not require the original templates or replacement table.
Once supplied to the runner, résumé text is final, including text such as
`{{lot_code}}` that the researcher intends the model to see literally.

Conversely, a researcher can populate with AuditKit and use the returned
DataFrame to construct and run their own EDSL experiment. In that workflow
the researcher controls how EDSL builds prompts and associates answers with
applicants. When using AuditKit's experiment runner, shared inference runs
the experiment through EDSL regardless of who populated the résumés.

### Using both AuditKit stages

Pass the same DataFrame directly to the [experiment runner](experiment_execution.md).
Use the population job text column (`Text` by default) and construct
`resume_columns` in integer slot order from 1 through `N`. Use that list to
label the question's `{resume_i}` fields in the same order. Population's
`{{label}}` syntax applies to the input templates; the experiment question
uses single braces for columns in the populated table.

The supplied `scenario_id` is preserved. With that configuration, an
applicant's `candidate_order == i` determines `resume_i`, the displayed
“Applicant i”, and the matching `pick<i>` and `logprob<i>` result columns.
Experiment execution preserves `candidate_<i>_id`, template provenance, and
source metadata; it does not infer applicant order or validate that the prose
labels in the question match the schema. See the
[worked handoff](../guides/template_population.md#pass-the-populated-table-to-experiment-execution)
for the configuration and expected applicant order.

This slot mapping is verified through EDSL preview, synchronous and
asynchronous execution. See the [native verification results and hosting boundary](../guides/template_population.md#native-edsl-literal-text-and-interview-counts).

Preserving candidate IDs, template provenance, counts, and explicitly supplied
scalar covariates does **not** make the resulting experiment CSV directly
compatible with R preparation. Writer/status/schema mapping, audit partition
validation, production identity integration, and cross-audit alignment remain
in the [holistic integration pass](../integration/regression_analysis.md#later-integration-touchpoints).
Population does not assign audit IDs, create outcomes, or infer demographic,
treatment, quality, or numeric indicators. Only explicitly configured suitable
covariates will enter regression preparation.

### Later cross-subissue consistency review

Revisit these two handoffs together when reviewing issues #12 and #13:

- [ ] Populate two distinguishable applicants in a researcher-owned EDSL
  workflow, then run the finished table through `ExperimentRunner`. Check
  that the configured applicant order and exact résumé text reach the model,
  including a value containing literal braces.
- [ ] Populate the same applicants with `TemplatePopulator`, then use the
  output in a researcher-owned EDSL experiment. Check the prompt seen by the
  model and match each decision back to the supplied candidate ID using the
  researcher's slot order.
