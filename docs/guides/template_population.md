# Template Population: Worked Contract Example

This is a synthetic example of the
[population contract](../components/template_population.md). The step-two
[unit tests](../../tests/templates/population/test_populator.py) check its exact
output through the implemented DataFrame API. All names, institutions, jobs, and assignments
below are invented. Both tables are supplied by the researcher; population
neither chooses their values nor derives one table from the other.

## Configuration and Both Inputs

The `TemplatePopulationConfig` fields are:

```python
job_posting_column = "Text"
template_columns = {"application": "template_1", "resume": "template_2"}
placeholder_columns = {
    "name": "full_name",
    "school": "school",
    "start_month": "start_month",
    "end_month": "end_month",
    "credential": "credential",
    "skill": "skill",
}
```

There are two templates/applicants per scenario, so `N = 2`. The map uses
explicit template IDs; `candidate_order` in the second table defines resume
order. `job_id` is retained scenario metadata. Column order is exactly the
left-to-right order shown in each table.

Prepared templates (`templates`):

| scenario_id | job_id | Text | template_1 | template_2 |
| --- | --- | --- | --- | --- |
| clerk-set-a | job-clerk | Hire a records clerk. | Application: {{name}}. Education: {{school}}. Signed: {{name}}. | Resume: {{name}}. Experience: {{start_month}} to {{end_month}}. |
| assistant-set-a | job-assistant | Hire a laboratory assistant. | Application: {{name}}. Training: {{school}} ({{credential}}). Signed: {{name}}. | Resume: {{name}}. Skills: {{skill}}. |

Replacement values (`replacements`):

| scenario_id | template_id | candidate_id | candidate_order | full_name | school | start_month | end_month | credential | skill | quality_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clerk-set-a | application | applicant-cedar | 2 | Alex Rowan | Example College | ∅ | ∅ | ∅ | ∅ | 7 |
| assistant-set-a | resume | applicant-elm | 2 | Jamie Vale | ∅ | ∅ | ∅ | ∅ | Printing {{lot_code}} labels | 6 |
| clerk-set-a | resume | applicant-birch | 1 | Casey Brook | ∅ | May 2021 | June 2024 | ∅ | ∅ | 8 |
| assistant-set-a | application | applicant-ash | 1 | Morgan Reed | Sample Institute | ∅ | ∅ | Laboratory certificate | ∅ | 9 |

`∅` denotes a missing scalar (`None` here), not a literal string. All other
cells are strings except `candidate_order` and `quality_score`, which are
integers. The intentionally interleaved rows show that table position does
not match applicants to templates. `quality_score` is an opaque,
researcher-supplied numeric covariate; it is not calculated or inserted.
The dates are supplied strings, with no arithmetic or period recipe.
Jamie's skill contains the literal text `{{lot_code}}`. No mapping for
`lot_code` is required: it is part of a replacement value, not a source template.

For `clerk-set-a`, `application` needs only `name` and `school`; its other
mapped cells may be missing. Its repeated `name` uses one value twice. The
same template ID in `assistant-set-a` additionally requires `credential`.
The two `resume` texts have different label sets as well.

## Exact Expected Output

The following three column panels describe **one two-row DataFrame**. The
panels share row positions (first `clerk-set-a`, then `assistant-set-a`);
they are not separate outputs. Concatenate their columns left to right.
All text shown is a single-line string. `∅` again means a missing scalar;
counts and scores remain integers. There are no other columns. The output
index is `RangeIndex(0, 2)`.

Retained source columns, followed by `candidate_count`:

| scenario_id | job_id | Text | template_1 | template_2 | candidate_count |
| --- | --- | --- | --- | --- | --- |
| clerk-set-a | job-clerk | Hire a records clerk. | Application: {{name}}. Education: {{school}}. Signed: {{name}}. | Resume: {{name}}. Experience: {{start_month}} to {{end_month}}. | 2 |
| assistant-set-a | job-assistant | Hire a laboratory assistant. | Application: {{name}}. Training: {{school}} ({{credential}}). Signed: {{name}}. | Resume: {{name}}. Skills: {{skill}}. | 2 |

Slot 1 columns, in order:

| resume_1 | candidate_1_id | candidate_1_template_id | candidate_1_template_column | candidate_1_full_name | candidate_1_school | candidate_1_start_month | candidate_1_end_month | candidate_1_credential | candidate_1_skill | candidate_1_quality_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Resume: Casey Brook. Experience: May 2021 to June 2024. | applicant-birch | resume | template_2 | Casey Brook | ∅ | May 2021 | June 2024 | ∅ | ∅ | 8 |
| Application: Morgan Reed. Training: Sample Institute (Laboratory certificate). Signed: Morgan Reed. | applicant-ash | application | template_1 | Morgan Reed | Sample Institute | ∅ | ∅ | Laboratory certificate | ∅ | 9 |

Slot 2 columns, in order:

| resume_2 | candidate_2_id | candidate_2_template_id | candidate_2_template_column | candidate_2_full_name | candidate_2_school | candidate_2_start_month | candidate_2_end_month | candidate_2_credential | candidate_2_skill | candidate_2_quality_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Application: Alex Rowan. Education: Example College. Signed: Alex Rowan. | applicant-cedar | application | template_1 | Alex Rowan | Example College | ∅ | ∅ | ∅ | ∅ | 7 |
| Resume: Jamie Vale. Skills: Printing {{lot_code}} labels. | applicant-elm | resume | template_2 | Jamie Vale | ∅ | ∅ | ∅ | ∅ | Printing {{lot_code}} labels | 6 |

## Pass the Populated Table to Experiment Execution

Pass the returned DataFrame directly to `ExperimentRunner.preview` or
`ExperimentRunner.run`. Keep its `scenario_id` and source columns. The
example's job text is in `Text`; no CSV round trip, renaming, or reshaping is
needed for the Python runner.

With the package installed, run this example from the repository root:

```bash
python examples/template_population/preview.py
```

The [preview script](../../examples/template_population/preview.py) reads the
editable [template table](../../examples/template_population/templates.csv)
and [replacement table](../../examples/template_population/replacements.csv)
using the shared local file source. The template table goes through the dataset
loader. The replacement table has several rows per scenario, so population
validates its composite keys. The example prints the slot-to-candidate mapping and the actual
EDSL-rendered questions for both jobs. The example puts both job requests in
one batch, with both applicants in each question. It stops at preview: no model
call, interview decision, or saved result is needed.

Build the experiment schema **and** question from the same list of resume
columns. Population fills `resume_i` from the applicant with
`candidate_order == i`. Experiment execution uses its configured column
order for answer slots and uses the question text you supply to present the
resumes. A question that labels the wrong field “Applicant 1” can still
reference every required column, so inspect the rendered preview.

```python
from llm_auditkit.experiments import ExperimentDatasetSchema

# population_config is the config used to produce the populated DataFrame.
resume_columns = [
    f"resume_{i}" for i in range(1, len(population_config.template_columns) + 1)
]
dataset_schema = ExperimentDatasetSchema(
    job_posting_column=population_config.job_posting_column,
    resume_columns=resume_columns,
)
applicant_lines = [
    f"Applicant {i}: {{{column}}}" for i, column in enumerate(resume_columns, 1)
]
prompt_template = "\n\n".join(
    ["Job: {job_posting}", *applicant_lines, "Which applicants would you interview?"]
)
```

Use `dataset_schema` and `prompt_template` in the experiment configuration.
For the two jobs above, the resulting order is:

| Scenario | Applicant 1 | Applicant 2 |
| --- | --- | --- |
| `clerk-set-a` | Casey Brook (`applicant-birch`, from `template_2`) | Alex Rowan (`applicant-cedar`, from `template_1`) |
| `assistant-set-a` | Morgan Reed (`applicant-ash`, from `template_1`) | Jamie Vale (`applicant-elm`, from `template_2`) |

Read each decision in that same slot: for `clerk-set-a`, `pick1` and
`logprob1` describe Casey, and `pick2` and `logprob2` describe Alex.
`candidate_1_id` and `candidate_2_id` identify them in the experiment
result and its saved checkpoint.

The [offline handoff test](../../tests/integration/test_population_to_experiment.py)
passes the unchanged population result to the real runner for two other
synthetic jobs. It checks both submitted questions against expected text,
supplies distinct synthetic decisions and token log probabilities, and
returns inference results in reverse order. It checks the decisions by
scenario and candidate ID in memory, in the CSV checkpoint, and after a
fresh runner resumes from that checkpoint without another inference call.
Only the inference adapter is simulated in that test. Other cases in the
same module pass two populated jobs in one batch to EDSL’s native synchronous
and asynchronous runners. The test model receives the exact text of both
questions, including applicant data containing `{{ 2+2 }}`, an embedded NUL,
and mixed line endings. The same prompt text survives checkpoint reload. The real
experiment parser associates all four synthetic decisions and token log
probabilities with the expected candidate IDs.

### Native EDSL: literal text and interview counts

Two boundaries matter for audit reproducibility:

- **Text in a resume stays text.** A supplied `{{ 2+2 }}` reaches the
  model, preview, and recorded question exactly as written. AuditKit protects
  the supplied text while EDSL renders its answer instructions and restores
  it before caching and sending the prompt to the provider.
- **Each request schedules one interview.** Requests with the same model
  configuration and response format can run concurrently in one EDSL job,
  even with different personas and instructions. EDSL's `zip_assign()` pairs
  each request's agent with its scenario. EDSL schedules interviews, caches
  responses, and manages retries.

AuditKit runs each EDSL job locally so it can restore literal text. The model
provider can run remotely. This applies to all shared-inference jobs. See the
[inference contract](../components/inference.md) for supported EDSL versions.

To reproduce the [native execution checks](../../tests/inference/test_edsl_literal_transport.py)
and [experiment handoff](../../tests/integration/test_population_to_experiment.py)
offline, run:

```bash
python -m pytest tests/integration/test_population_to_experiment.py \
    tests/inference/test_edsl_literal_transport.py
```

These tests use a local test model. They do not claim a live-provider
result, successful whole-job offload, or compatibility with R preparation.

## Acceptance Cases

These cases specify the contract. The tests cover core filling and validation,
[reference structures](#reference-structure-verification), and
[custom labels and applicant counts](#custom-labels-and-applicant-counts).
The [development checklist](../components/template_population.md#local-development-checklist)
tracks the experiment-input check and final contract review.
Unless stated otherwise, each change is applied independently to the valid example.

| Case | Expected result |
| --- | --- |
| Unchanged inputs; repeated calls | Exactly the two rows and all fields above; both inputs/config unchanged. |
| Reorder replacements or change either DataFrame's index labels | Same output values, column order, and `RangeIndex`. |
| Reverse templates row order | Same scenario records, reversed output row order; IDs unchanged. |
| Swap orders 1 and 2 within one scenario and supply a new `scenario_id` in both inputs | Swap that scenario's whole resume/identity/payload bundles; candidate/template IDs are preserved. The new scenario ID distinguishes the changed set for checkpoints. |
| Use 10 configured templates with explicit IDs and complete values | Exactly 10 applicants; integer `candidate_order` controls slots, never lexical sorting of `template_10` before `template_2`. |
| Use templates with 3, 6, or 10 distinct user-defined labels | Same coverage rules, independent of the number/names of labels. |
| Add a new label `{{candidate_id}}`, explicitly mapped to a payload column `display_id` | Insert `display_id`; never implicitly use the structural `candidate_id` key. Mapping to the structural key is an error. |
| Leave `credential` missing for `clerk-set-a` / `application` | Valid: this template does not use that label. |
| Set `credential` missing for `assistant-set-a` / `application` | Error: its matched template requires that value. |
| Remove the `school` mapping, even if another unused mapping keeps the count equal | Error: label-name coverage is incomplete. |
| Add an unused mapping targeting an existing payload column | Valid; no additional required cell values until a template uses that label. |
| Add a mapping targeting an absent column | Error, even if its label is unused. |
| Replace a required text value with integer `2024`, boolean `False`, `""`, or missing | Error; exact nonblank insertion strings are required. `"2024"` is valid text. |
| Replace a required value with `"Writes {{notes}} and {examples}"` | Insert it verbatim; do not substitute or reject its braces. |
| Change a template to `Literal \{{name\}}; person {{name}}.` and supply name `Alex Rowan` | Exactly `Literal {{name}}; person Alex Rowan.` |
| Use source `{{ name }}`, `{{}}`, `{{name`, `name}}`, or `{{{name}}}` | Malformed-placeholder error before returning output. |
| Use source `{name}` or a fixed template with no placeholders | Literal text; still requires its one matched applicant row. |
| Duplicate a templates `scenario_id` or a replacement `(scenario_id, template_id)` | Ambiguous-match error; no first/last-row choice. |
| Duplicate `candidate_id` within a scenario | Error, even if templates/orders differ. Same ID in another scenario is permitted. |
| Delete/add a replacement row or reference an unknown scenario/template | Completeness or unmatched-record error; no partial result or silent drop. |
| Use orders `0, 1`, `1, 1`, `1, 3`, `"1", "2"`, or `True, 2` for `N = 2` | Error: order must be exactly integer `1, 2`. |
| Supply either input with zero rows, duplicate columns, or nonstring column names | Input-schema error. |
| Add source `resume_1` or `candidate_count`, or payload `id` or `template_column` | Output-column collision error; no automatic overwrite/rename. |
| Add scenario metadata `comment` or `pick1` | Experiment-reserved column error. Payload `comment` is valid under its candidate prefix. |
| Add optional scalar metadata, including missing values or integer covariates | Preserve values under the documented source/candidate names without insertion or inference. |
| Add a list/dictionary, nonmissing datetime object, or infinity as metadata | Unsupported-scalar error; callers prepare scalar text/numeric data explicitly. |

## Reference Structure Verification

Step three uses the public
[synthetic fixture](../../tests/fixtures/template_population/reference_structures.yaml)
and [offline tests](../../tests/templates/population/test_reference_structures.py).
Five parameterized cases compare exact multiline output against independently
hand-authored expected resumes. They check unchanged prose, punctuation and
newlines, original templates, scalar metadata, candidate identity, and template
provenance. Replacement values are explicit fixture data, not renderer output.

The private reference was verified clean and read-only on 2026-11-03 at
`KirillUtyashev/job-parsing-code@c9391854ea55806ec252625cd2f48fb9edb156cd`.
The following source locations identify structural evidence, not copied prompt
bodies or historical data. All paths are relative to that reference repository.

| Synthetic family | Reference location | Verified structure |
| --- | --- | --- |
| `application_1950_1960` | `jobs_to_experiment/prompts.py:40–71` | School and employment fields; supplied name reused in applicant and signature lines; supplied signature date. |
| `school_employment_1970_1980` | `jobs_to_experiment/prompts.py:143–166` and `230–253` | School, graduation, one employment range, duties, and skills. |
| `university_one_job_1990` | `jobs_to_experiment/prompts.py:316–342` | University attendance and one job; the supplied graduation year is reused in the job-start field. |
| `university_student_job_2000_2002` | `jobs_to_experiment/prompts.py:391–421` | University, a post-school work period, and an in-school work period. |
| `university_two_jobs_internship_2010_2020` | `jobs_to_experiment/prompts.py:470–509` | University, two post-school work periods, and an invented internship representing in-school work. |

`jobs_to_experiment/resume_creation.py:38–67` illustrates wide template columns
alongside job metadata; lines 87–98 establish the grouped year routing. The
1970 and 1980 prompts have the same section structure with different prose-style
instructions; each other grouped family shares one prompt. The modern reference
calls its student section **In-School Work Experience**; the fixture's internship
is a synthetic specialization, not a claim about the original applicants.
Historical declared placeholder lists are inconsistent (for example,
`prompts.py:139` and `311`); coverage follows the fields actually used in each
adapted template. Historical `experiment_setup.py` is only format context, not
an implementation target. See the [reference guide](../paper_reference.md).

One additional test assembles a mixed-form cohort with two explicit job rows
and three explicitly assigned applicants per job. It verifies all six expected
resumes and every identity/payload bundle after interleaving replacement rows
and using duplicate DataFrame index labels. The same stable applicant is
intentionally reused across jobs, and template-to-slot order differs between
jobs. This is a mechanical alignment test, not a proposed historical experiment.
No Cartesian product or scenario expansion constructs the assignments.

Two negative cases remove a required application signature date or internship
start date. Each must fail with scenario/template/candidate and label context;
that same missing field remains valid in a different family that does not use
it. The other family cases also leave unrelated mapped fields missing. These
checks demonstrate template-specific coverage without reproducing the whole
step-two validation matrix.

Run these checks without the private checkout, credentials, or model access:

```bash
python -m pytest tests/templates/population/test_reference_structures.py
```

All eight cases passed on 2026-11-03. The
[development checklist](../components/template_population.md#local-development-checklist)
records the fresh baseline and final full-suite results. No population runtime
change was needed for these examples.

## Custom Labels and Applicant Counts

The two counts are independent. The template-column mapping sets the number
of applicants for every scenario in one call. Each source template can use
its own set of placeholder labels. A repeated label reuses the same value
without adding an applicant or requiring another replacement column.

The [custom-label tests](../../tests/templates/population/test_custom_placeholder_sets.py)
keep two applicants per scenario while varying a form from 3 to 6 to 10
distinct labels. For example, `{{Bay}}` reads `work_area`, `{{bay}}` reads
`bench_code`, and `{{_tool2}}` reads `instrument`. Four explicitly expected
resumes per case verify case-sensitive matching, repeated labels, and
different required fields across templates and scenarios.

The [applicant-count tests](../../tests/templates/population/test_applicant_counts.py)
keep one label, `{{entry}}`, and run with 1, 5, 10, or 11 applicants per
scenario. Two scenarios share a job ID but have different metadata and
assignments. Even with shuffled replacement rows, output slots follow
integer `candidate_order`: slots 10 and 11 appear after slot 9. Each
resume stays with its candidate ID, original template, and supplied values.

Run these seven offline cases with:

```bash
python -m pytest tests/templates/population/test_custom_placeholder_sets.py \
    tests/templates/population/test_applicant_counts.py
```

## Reference Limits

The sanitized reference lacks the original generated template datasets and
year-specific name tables. No private data or historical name/address pools
are reproduced here. Historical bare `name`, `year`, and `month` tokens and
their broad substring replacement are adapted to the new explicit syntax;
there is no legacy parser, token repair, or period-specific population recipe.
The examples establish literal text and data alignment only. They do not
reproduce historical experiments or assess chronology, demographic assignments,
quality choices, or substantive research validity.

Candidate metadata preservation is useful for the future production boundary,
but the existing experiment CSV still needs the explicitly deferred
[writer-to-R integration](../integration/regression_analysis.md#later-integration-touchpoints).
