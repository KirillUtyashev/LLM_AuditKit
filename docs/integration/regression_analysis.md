# Regression Analysis Integration Handoff

This handoff records what regression-analysis subissue #24 verified and what
must be rechecked when experiment execution (#13) and repository CI (#5) are
implemented. The detailed, authoritative schemas remain in the
[regression-analysis component contract](../components/regression_analysis.md).

## Verified Public Workflow

The public example contains two synthetic audits. Each audit has two city
shards, one persona, one model configuration, 16 job-post scenarios, 64
candidate rows, and four city-year estimation groups. The audits use the same
regression specification and are rendered as two explicit audit panels.

From the repository root, after restoring the locked R environment, run:

```bash
Rscript scripts/prepare_regression_data.R --config examples/regression/end_to_end/prepare_audit_a.yaml
Rscript scripts/prepare_regression_data.R --config examples/regression/end_to_end/prepare_audit_b.yaml

# Inspect the two regression-ready CSVs before estimation.

Rscript scripts/run_regression.R --config examples/regression/end_to_end/regress_audit_a.yaml
Rscript scripts/run_regression.R --config examples/regression/end_to_end/regress_audit_b.yaml
Rscript scripts/render_regression_plot.R --config examples/regression/end_to_end/render_audits.yaml
```

The commands use only the three independently invocable public R entry points.
They create:

| Artifact | Expected result |
| --- | --- |
| `outputs/regression/end_to_end/audit_a/regression_ready.csv` | 64 candidate rows; `pick`, `pick_top`, and `pick_threshold` sums of 39, 8, and 23. |
| `outputs/regression/end_to_end/audit_b/regression_ready.csv` | 64 candidate rows; `pick`, `pick_top`, and `pick_threshold` sums of 53, 8, and 38. |
| Each audit's `regression_results.csv` | 24 tidy rows: four grouped fits, two requested terms, and three confidence levels. |
| `outputs/regression/end_to_end/multi_audit_black_coefficients.png` | Eight selected `black` coefficients in two audit panels; 1200 by 600 pixels. |

The `outputs/` tree is ignored by Git; these generated example artifacts are
not repository fixtures.

The checked-in test `tests/r/test-regression-end-to-end.R` copies this public
example into a temporary directory, invokes the same entry points, checks the
inspection boundary and schemas, reruns the workflow to verify deterministic
CSV output, and validates the combined PNG. It never requires private data,
model credentials, or live inference.

## Boundary Contracts

### Experiment output

One raw CSV row represents one experiment job. The preparation boundary
requires `scenario_id`, `persona_id`, `model_config_id`, `result_status`,
`candidate_count`, `city`, and `year`, followed by contiguous dynamic candidate
families `candidate_<i>_id`, `candidate_<i>_pick`, and
`candidate_<i>_log_probability`. Only explicitly configured scalar scenario
and candidate covariates cross the boundary.

Scenario and candidate IDs are durable identities, not row or candidate
positions. A preparation config covers exactly one model configuration, one
persona, and one distinguishable run or batch. The researcher assigns its
`audit_id`; preparation never derives that ID from a path or model label.
Multiple city/year files may be shards of the same audit, but separate audits
use separate preparation calls.

`result_status: completed` marks rows eligible for preparation. For a completed
candidate, `pick` is binary and `log_probability` is the natural-log
probability of the emitted binary answer: `log(P(Yes))` for a positive pick and
`log(P(No))` for a negative pick. A positive pick must have a probability.

### Preparation assumptions

With the defaults, `pick_top` ranks within each city-year group. Its denominator
is every candidate in the group, including raw non-selections; the cutoff is
`ceiling(0.08 * group_size)`, and only raw-positive candidates compete, ordered
by descending log probability with stable-identity tie breaking.
`pick_threshold` is one only when `pick == 1` and
`log_probability >= log(0.99)`. Both values are configurable and are repeated
in the output as provenance.

The regression-ready CSV has one row per candidate. It retains source-file and
audit provenance; the stable scenario, persona, model-configuration, and
candidate identities; candidate count and source index; city and year; the
three outcomes; preparation settings; and configured scalar covariates. See
the [complete prepared-data schema](../components/regression_analysis.md#regression-ready-csv-contract).

### Regression results

The estimator accepts exactly one inspected regression-ready CSV per call. Its
tidy output has one row per fit, coefficient, and confidence level. It retains
`(audit_id, dataset_id, model_id)` source provenance; estimator and inference
metadata; the outcome and term; coefficient statistics and observation counts;
90%, 95%, and 99% intervals; covariance and formula metadata; preparation
provenance; and the configured estimation-group columns. See the
[complete result schema](../components/regression_analysis.md#plot-ready-results-contract).

Multi-audit rendering may vary the outcome only through an explicit
outcome-by-panel map. The explanatory variables, controls, fixed effects,
clusters, covariance type, estimation grouping, inference contract, and
preparation settings must otherwise match globally.

## Environment and Checks

R 4.4.2 is the recorded target. `renv.lock` pins `renv` 1.2.4, `yaml` 2.3.12,
`fixest` 0.14.2, `ggplot2` 4.0.3, `patchwork` 1.3.2, and the remaining
transitive/test dependencies. From the repository root, the relevant checks
are:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript -e 'status <- renv::status(); if (!isTRUE(status$synchronized)) quit(status = 1)'
Rscript -e 'testthat::test_file("tests/r/test-regression-end-to-end.R", reporter = "summary")'
Rscript tests/r/run_tests.R

python -m pip install -e ".[test]"
python -m pytest

git diff --check
git diff --cached --check
```

## Private Reference Smoke Test

On 2026-09-01, the pinned private sample at
`KirillUtyashev/job-parsing-code@c9391854ea55806ec252625cd2f48fb9edb156cd`
was exercised manually. The run used R 4.4.2 on
`aarch64-apple-darwin20` with the locked `yaml` 2.3.12, `fixest` 0.14.2,
`ggplot2` 4.0.3, and `patchwork` 1.3.2. Both repository worktrees were clean.

Direct loading failed safely before any mapping: the legacy raw sample lacks
the modern envelope and dynamic candidate-family fields, while the historical
regression-ready sample lacks the current audit and preparation provenance.
The two samples also come from different source experiments, so neither is an
expected output oracle for the other.

A compatibility adapter and every generated artifact lived in one disposable,
untracked temporary directory. In the commands below, `SMOKE_DIR` denotes that
run-specific directory; it is not a supported repository path or interface.

```bash
Rscript --vanilla scripts/prepare_regression_data.R --config "${SMOKE_DIR}/preparation.yaml"
Rscript --vanilla scripts/run_regression.R --config "${SMOKE_DIR}/regression.yaml"
Rscript --vanilla scripts/render_regression_plot.R --config "${SMOKE_DIR}/render.yaml"
```

The compatibility mapping used `scenario.city`, `scenario.year`, and
`scenario.category` for city, year, and job category; mapped the four legacy
`pick<i>` and `logprob<i>` fields to modern candidate families; and derived
the historical `black`, `female`, and slot-based `high` indicators. Content
from each scenario and candidate was hashed into temporary MD5 pseudonyms.
Those hashes are compatibility keys, not canonical durable IDs and not a
recommended anonymization method. The adapter supplied sample-only constant
persona `historian_first_person_hr_manager`, model configuration
`gpt-4o-2024-08-06_temperature-0`, and noncanonical audit label
`paper_sample_openai_08_first_equal_2010_smoke`. It marked rows complete only
after completeness checks. Those labels and the true run or batch identity
still require upstream and researcher confirmation. Raw prompts, job text,
resumes, and comments did not cross into the prepared CSV.

Preparation used the 0.08 top share, 0.99 probability threshold, city-year
ranking, scenario covariates `position_fe` and `job_category`, and candidate
covariates `black`, `female`, and `high`. Estimation fit
`pick_threshold ~ black | position_fe`, clustered on `position_fe`, separately
by city and year. Rendering selected the `black` term and saved 95% intervals.

The five legacy rows produced a 20-row, 24-column prepared table. Preparation
selected 2 `pick_top` and 3 `pick_threshold` observations and matched the
historical outcome calculations on all 20 sampled candidates. The threshold
regression produced two city-year grouped fits and a 6-row, 35-column tidy
interval table; rendering selected two coefficients into a one-panel, 900 by
600 pixel PNG. No private input, compatibility output, regression result, or
PNG was copied into or committed to LLM AuditKit.

This run validates mechanical compatibility across preparation, grouped
`fixest` estimation, tidy export, and rendering on the sampled rows. It does
not validate substantive estimates, canonical identities, log-probability
semantics, multi-year behavior, or multi-audit integration. In particular, the
legacy parser retained `top_logprobs[[1]]` for each emitted Yes/No token and
discarded the raw response, so the current emitted-answer probability contract
cannot be proven from this sample. Its raw and historical
regression-ready samples also come from different source experiments and
cannot be compared row by row. The sample contains one audit, one year, two
cities, five jobs, all-positive raw picks, and only two or three clusters per
fit; its estimates are not research evidence.

## Later Integration Touchpoints

### Experiment execution (#13)

The public workflow verifies the downstream consumer, not the unfinished
production writer. Issue #13 must:

- emit the exact envelope, status, dynamic candidate-family, ranking, and
  emitted-answer probability semantics described above;
- preserve durable scenario and candidate IDs and detect duplicate job keys
  across shards;
- either emit audit-partitioned CSVs or provide an explicit validated adapter
  for aggregate multi-persona/model output;
- preserve a distinguishable run/batch identity or partition guarantee, which
  is not currently part of `ExperimentJobKey`;
- prove that shared scenarios and candidate assignments align across audits;
  and
- rerun the public boundary tests with finalized writer output.

The temporary private-sample adapter is not the production adapter decision.
`audit_id` remains researcher-assigned and must not be inferred by #13 or by
preparation.

### Repository CI (#5)

CI should provision R 4.4.2, restore and verify `renv.lock`, run the complete R
suite (including the public end-to-end test), install Python test dependencies,
and run `python -m pytest`. It must not sync the private reference repository,
require SSH credentials, or make live model calls. The runner also needs a
headless PNG-capable R installation.

No formatter, linter, type checker, or Python build command is configured yet;
#5 owns those choices and must document the commands it introduces. An `renv`
cache may accelerate CI but cannot replace restoration and synchronization
checks.

## Remaining Limitations

- Production experiment-output compatibility remains unverified until #13 is
  implemented.
- No global registry prevents reuse of one `audit_id` for different
  persona/model/run combinations.
- The current raw schema cannot itself prove run/batch identity.
- Researchers still inspect and save analysis slices outside the estimator;
  there is no sample-filtering language.
- PNG dimensions and numerical plot data are reproducible, but fonts,
  antialiasing, and file bytes may vary by operating system.
- The private smoke test is deliberately narrow and must never be expanded by
  duplicating its rows under invented audit identities.
