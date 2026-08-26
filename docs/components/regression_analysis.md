# Regression Analysis

[View the regression analysis diagram.](../architecture/regression_analysis.mmd)

## Overview

Regression analysis is one top-level pipeline stage with three independently
invocable R responsibilities:

```text
Raw experiment CSVs
    -> regression-data preparation
    -> regression-ready CSV
    -> fixed-effects estimation
    -> plot-ready regression-results CSV
    -> paper-style rendering
    -> PNG
```

The CSV between preparation and estimation is an intentional inspection
boundary. Researchers clean the experiment output first, inspect it, create any
desired sample slice, and then pass exactly one regression-ready CSV to the
estimator. The estimator does not parse raw experiment output or provide a
sample-filtering language.

This page defines the contracts established in subissue #19. Subissue #20 adds
the locked R environment, preparation configuration validation, deterministic
raw job-row loading, and the initial R test scaffold. Subissue #21 completes
dynamic candidate preparation, selection outcomes, status reporting, and the
preparation CLI. Estimation and rendering remain assigned to later regression
subissues, so not all commands below are available yet.

## Shared Configuration Rules

Preparation, estimation, and rendering each receive their own YAML file.

- A CLI accepts exactly `--config <path>` and rejects positional or unknown
  arguments.
- Relative paths are resolved against the directory containing the YAML file,
  not the caller's working directory.
- Input files are explicit paths. Directory discovery and glob expansion are
  not implicit.
- Unknown YAML keys, duplicate list entries, and empty required strings are
  errors so misspelled options cannot be ignored silently.
- Output parent directories are created when needed. A successful rerun
  atomically replaces its configured artifact; validation or computation
  failure leaves any existing artifact unchanged.

## 1. Regression-Data Preparation

Preparation is the only responsibility that understands raw experiment-output
shape. It combines configured raw CSVs, validates stable identities, reshapes
wide candidate fields into candidate-level rows, and constructs the three
selection outcomes.

### Raw Experiment CSV Contract

Each raw row represents one completed or attempted `ExperimentJobKey`. The
production writer is owned by [experiment execution](experiment_execution.md),
and the preparation consumer requires these columns:

| Column | Type | Contract |
| --- | --- | --- |
| `scenario_id` | string | Stable scenario/job-posting identity. |
| `persona_id` | string | Stable persona identity. |
| `model_config_id` | string | Stable provider/model/parameter identity. |
| `result_status` | string | `completed` for rows eligible for preparation; other terminal or incomplete states are reported and excluded. |
| `candidate_count` | integer | Positive `N` for this scenario. |
| `city` | string | Default top-share ranking field. |
| `year` | integer | Default top-share ranking field. |
| `candidate_<i>_id` | string | Stable candidate/resume identity for index `i`. |
| `candidate_<i>_pick` | integer | Raw binary selection for candidate `i`; required on completed rows and ignored if present on unsuccessful rows. |
| `candidate_<i>_log_probability` | double | Natural-log probability of the emitted binary answer for candidate `i`: `log(P(Yes))` when `pick == 1` and `log(P(No))` when `pick == 0`; unsuccessful rows may be empty. |
| `candidate_<i>_<covariate>` | scalar | Optional structured candidate covariates named in `candidate_covariates`. |

Candidate indices are one-based. Every row must contain the job identities,
`result_status`, `candidate_count`, ranking fields, candidate IDs, and configured
covariates from `1` through `candidate_count`; indexed values above that count
are empty. Completed rows must also contain binary picks, and raw-positive picks
must contain log probabilities. Unsuccessful rows may leave all picks and log
probabilities empty and are excluded before result-value validation. Within one
input file, every required candidate family exposes exactly the same contiguous
header indices from `1` through that file's maximum `candidate_count`;
configured files may have different maximum values of `N` because their
candidate rows are combined after per-file validation and reshaping. Parsing
uses the complete
`candidate_<i>_<field>` pattern, so `N >= 10` does not depend on the last
character of a column name.

The stable long-row identity is:

```text
(scenario_id, persona_id, model_config_id, candidate_id)
```

`candidate_index` is retained for provenance but is never used as durable
identity. Duplicate `ExperimentJobKey` rows across or within configured inputs,
duplicate long-row identities, inconsistent candidate families, or non-contiguous
indices are errors.

Only explicitly configured covariates cross the preparation boundary.
`scenario_covariates` contains literal raw column names and preserves them
unchanged. `candidate_covariates` contains literal suffixes: configured suffix
`black`, for example, reads `candidate_<i>_black` and writes `black`. Both lists
default to empty, preserve their configured order, must be mutually disjoint
and disjoint from the core output columns, and accept names matching
`[A-Za-z][A-Za-z0-9_]*` only. There is no implicit name normalization.

All unconfigured columns are ignored. Covariate names containing the
case-insensitive tokens `prompt`, `response`, `comment`, `job_posting_text`, or
`resume_text` are rejected in this initial interface, which prevents known
payload-text fields from leaking into the clean artifact. Preparation preserves
supplied scalar analysis covariates but does not infer demographic indicators,
treatment assignments, quality measures, or interaction terms from candidate
position.

For every repeated `scenario_id`, `city`, `year`, `candidate_count`, configured
scenario covariates, and the complete candidate-ID set must agree. Configured
candidate covariates must agree for every repeated
`(scenario_id, candidate_id)` pair. Conflicts are errors rather than being
resolved by input order.

The intermediate implementation names `raw_pick` and `raw_log_probability`
are reserved in addition to the published core columns, so configured
covariates cannot overwrite the source values used to construct outcomes.

The pinned paper-reference sample
`.references/job_parsing-code/samples/edsl_raw_results_sample.csv` predates this
stable schema. It uses legacy fields such as `scenario.*`, `agent.*`, `pick1`,
and `logprob1`, assumes four candidate positions, and lacks the modern stable
IDs, result status, candidate count, and candidate IDs. The production loader
therefore rejects it with missing-field diagnostics; it is a private manual
compatibility reference, not a public fixture or a schema authority. Any later
end-to-end smoke-test mapping must be explicit and documented rather than
silently embedded in the production loader.

### `PreparationConfig`

```yaml
input_paths:
  - data/raw/experiment_2010.csv
  - data/raw/experiment_2020.csv
output_path: outputs/regression/regression_ready.csv
top_share: 0.08
probability_threshold: 0.99
ranking_group_variables:
  - city
  - year
scenario_covariates:
  - job_category
candidate_covariates:
  - black
  - high
  - black_high
```

| Field | Required | Validation and meaning |
| --- | --- | --- |
| `input_paths` | yes | Nonempty, ordered list of distinct readable CSV paths. |
| `output_path` | yes | One CSV path distinct from every input path. |
| `top_share` | no | Fraction in `(0, 1]`; default `0.08`. |
| `probability_threshold` | no | Probability in `(0, 1]`; default `0.99`. |
| `ranking_group_variables` | no | Nonempty list of distinct pre-ranking fields: `source_file`, `scenario_id`, `persona_id`, `model_config_id`, `candidate_id`, `candidate_index`, `candidate_count`, `city`, `year`, or configured covariates; default `[city, year]`. |
| `scenario_covariates` | no | Ordered allowlist of distinct scenario-level scalar columns; default `[]`. |
| `candidate_covariates` | no | Ordered allowlist of distinct candidate-field suffixes; default `[]`. |

The #20 functions `load_preparation_config()` and
`load_experiment_results()` validate this configuration, read raw CSV values
as character data, combine job rows in configured file and source-row order,
preserve every result status, attach lexical `source_file` provenance, and
reject duplicate stable job keys. Filtering, candidate-level reshaping,
ranking, derived outcomes, and output writing belong to #21.

The #21 function `prepare_regression_data()` performs those candidate-level
transformations in memory from the configured CSV paths.
`run_regression_preparation()` additionally reports completed and excluded job
counts and atomically writes the configured regression-ready CSV. Neither
function accepts an in-session data frame as a substitute for the canonical
CSV boundary.

Configured inputs are combined deterministically. `source_file` stores the
lexically normalized path string from `input_paths`, using `/` separators and
remaining relative when the configured path is relative. Inputs must expose
compatible candidate families. Rows whose `result_status` is not `completed`
are excluded with a reported count; zero remaining rows is an error.

Every configured scenario field and candidate family header must exist in every
input. Among eligible rows, stable IDs and ranking fields must be nonempty,
`candidate_count` must be a positive integer, candidate picks must be exactly
`0` or `1`, and configured ranking-group values must be complete.

### Selection Outcomes

The preparation output always contains:

- `pick`: the raw `0`/`1` selection;
- `pick_top`: the raw selection capped to the configured top share within each
  ranking group;
- `pick_threshold`: the raw selection subject to the configured probability
  threshold.

For `pick_top`, each unique combination of `ranking_group_variables` is handled
independently:

1. Let `group_size` be the number of all candidate observations in the group,
   including raw non-selections.
2. Set `cutoff = ceiling(top_share * group_size)`.
3. Raw-positive candidates are eligible and are ordered by descending
   `log_probability`.
4. Ties are resolved by ascending `scenario_id`, `persona_id`,
   `model_config_id`, and `candidate_id`.
5. Eligible candidates with rank at most `cutoff` receive `pick_top = 1`;
   every other candidate receives `0`.

This is a cap, not a promise that exactly `cutoff` candidates are selected. If
the group has fewer raw-positive selections, all of them remain selected.

The default deliberately creates one shared cutoff for every `city`-`year`
combination in the configured inputs. It does not add implicit strata for
source file, model, persona, or another experiment dimension. Researchers who
do not want those records to compete must either prepare homogeneous input
slices separately or add the relevant stable columns to
`ranking_group_variables`. The historical script ranked by city while
processing one file at a time, so reproducing that behavior requires retaining
the file's other experiment dimensions as explicit strata.

For `pick_threshold`:

```text
pick_threshold = 1 when
    pick == 1 and log_probability >= log(probability_threshold)
otherwise 0
```

The comparison is inclusive. `probability_threshold` is supplied on the
probability scale while the input score is on the natural-log scale. Every
nonmissing log probability must be finite and at most zero, and every
raw-positive selection must have a nonmissing `log(P(Yes))`. A non-selection's
`log(P(No))` may be missing because it is not used by either derived outcome.
Invalid values are errors. Raw log probabilities are never overwritten with a
sentinel.

### Regression-Ready CSV Contract

The prepared CSV is deterministically ordered by the stable long-row identity.
Its required core columns are:

| Column | Type | Nullability and meaning |
| --- | --- | --- |
| `source_file` | string | Non-null normalized configured-path provenance. |
| `scenario_id` | string | Non-null stable scenario identity. |
| `persona_id` | string | Non-null stable persona identity. |
| `model_config_id` | string | Non-null stable model-configuration identity. |
| `candidate_id` | string | Non-null stable candidate identity. |
| `candidate_index` | integer | Non-null one-based source index; not a durable key. |
| `candidate_count` | integer | Non-null number of candidates attached to the source scenario/job post. |
| `city` | string | Non-null default ranking field. |
| `year` | integer | Non-null default ranking field. |
| `pick` | integer | Non-null binary raw selection. |
| `log_probability` | double | May be missing only for a raw non-selection. |
| `pick_top` | integer | Non-null binary top-share selection. |
| `pick_threshold` | integer | Non-null binary threshold selection. |
| `preparation_top_share` | double | Repeated provenance value from the preparation config. |
| `preparation_probability_threshold` | double | Repeated provenance value from the preparation config. |
| `preparation_ranking_group_variables` | string | Ordered variable names joined with `|`, for example `city|year`. |
| `preparation_scenario_covariates` | string | Ordered configured names joined with `|`; empty when none were requested. |
| `preparation_candidate_covariates` | string | Ordered configured suffixes joined with `|`; empty when none were requested. |

Configured scenario- and candidate-level covariates follow the core columns,
first in `scenario_covariates` order and then in `candidate_covariates` order.
Their scalar values and configured names are preserved exactly.

## 2. Fixed-Effects Estimation

The regression runner accepts exactly one regression-ready CSV per invocation.
Researchers perform any sample selection before invoking it and save that slice
as a separate dataset. The slice must retain every core and preparation
provenance column. Each repeated preparation setting must have exactly one
nonmissing value in the supplied slice; mixing differently prepared data is an
error.

### `RegressionConfig`

```yaml
data_path: outputs/regression/paper_example_ready.csv
dataset_id: paper_example
model_id: black_callback_by_period_model
outcome_variable: pick_top
explanatory_variables:
  - black
control_variables: []
fixed_effects:
  - scenario_id
cluster_variables:
  - scenario_id
estimation_group_variables:
  - period
  - model_config_id
output_directory: outputs/regression/black_callback
```

| Field | Required | Validation and meaning |
| --- | --- | --- |
| `data_path` | yes | Exactly one readable regression-ready CSV. |
| `dataset_id` | yes | Nonempty researcher-defined dataset/slice identifier saved in every result row. |
| `model_id` | yes | Nonempty researcher-defined specification identifier saved in every result row. |
| `outcome_variable` | yes | One numeric column name. Binary outcomes are estimated as linear-probability models. |
| `explanatory_variables` | yes | Nonempty ordered list of distinct numeric or logical column names. |
| `control_variables` | yes | Ordered list of distinct numeric or logical column names; may be empty. |
| `fixed_effects` | yes | Ordered list of distinct columns; may be empty. |
| `cluster_variables` | yes | Ordered list of distinct columns; may be empty for IID standard errors. |
| `estimation_group_variables` | no | Ordered list of distinct columns; default `[]`, which estimates once on the full supplied dataset. An explicit `[]` has the same behavior. |
| `output_directory` | yes | Directory receiving `regression_results.csv`. |

Variable-name fields contain literal CSV column names matching
`[A-Za-z][A-Za-z0-9_]*`, not formula fragments. The outcome cannot also appear
on the right-hand side, and explanatory and control lists cannot overlap. A
fixed-effect variable may also be a clustering variable. Categorical predictors
must be pre-encoded as one or more numeric/logical indicator columns in the
inspected input, and each indicator must be listed explicitly. Indicator
interactions and other transformations must likewise be precomputed. Character
columns are accepted directly only as fixed effects, clusters, or estimation
groups. Arbitrary formula strings are out of scope.

The runner constructs:

```text
outcome ~ explanatory variables + control variables | fixed effects
```

`fixest::feols` supplies the ordinary intercept when no fixed effects are
configured. An empty clustering list uses IID standard errors. One or more
cluster variables use the corresponding one- or multi-way clustered covariance
estimator.

The canonical paper example leaves `control_variables` empty so `black` is the
overall Black--White contrast. A separate quality-heterogeneity specification
may add `high` and `black_high`; in that model, the raw `black` coefficient is
the contrast at the baseline quality level and must be labeled accordingly.

When `estimation_group_variables` is nonempty, the same specification is fit
independently to every observed group combination. Group variables must be
complete, and fits are ordered by the configured variables and their ascending
values. No grouping variables means one fit.

Period collapsing is an inspection-stage data decision, not an implicit
estimator transformation. For the paper smoke test, the inspected dataset adds
`period = 2000` for source years 2000 through 2002 and otherwise uses `year`,
then groups and renders on `period` as shown here. Retaining raw `year` instead
is allowed but defines a different set of models.

The example groups by `period` and `model_config_id`, so it composes with the
fixed-blue renderer below. A separate city-series run adds `city` to
`estimation_group_variables` and sets `series_variable: city`; it does not reuse
the main-panel result file as though the row grain were the same.

Missingness across the outcome, right-hand-side, fixed-effect, and cluster
variables is handled by complete-case estimation. For every fit, the runner
records the input count, complete-case count, missing-data removals, actual
`fixest` observation count, any additional fixed-effect/estimator removals, and
total removals. Empty groups, no complete cases, removal of any requested
explanatory or control term through collinearity, and unidentified
specifications are errors rather than silently changed models.

The count identities are `n_missing_dropped = n_input - n_complete`,
`n_estimator_dropped = n_complete - n_used`, and
`n_dropped = n_input - n_used`.

Coefficient tables, p-values, and confidence intervals use the same configured
covariance estimator. Confidence intervals are obtained from `fixest::confint`
at levels `0.90`, `0.95`, and `0.99`. Inference uses the locked `fixest::ssc()`
defaults: `adj = TRUE`, `fixef.K = "nested"`, `cluster.adj = TRUE`,
`cluster.df = "min"`, `t.df = "min"`, and `fixef.force_exact = FALSE`.
Plotting never recomputes intervals.

### Plot-Ready Results Contract

`regression_results.csv` is tidy and long: one row per model fit, estimable
coefficient, and confidence level. It contains these stable columns:

| Column | Meaning |
| --- | --- |
| `dataset_id`, `model_id` | Researcher-defined data and specification identities. |
| `estimator`, `estimator_version`, `inference_contract_id` | `fixest::feols`, the locked `fixest` package version, and `fixest_feols_ssc_v1`. |
| `outcome_variable`, `term` | Dependent variable and estimated coefficient name. |
| `estimate`, `std_error`, `statistic`, `p_value` | Numerical coefficient statistics from the configured covariance estimator. |
| `n_input`, `n_complete`, `n_used` | Group rows, complete model-variable rows, and observations used by `fixest`. |
| `n_missing_dropped`, `n_estimator_dropped`, `n_dropped` | Missing-data removals, additional estimator/fixed-effect removals, and their sum. |
| `confidence_level`, `conf_low`, `conf_high` | One of `0.90`, `0.95`, or `0.99` and its bounds. |
| `vcov_type` | `iid` or `cluster`. |
| `explanatory_variables`, `control_variables`, `fixed_effects`, `cluster_variables`, `estimation_group_variables` | Ordered names joined with `|`; empty lists are empty strings. |
| `cluster_counts` | Unique estimation-sample cluster counts encoded as `name=count`, joined with `|`; empty for IID. |
| `preparation_top_share`, `preparation_probability_threshold`, `preparation_ranking_group_variables`, `preparation_scenario_covariates`, `preparation_candidate_covariates` | Preparation provenance copied from the inspected input. |

Configured estimation-group columns are appended using their original column
names and scalar group values. Every stable column named in the table above is
reserved; an estimation-group name that collides with one is rejected.
Configuration variable names cannot contain the `|` or `=` metadata separators
under the variable-name rule. Result rows are ordered by group values,
coefficient order, and confidence level. The output contains all information
required for rendering and does not serialize fitted model objects.

## 3. Paper-Style Rendering

Rendering is an independent process that reads one or more compatible saved
result CSVs and produces exactly one configured PNG. It never reads the
regression-ready data and never re-estimates a model.

“Compatible” means selected rows agree exactly on `dataset_id`, `term`, all
serialized model-variable lists, `vcov_type`, `estimator`,
`estimator_version`, `inference_contract_id`, and all preparation-provenance
fields. Only the explicitly mapped outcome, panel/period/series group values,
observation and cluster counts, and numerical estimates may differ. The
researcher-defined `model_id` may differ, but it never waives those substantive
compatibility checks and cannot create duplicate plotting keys. The canonical
renderer rejects heterogeneous specifications; researchers render those as
separately labeled figures instead of placing incomparable estimates in one
grid.

### `RenderConfig`

```yaml
results_paths:
  - outputs/regression/gemini/regression_results.csv
  - outputs/regression/gpt/regression_results.csv
  - outputs/regression/grok/regression_results.csv
  - outputs/regression/llama/regression_results.csv
output_path: outputs/regression/paper_black_coefficient.png
term: black
confidence_level: 0.95
period_variable: period
series_variable: null
panel_variable: model_config_id
outcome_by_panel:
  gemini-1.5-flash: pick_top
  gpt-4o: pick_threshold
  grok-2: pick_threshold
  llama-3.1-405b: pick_threshold
period_order:
  - 1970
  - 1980
  - 1990
  - 2000
  - 2010
  - 2020
series_order: []
panel_order:
  - gemini-1.5-flash
  - gpt-4o
  - grok-2
  - llama-3.1-405b
panel_labels:
  gemini-1.5-flash: "Panel A: Gemini 1.5 Flash"
  gpt-4o: "Panel B: GPT-4o"
  grok-2: "Panel C: Grok-2"
  llama-3.1-405b: "Panel D: Llama 3.1 405B"
x_label: Period
y_label: Black coefficient estimate
y_limits:
  - -0.3
  - 0.3
y_break_interval: 0.1
significance_level: 0.05
panel_columns: 2
width: 12
height: 8
dpi: 300
```

| Field | Required | Validation, meaning, and default |
| --- | --- | --- |
| `results_paths` | yes | Nonempty ordered list of distinct readable result CSVs. |
| `output_path` | yes | PNG path distinct from all result inputs. |
| `term` | yes | One nonempty coefficient name to select. |
| `confidence_level` | no | One of `0.90`, `0.95`, or `0.99`; default `0.95`. |
| `period_variable` | yes | Result column used for the horizontal axis. |
| `series_variable` | no | `null` for fixed-blue panels or a result column for the colored-series variant; default `null`. |
| `panel_variable` | yes | Result column used to divide panels. |
| `outcome_by_panel` | no | Panel-value-to-outcome mapping; default `{}` requires one common selected outcome. A nonempty map must cover every selected panel exactly. |
| `period_order` | no | Complete permutation of selected period values; default `[]` uses ascending observed values. |
| `series_order` | no | Complete permutation of selected series values; default `[]` uses ascending observed values. Must be `[]` when `series_variable` is `null`. |
| `panel_order` | no | Complete permutation of selected panel values; default `[]` uses ascending observed values. |
| `panel_labels` | no | Optional panel-value-to-label map with no unknown keys; source values are the default labels. |
| `x_label`, `y_label` | no | Nonempty axis labels; defaults `Period` and `Coefficient estimate`. |
| `y_limits` | no | Two finite increasing bounds; default `[-0.3, 0.3]`. |
| `y_break_interval` | no | Positive finite spacing; default `0.1`. |
| `significance_level` | no | Value in `[0, 1]`; default `0.05`. |
| `panel_columns` | no | Positive integer; default `2`. |
| `width`, `height` | no | Positive finite inches; defaults `12` and `8`. |
| `dpi` | no | Positive integer PNG resolution; default `300`. |

`outcome_by_panel` makes the paper's mixed-outcome display explicit: its Gemini
panel uses `pick_top`, while its other three panels use the modern
`pick_threshold` name for the historical `pick_99`. When the mapping is empty,
selected rows must contain one common `outcome_variable`; when it is nonempty,
each panel is filtered to its mapped outcome and no additional outcome is
allowed for that panel.

A nonempty order list must contain every distinct selected value exactly once;
unknown, duplicate, or omitted values are errors. Orders never filter data. To
render a subset, the researcher supplies a separately saved, inspected result
CSV rather than relying on an accidental factor-level drop.

The canonical paper-style renderer uses:

- coefficient estimates by period with capped vertical confidence intervals;
- a red dotted horizontal zero line;
- `#1f77b4` blue points of size `3` and intervals with cap width `0.8` and line
  width `0.5` when `series_variable` is null;
- deterministic fixed horizontal dodging, color, and a bottom legend when a
  series variable is present;
- full opacity for `p_value < significance_level` and `0.3` opacity otherwise;
- configured period values as x-axis breaks (decades in the paper config), a
  minimal theme, bold panel titles, and a two-column panel grid by default;
- the configured y limits through coordinate zoom so out-of-range values are
  not removed from the plot data.

The historical script did not record physical output dimensions or DPI. This
project therefore makes `12 x 8` inches at `300` DPI the explicit reproducible
default. Other dimensions are allowed without changing the numerical result
contract.

The renderer validates that the selected term, interval level, outcome, period,
series, and panel fields exist. After term, confidence-level, and outcome
selection, `(panel_variable, period_variable)` must identify each row when
`series_variable` is null; otherwise `(panel_variable, period_variable,
series_variable)` must identify each row. Missing selections, panels absent
from a nonempty outcome mapping, and duplicate plotting keys are errors. The
renderer uses the saved interval bounds and exact p-values; significance
styling is not used as a substitute for the numerical result artifact.

“Paper-style” refers to the historical visual grammar and panel arrangement,
not a promise of numerically identical intervals. The authoritative result
contract uses `fixest::confint` with locked finite-sample settings, whereas the
historical script drew only 95% normal intervals as `estimate +/- 1.96 * SE`.

## Invocation

The three entry points are intentionally separate. The preparation command is
implemented; estimation and rendering commands become available in their
respective subissues.

```bash
Rscript scripts/prepare_regression_data.R --config path/to/preparation.yaml
Rscript scripts/run_regression.R --config path/to/regression.yaml
Rscript scripts/render_regression_plot.R --config path/to/render.yaml
```

Each command exits nonzero with an actionable message on invalid arguments,
configuration, input, or output. Estimation does not invoke rendering
implicitly, which guarantees that a figure can be recreated in a fresh process
from saved results alone.

## R Environment and Test Contract

The R implementation lives alongside, rather than inside, the Python package:

```text
R/regression/       Pure preparation, estimation, extraction, and rendering modules
scripts/            Thin Rscript CLI entry points
tests/r/            testthat unit and end-to-end tests
renv.lock           Authoritative R package environment
```

R 4.4.2 is the initial implementation target and is recorded in the project
lockfile. `renv` manages R packages but does not install R itself or
operating-system libraries. The committed bootstrap uses `renv` 1.2.4, so
later restores do not float with CRAN.

Direct dependencies are intentionally narrow:

| Package | Role |
| --- | --- |
| `yaml` | Load configuration contracts; locked beginning with subissue #20. |
| `fixest` | Estimate fixed-effects models and their inference; added with estimation work. |
| `ggplot2` | Build regression figures; added with rendering work. |
| `patchwork` | Reproduce the paper's panel-specific margins and 2-by-2 assembly; added with rendering work. |
| `testthat` | Run R tests; locked beginning with subissue #20. |

Base R handles CSV I/O and transformation unless implementation demonstrates a
concrete need for another dependency. Runtime commits add a package only when
they first use it and update `renv.lock` in the same commit.

Beginning with subissue #20, the committed root `.Rprofile` sources
`renv/activate.R`; starting `Rscript` from the repository root therefore
bootstraps the recorded `renv` version automatically, with no global package
installation step. A fresh contributor restores and verifies the environment
with:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript -e 'status <- renv::status(); if (!isTRUE(status$synchronized)) quit(status = 1)'
```

The full and focused R test commands are:

```bash
Rscript tests/r/run_tests.R
Rscript -e 'testthat::test_file("tests/r/test-preparation-config.R", reporter = "summary")'
Rscript -e 'testthat::test_file("tests/r/test-preparation.R", reporter = "summary")'
```

Subissue #20 introduces the `renv` scaffold, preparation-config and raw-loader
modules, test runner, and public synthetic fixtures. Dependencies for
estimation and rendering land only when those modules use them. Subissue #21
adds the dependency-free base-R preparation transformation and CLI plus public
multi-city, multi-year, dynamic-`N` fixtures. Existing Python checks continue
to run with `python -m pytest`.

## Artifact Example

```text
outputs/regression/
|-- regression_ready.csv
|-- black_callback/
|   `-- regression_results.csv
`-- paper_black_coefficient.png
```

Generated research outputs are not committed. Automated tests use small public
synthetic fixtures; the private paper samples are reserved for manual smoke
testing.

## Design Principles and Historical Reference

- Preparation, estimation, numerical extraction, and rendering remain separate
  pure responsibilities behind thin R CLIs.
- Raw experiment output, regression-ready data, and plot-ready results cross
  responsibility boundaries as CSV files rather than in-memory Python/R
  objects.
- Stable upstream identities are preserved; local row positions and per-file
  factor codes are not durable keys.
- Model variables, fixed effects, clusters, grouping, paths, and plot semantics
  are configuration-driven rather than hard-coded.
- Numerical results are authoritative; figures are disposable renderings of
  those saved values.

The historical behavior consulted for this contract is pinned at
`KirillUtyashev/job-parsing-code@c9391854ea55806ec252625cd2f48fb9edb156cd`,
primarily `analysis/paper_results_analysis.R` and the two files documented in
`samples/README.md`. The new contract deliberately replaces its hard-coded
four-candidate pivots, positional treatment construction, local paths,
per-file factor identifiers, overwritten log probabilities, implicit
input-order ties, in-memory-only results, and unrecorded plot dimensions.

The outcome contract also deliberately omits the historical global `pick_40`,
renames `pick_99` to configurable `pick_threshold`, and treats a missing
positive-answer probability as invalid instead of propagating `NA`. Historical
file boundaries and the 2000--2002 period collapse become explicit data/strata
choices. Finally, modern intervals come from `fixest::confint`, colored series
use deterministic fixed dodging rather than confidence-interval-dependent
offsets, and y limits use coordinate zoom rather than dropping out-of-range
rows. These choices preserve the requested paper-style appearance while making
the numerical and data contracts reproducible and inspectable.
