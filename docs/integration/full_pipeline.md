# Full-Pipeline Verification

Issue #17's cross-stage test is
[`tests/integration/test_full_pipeline.py`](../../tests/integration/test_full_pipeline.py).
CI setup is outside this verification task.

## Run locally

Install the test and optional OCR dependencies, including system Poppler as
described in the [OCR guide](../guides/newspaper_ocr.md). The Python test runs
with the normal suite; it skips when optional OCR dependencies are absent:

```bash
python -m pip install -e ".[ocr,test]"
python -m pytest tests/integration/test_full_pipeline.py
```

To include the real R preparation, estimation, and rendering entry points,
first restore the locked R environment, then opt in explicitly:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
LLM_AUDITKIT_RUN_R_INTEGRATION=1 python -m pytest tests/integration/test_full_pipeline.py
```

This test never calls live Vision or model services. It uses a real synthetic
PDF, Poppler rendering, real Vision SDK response parsing, and native EDSL
execution/cache behavior. Only the OCR RPC and model-response transport are
scripted; the test forbids socket connections in Python. R runs with the
restored local packages.

## Coverage and expected outcomes

Both synchronous and asynchronous execution traverse OCR, dataset loading,
template generation, template population, and experiment execution. Each uses
the same 16-page synthetic newspaper, three configurable templates/candidates
per posting, and logical inference batches of five. Resume checks prove that
completed OCR/template work is reused and that experiment execution resumes
from an interruption after its first persisted batch without spending more
model calls on completed jobs. The two modes produce identical experiment
tables.

The optional R check invokes the three public YAML-configured scripts. It
checks 48 candidate observations, stable candidate identities, preserved
researcher-defined numeric predictors and emitted-answer log probabilities,
and outcome sums of 20 (`pick`), 12 (`pick_top`), and 14 (`pick_threshold`).
The inspected fixture yields a treatment coefficient of 0.5 with 48 used
observations. Rendering produces a 600-by-400 PNG with explicitly configured
y limits that include the coefficient and selected interval.

The synthetic assertions stand in for the researcher's inspection between
preparation and estimation. They do not remove that gate for real data.
Generated inputs, checkpoints, YAML files, regression tables, and images stay
in pytest temporary directories; no private data or outputs are committed.

## Production handoffs and explicit researcher choices

OCR exports `ocr_request_id` and `ocr_model_config_id`, avoiding experiment
writer column collisions at the source. Those provenance fields pass through
the pipeline unchanged. City/year keys are still explicitly unpacked from
source metadata because OCR does not impose a historical dataset schema.

R preparation receives the unchanged native experiment CSV with
`input_format: auditkit`. Its production loader normalizes pick/logprob/error
fields to the canonical contract, rejects mixed schemas/scopes, and leaves
candidate IDs, covariates and emitted-answer probabilities unchanged. The
test supplies a researcher-assigned `audit_id`; it does not infer demographic
indicators, candidate identities or distinct execution runs. See the
[regression integration handoff](regression_analysis.md).

There is no fixture-only schema translation between these stages. This test
uses the public Python APIs plus the R YAML entry points. The repository's
[phase runner](../guides/pipeline.md) offers the same composition through a
master YAML. `tests/test_pipeline_runner.py` separately exercises its real
Python stages, configuration wiring, inspection stops, error handling and
resume, with mocked inference. Its opt-in R test drives the runner through
preparation, estimation and PNG rendering with a numerical oracle.

The runner also supports an explicit continuous `--run` through R preparation,
without intermediate review pauses. Its offline tests cover optional OCR
dispatch, configured pool sampling, in-memory template/population handoffs,
sync/async experiments, saved-assignment compatibility, interrupted writes,
and checkpoint resume. A separate opt-in test feeds its sampled candidates
through real R preparation, checks all 32 candidate identities and the supplied
audit ID, and proves that estimation/rendering are not invoked. To include
those checks:

```bash
LLM_AUDITKIT_RUN_R_INTEGRATION=1 python -m pytest tests/test_pipeline_runner.py tests/test_sample_candidates.py
```

The small independent pools are a mechanics example, not the paper's sampling
design. The reference sampling context is revision
`c9391854ea55806ec252625cd2f48fb9edb156cd`,
`jobs_to_experiment/experiment_setup.py`. No private pools or legacy data are
copied into this implementation.

## Verification record and real-data follow-up

On 2026-11-15, both offline modes and the optional R path passed locally. The
full Python suite with R integration enabled passed (835 tests; five live
tests skipped), and the complete R suite passed. Locked R packages were
restored, but the local R executable was
4.5.0 rather than the recorded 4.4.2 target; `renv::status()` still reports that
runtime mismatch. This is not verification of the exact locked R runtime.

The initial stored-key checks returned `API_KEY_SERVICE_BLOCKED` and
`API_KEY_INVALID`. On 2026-11-16, a newly supplied key successfully recognized a
synthetic text image after billing was enabled. The updated backend then
recognized the same text in both sync and async SDK paths using
`GOOGLE_VISION_API_KEY`. No secret was saved in source/configuration artifacts.
A bounded live one-ad OCR-to-preparation run is recorded below. A substantive
newspaper run still needs an inspected sampling design and OCR/template fidelity.
A downstream live smoke run, starting after OCR, is also recorded below. Offline continuous-run checks
also passed with real R preparation on the installed R 4.5.0 runtime; the locked
R runtime mismatch noted above remains.

## Live post-OCR smoke run

On 2026-11-15, the repository phase runner processed four historical postings
from the existing 20-row example, without its old resumes or demographic
fields. It used `gpt-4o-2024-08-06`, temperature zero, asynchronous execution,
logical batches of two, and two templates per posting. All data, local YAML
files, prompts and results remain in an ignored `outputs/post-ocr-smoke.*`
directory, not public fixtures. The original example was not changed.

The first four template requests produced three valid pairs and one rejected
pair missing a required qualification placeholder. Validation stopped the
runner before population; the checkpoint and its error were retained. A new
local prompt and separate output file produced four valid pairs. This was an
explicit configuration revision, not an automatic retry loop or a runtime
parser change. Inspection still found generic experience claims outside the
qualification placeholder, so template compliance is only structural, not
proof of a controlled or historically accurate research design.

The researcher approved two synthetic profiles per posting (good-fit and
poor-fit) and the explicit `audit_id: post_ocr_smoke_test`. The assignment
table supplied eight persistent candidate IDs and an illustrative
`smoke_variant` indicator outside package code; no demographic indicator or
identity was inferred by the pipeline. Population preserved all assignments
and source posting text, with no unresolved placeholders.

All four live experiment jobs succeeded. R preparation consumed the unchanged
native CSV and produced eight candidate observations, excluding zero jobs.
The four good-fit profiles were selected and the four poor-fit profiles were
not selected. All eight decisions, emitted-answer log probabilities and
variant values matched their original candidate IDs; no resume or prompt
payload entered the prepared CSV. Outcome sums were 4 (`pick`), 2 (`pick_top`,
using a smoke-specific 0.25 top share), and 4 (`pick_threshold`, threshold 0.99).
These outcomes exercise plumbing; they are not evidence of a qualification
effect or of fair hiring behavior.

Completed template and experiment phases were rerun with Python networking
disabled. They succeeded without network inference, and their checkpoint
CSVs were byte-identical; repeated preparation also produced an identical CSV.
R used the installed 4.5.0 runtime with the restored package versions, not
the recorded 4.4.2 target. Estimation and rendering were deliberately not run:
the prepared CSV awaits researcher inspection, and this tiny sample is not a
substantive regression dataset. The earlier synthetic checks remain the
numerical oracle for the complete analysis path.

## Live one-ad OCR-to-preparation smoke run

On 2026-11-16, the newspaper YAMLs were initially configured for the real
paint-salesmen ad in the Omaha Daily Bee, January 1, 1900, page 7. The
[source archive](https://nebnewspapers.unl.edu/lccn/sn99021999/1900-01-01/ed-1/seq-7/)
provided IIIF region `235,2380,750,140`. The downloaded input and all
generated artifacts remain in ignored `tests/manual/newspaper_pipeline/local/omaha-1900-smoke/`.

The first reconstruction responses wrapped JSON in Markdown, which the old
parser rejected. The parser now accepts one whole-response JSON fence before
JSON/schema checks. At the time of this run it also enforced exact-source and
cleanup-fidelity checks. Those content checks were later removed at the
researcher's request; see below. The reconstruction fingerprint version
was bumped; `ads-v2.csv` and `ocr-checkpoints-v2/` keep the original failed
attempts untouched rather than overwriting their records.

The continuous run then completed real Vision OCR, GPT-4o August reconstruction,
two generated templates, seeded pool assignments, population, one successful
experiment and real R preparation. Preparation produced two candidate rows and
excluded zero jobs. Candidate IDs, decisions and emitted-answer log probabilities
matched the native experiment. Outcome sums were 2 (`pick`), 1 (`pick_top`),
and 2 (`pick_threshold`). No estimation or rendering was run. The independent
synthetic `treatment` pool is only a plumbing label, not a causal study design.

Review found an important fidelity limitation: Vision isolated the word `on`
from “work on commission” into its own block; reconstruction excluded that
block, so cleaned text reads “work commission.” The raw block remains saved.
Source coverage validates the explicit partition, not whether each exclusion
reason is substantively correct. The exported ad remains `review_required=true`;
successful execution is not proof of newspaper transcription accuracy or a
validated historical candidate design.

The installed R runtime remained 4.5.0 rather than the lockfile's 4.4.2 target;
its existing environment warning did not prevent preparation. A completed-run
resume was checked with Python networking blocked and the six saved CSVs
compared byte-for-byte. No live credentials or generated research files were
added to Git.

## Current local newspaper input

After the one-ad run, the default YAMLs were switched at the researcher's request
to an unchanged copy of an existing research PDF: Chicago Daily Tribune,
April 2, 1950, page A6, ProQuest export `Classified Ad 36 -- No Title`.
The source and local copy have SHA-256
`1582ef343286542354fcbc588169f37a378c46a639b9654ed2196752afd17b7c`.
The title, date and page were inspected from the PDF. This is one complete
newspaper page, not a crop. Input and fresh output paths are under
`tests/manual/newspaper_pipeline/local/chicago-1950-smoke/`, separate from the earlier Omaha run. The PDF is
local-only and is not distributed in Git; its original reproduction notice is
retained. All generated files remain ignored. The
previous one-ad results above do not constitute live verification of this new
full-page configuration; its later completed run is recorded below.

## Relaxed reconstruction validation

At the researcher's request, extraction no longer enforces character equality,
numeric formatting, complete source partitions or mandatory per-ad source
mappings. This follows the reference's prompt-based approach to fidelity:
revision `c9391854ea55806ec252625cd2f48fb9edb156cd`,
`images_to_jobs/image_rec.py` (`initial_api_call`, `text_clean_up`). Shared
inference, basic JSON/schema and text validation, raw OCR/model checkpoints,
page-level provenance and `review_required=true` remain.

The saved Chicago response proposes 32 ads and passes the relaxed parser
offline, including spelling corrections and records without individual source
assignments. This does not establish extraction accuracy. Exports repeat full
raw page text per ad and emit empty `source_spans_json`; no verified per-ad
attribution is claimed. Ad IDs hash page identity plus cleaned text, not response
position or temporary model keys.

The v3 prompt/parser uses fresh `ads-v3.csv` and `ocr-checkpoints-v3/` paths.
The original failed attempt and model response remain untouched; an old model
response is never relabeled as a response to the new prompt. Raw Vision pages
can be copied only after their source hashes, metadata, IDs and checkpoint
structure have been verified; their new outcomes start pending. No new paid
inference was performed while checking the saved response.

## Manual-test file organization

Newspaper-only YAMLs and prompts now live in
[`tests/manual/newspaper_pipeline/`](../../tests/manual/newspaper_pipeline/README.md).
Chicago inputs/checkpoints and the Omaha archive were moved under its
`local/` folder. All scans and generated outputs remain ignored. Generic scripts,
package code and reusable examples remain in their usual locations.

Only absolute `output_path` and `checkpoint_directory` bindings were updated in
existing manifest/owner metadata. Original metadata was retained beside each
file with a `.before-relocation` suffix. Fingerprints, raw pages, model responses
and CSV contents were not rewritten. The active Chicago Vision page was verified
against the relocated source and remains usable without another OCR call;
historical CSV provenance still records acquisition-time paths. No paid provider
calls were made for this reorganization.

## Completed Chicago live smoke run

On 2026-11-17, the researcher ran the manual shell launcher. Its console output
reported 32 extracted ads, saved templates and populated resumes, 32 completed
experiment jobs, and 64 regression-ready candidate rows with zero excluded jobs.
The runner finished through preparation without invoking estimation or plotting.
Template generation used GPT-5.5 medium with schema-enforced text/field parts;
OCR reconstruction and experiments used GPT-4o August 2024. Candidate values
came from the configured seeded synthetic pools, not the paper's assignments.

The seven stage/master YAMLs, prompts, launcher, sampling design, audit ID and
source hash are versioned in the manual-test directory. The PDF remains locally
at its unchanged path so existing compatible OCR checkpoints can still be reused.
Completed outputs, earlier failed attempts, candidate assignments and caches
remain local and are not included in Git. This record reflects the reported
execution outcome, not a row-level accuracy or substantive research review.

The `renv` out-of-sync warning remained during preparation; formal analysis still
requires environment inspection and researcher review of the prepared data.
The complete Python suite with offline R integration also passed locally
(971 tests; five live tests skipped), and schema transport passed in a fresh
editable installation. These offline checks do not call paid providers.
