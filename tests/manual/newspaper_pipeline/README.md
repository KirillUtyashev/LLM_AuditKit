# Manual newspaper pipeline smoke test

This directory holds the real-newspaper test setup, not production defaults.
Pytest validates the YAML wiring offline but never executes this paid workflow
automatically. Shared pipeline code and reusable examples stay in their normal
package, script and example directories.

Install the package and optional OCR dependencies with
`python -m pip install -e ".[ocr,test]"`. Install system Poppler as described in
the [OCR guide](../../../docs/guides/newspaper_ocr.md), configure Vision/OpenAI
credentials in the root `.env`, and restore the R packages with
`Rscript -e 'renv::restore(prompt = FALSE)'`. The source PDF is local-only:
another checkout needs an authorized copy at the configured path or a different
source with updated metadata. Live execution makes paid calls.

Run from the repository root:

```bash
./tests/manual/newspaper_pipeline/run.sh --check
./tests/manual/newspaper_pipeline/run.sh
```

The wrapper defaults to the paid continuous `--run`, uses the repository `.venv`
when available (otherwise `python3`), and works from any current directory when
invoked by its absolute path. It forwards `--check`, `--phase ...` and `--help`
to the existing Python runner and prints its output without Python buffering.
It does not activate a shell environment, install dependencies or add retries.

The live command requires Vision/OpenAI credentials in the environment or root
`.env`, OCR dependencies, Poppler and the R environment. It stops after R
preparation. Estimation and plotting require a separate `--phase analysis`;
individual phases also remain available for intermediate review. See the
[pipeline guide](../../../docs/guides/pipeline.md).

## Layout

- `pipeline.yaml`: wiring, candidate pools and population settings.
- `run.sh`: explicit shell launcher (defaults to the live smoke test).
- `ocr.yaml`, `templates.yaml`, `experiments.yaml`: paid stage settings.
- `prepare.yaml`, `estimate.yaml`, `render.yaml`: separate R stage settings.
- `prompts/`: newspaper-specific prompts; shared prompts remain in examples.
- `local/chicago-1950-smoke/`: active input, OCR checkpoints and generated outputs.
- `local/omaha-1900-smoke/`: earlier smoke-test archive, not the active input.

Paths inside YAML resolve relative to that file. The active source is an
unchanged Chicago Daily Tribune PDF, April 2, 1950, page A6, ProQuest export
`Classified Ad 36 -- No Title`. SHA-256:
`1582ef343286542354fcbc588169f37a378c46a639b9654ed2196752afd17b7c`.
The unchanged PDF remains locally at the path configured in `ocr.yaml` but is
not distributed in Git. Its original reproduction notice is retained; no
redistribution permission is asserted. A full page can produce many ads and
model requests; batching does not cap total spending.

The entire `local/` folder is ignored: scans, checkpoints, assignments, model
outputs and prepared results remain untracked. Credentials stay in the root
`.env` or environment, never in test configs. The launcher, YAMLs, prompts and
this README are versioned. The source and earlier outputs remain locally
available for inspection.

Template generation uses `gpt-5.5` with medium reasoning and a 16,000-token
completion budget (including reasoning) and schema-enforced `response_mode: parts`,
writing `templates-gpt55-medium-parts.csv`. The model returns free text plus
configured field references; the application renders literal placeholders.
The earlier GPT-4o `templates.csv` and GPT-5.5 text-mode
`templates-gpt55-medium.csv` are retained but are not reused across contracts:
the first run with this configuration generates all template pairs anew.
OCR reconstruction and experiment execution still use `gpt-4o-2024-08-06`;
existing compatible OCR checkpoints are reused. Changing models does not
guarantee that every generated template satisfies the placeholder contract.

The candidate pools and treatment label are synthetic mechanics-test inputs,
not the paper's assignments or a validated study. All extracted ads require
review. See the [verification record](../../../docs/integration/full_pipeline.md).

## Completed live smoke test

On 2026-11-17, the live runner reported 32 extracted ads, completed template
generation and population, 32 completed experiment jobs, and 64 prepared
candidate rows with zero excluded jobs. It stopped before estimation and
plotting as intended. Generated results remain local, not committed.
The existing `renv` out-of-sync warning still requires inspection before formal
analysis; this test does not establish OCR accuracy or research validity.
