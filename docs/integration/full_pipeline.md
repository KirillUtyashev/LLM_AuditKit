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

## Verification record and real-data follow-up

On 2026-11-15, both offline modes and the optional R path passed locally. The
full Python suite with R integration enabled passed (835 tests; five live
tests skipped), and the complete R suite passed. Locked R packages were
restored, but the local R executable was
4.5.0 rather than the recorded 4.4.2 target; `renv::status()` still reports that
runtime mismatch. This is not verification of the exact locked R runtime.

Live OCR verification still needs a selected newspaper page and working Google
Vision credentials. Testing the stored keys returned `API_KEY_SERVICE_BLOCKED`
and `API_KEY_INVALID`; neither successfully performed OCR. A downstream live
smoke run, starting after OCR, is recorded below.

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
