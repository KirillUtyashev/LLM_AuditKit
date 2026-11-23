# Pipeline showcase

A small static walkthrough: **newspaper scan → job rows → resume prompts → candidate resumes → model evaluation → candidate-output table**.
No build, dependencies, live OCR or browser model calls. Population and
experiments use saved demonstration data; no regression is run by the website.

## Preview

From the repository root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory website
```

Open <http://127.0.0.1:8765/>. Choose a paper, inspect the original newspaper, then scroll
down to the jobs. Search the jobs, inspect their source excerpts, or download the
filtered CSV. Source notes and raw OCR remain in the data, not in a UI accordion.
The stages stay in the document, without tabs or stage-navigation controls.
The newspaper remains one large preview, with full-page enlargement and zoom.
Search covers every available job for the selected newspaper (59 Boston,
118 Chicago, or 86 Birmingham ads), but displays at most three matches side by side on desktop,
stacked on mobile. Clearing search restores the three featured images.
The result count shows the full match count, not just the previews.
CSV download exports all matching jobs, not only the three shown.
All 59 local jobs have source-image previews. Six use previously located
regions (including the three featured examples); the rest are approximate
source areas matched using the saved Vision word coordinates. Their hover
titles and alt text identify them as approximate. Some include neighboring
text or omit fragments, especially when extraction merged ads across columns.
These crops are website preview annotations, not verified OCR-stage mappings.
The local curation script is `website/local/map_source_areas.py`; no new paid
OCR/model calls were made. Bundles without any usable crop still fall back
to a labeled text preview.
Click any image or text preview to read its full extracted text in a dialog; Close or Escape
returns to the images. The newspaper preview and its zoom remain unchanged.
The paper and current scroll stage are
bookmarkable; browser Back/Forward is supported. Content fades in as it enters
the viewport, with reduced-motion and no-animation-API fallbacks.

Only the website directory is served, never the repository root or its credentials.

## Published newspaper examples

The selector offers **Boston, 1990**, **Chicago, 1970**, and **Birmingham, 2000**.
Each has its own scan and actual AuditKit OCR output. Each also has three saved
prompt variants, two distinct generated resume templates per variant, and three
real evaluations of those resume pairs. Switching papers changes the complete
walkthrough, not just its opening image. Candidate names/addresses remain the
same fixed fictional demonstration profiles; work histories and model outcomes
belong to each newspaper's selected job.

Chicago uses the *Chicago Tribune*, 31 May 1970, page D8. Birmingham uses
*The Birmingham News*, 2 April 2000, page 4G—not 2001. Both dates are visible
on their scans. Their resume examples use the hospital Stationary Engineer and
Payroll Specialist ads respectively. Three featured source regions per paper
were located for display; other crops are approximate OCR-text alignments.
OCR can omit, split or merge material; these are not verified complete transcripts.
The original Chicago ProQuest reproduction notice is retained. See
[asset provenance](assets/README.md); third-party material is not MIT-licensed.

The additional runs use the same generation/evaluation settings as Boston:
AuditKit structured parts, two templates per preset, gpt-5.5 medium generation,
and gpt-4o-2024-08-06 evaluation with temperature 0 and log probabilities.
Maintainer-local YAML, checkpoints and curation commands are under ignored
`website/local/chicago-1970/`, `website/local/birmingham-2000/`, and
`website/local/extend_demo.py`. The public site needs none of those files and
makes no live model requests. These runs use EDSL's own configured local cache,
not a website-side inference cache.

Birmingham's final question explicitly requests a JSON object rather than a
bullet list. Its earlier malformed-response run is preserved locally; the
published examples come from a new prompt/run with fresh checkpoints, not an
edited or relabeled model answer.

### Boston 1990

The Boston entry in public `website/data/newspapers.json` and
`website/assets/boston-1990-08-05.jpg` contain the maintainer-approved Boston
scan and all 59 saved pipeline results, with the full resume/experiment flow.
On loopback hosts only, an optional ignored `website/local/newspapers.json`
can override that public data for development.
The three featured examples are Administrative Assistant (Southmayd Associates),
Operations Staff (Technical Aid Corporation), and Travel Reservationist (TASC).
The date comes from the research filename, not a verified
masthead. These are saved results from an AuditKit OCR run, not a live browser
run or a verified complete transcription. Their text is unedited.
The full raw Vision page is preserved separately from each cleaned ad.
Approximate source crops were manually located, not produced by the extraction.

One thin, centered continuous line leads from the scan into the jobs,
without provider icons, names or intermediate tool captions.
The selector uses only city and year, for example Boston, 1990.
The earlier manual bundle is retained locally as `newspapers-manual.json`;
`newspapers-large-ads.json` preserves the previous CIGNA/BBN/IRS selection.
The live run configuration, checkpoints and original comparison report remain local.

The maintainer explicitly approved public sharing of the Boston scan and its
saved synthetic resumes/results on 19 November 2026. Only the reviewed display
bundle and scan were copied into the public assets. The rest of `website/local/`
stays ignored: do not force-add research directories, raw checkpoints or secrets.
A fresh checkout contains all three complete demonstrations.

## Resume prompt demo

Continue scrolling below the jobs, or open <http://127.0.0.1:8765/#resumes>.
The Boston example uses the Administrative Assistant ad and three saved
prompt variants: Strong fit, Transferable skills, and More detail.
The source posting image is on the left; an editable prompt window is on the
right with style buttons directly above it. Switching styles shows the exact
variant-instruction paragraph and preserves each style's local edits. Drafts
are scoped to paper/job/style and reset on page reload. Shared instructions
are omitted; complete prompts remain in local text/YAML files. For an unchanged
preset, `Generate resume` opens its two jointly generated templates as typeset documents with
serif text, centered contact placeholders and restrained section headings.
Small `Template 1` / `Template 2` buttons switch the preview. Each template has
a distinct fictional background, not just a different name. The dialog is
explicitly labeled as a saved example. Edited prompts or presets
without saved output disable the button: this static demo does not run inference.
Highlighted placeholders explain on hover or keyboard focus that candidate
details are intentionally filled in next; Escape dismisses the explanation.
The UI uses plain `resume` without accents.

HTML asset URLs and the app's helper-module import share a cache revision;
bump all three together when changing their DOM/data contract. Local JSON is
revalidated on reload. Startup rendering errors show a visible reload message
instead of leaving empty resume panels.

Paired outputs were generated through AuditKit's template-generation API with
`templates_per_scenario: 2` and
shared inference using gpt-5.5, medium reasoning, and structured parts mode.
Name and address remain literal placeholders for the later population stage.
These are illustrative prompt comparisons, not a validated hiring design.
Generation commands below are maintainer-local: the ignored run artifacts are
not included in a fresh checkout and are not needed to view the published demo.
Full prompts, YAML settings, CSV checkpoints and source input stay under
`website/local/resume-pairs/` (source input/system files are shared with the
preserved earlier `resume-demo/`). To explicitly regenerate pending outputs (paid):

```bash
PYTHONPATH=src .venv/bin/python website/local/resume-pairs/generate.py
```

The browser makes no generation requests. Each saved output retains its real
request ID and generation fingerprint in the local bundle. Selecting another
paper without a matching saved demo hides the whole resume section rather than
reusing another newspaper's image or prompt. The approved public Boston bundle
includes the saved examples; other local research artifacts are not published.

## Templates become candidates

Scroll below the editor or open <http://127.0.0.1:8765/#population>.
Two explicitly synthetic profiles fill name and address in their own assigned
templates. Stable candidate IDs map to content-derived template IDs; no template
is reused for both. Candidate buttons switch the document, including its distinct
generated work history. A short highlight marks the populated personal details.
The prose within each original template stays unchanged. Motion is disabled for
reduced-motion preferences. This is not a controlled same-qualification comparison.

These are fixed local presentation examples, not the paper's sampling procedure
or research assignments. No inference or extra fetch runs when switching.
Editing a prompt hides the filled example until a valid unchanged preset is
selected again. Saved templates are never modified; unsupported placeholders
are not silently left unfilled. Bundles without saved resume outputs hide this
optional section; the published Boston bundle includes the complete examples.

## How does the model decide?

Continue scrolling or open <http://127.0.0.1:8765/#experiment>. Review the posting
or either candidate's exact resume using the input buttons. `Run experiment`
reveals the saved interview decisions and original model explanation for the
unchanged prompt. Editing the hiring prompt disables playback and clears the
result; this static site cannot run a new model request.

Each newspaper's three preset examples were actually run through `ExperimentRunner`
and shared inference with `gpt-4o-2024-08-06`, temperature 0 and log probabilities.
These small synthetic examples are not evidence
of bias or a replication of the paper. No browser inference runs.

YAML, fixed source snapshots, prompt/persona files and CSV checkpoints live under
ignored `website/local/experiment-pairs/`. Earlier one-template runs remain under
`experiment-demo/` and are not reused for changed candidate resumes.
To explicitly execute pending scenarios
(paid), or read validated completed checkpoints without inference:

```bash
PYTHONPATH=src .venv/bin/python website/local/experiment-pairs/run.py
PYTHONPATH=src .venv/bin/python website/local/experiment-pairs/run.py --export
```

Exported examples preserve exact input bindings, original rendered prompts,
request IDs, model configuration and emitted-answer log probabilities. Changes
to the source, candidate ordering, generation preset or hiring prompt cannot
display an unrelated result. Only the explicitly approved demonstration payload
is public; other research runs and local directories remain excluded.

## From decisions to data

Open <http://127.0.0.1:8765/#results> or continue scrolling. The final table shows
the selected newspaper's six candidate evaluations across the three presets: candidate, decision,
emitted-answer logprob and model. `Download CSV` preserves full-precision logprobs,
numeric decisions, explanations and stable candidate/template/request/model IDs.
The displayed logprob is rounded; it is not a calibrated hiring probability.

This candidate-level convenience export is not an R-ready regression dataset.
It does not infer audit IDs, demographic indicators or research specifications.
The final message links to the GitHub repository so researchers can scale the
workflow to thousands of applications and continue with their own analysis.
No regression or statistical conclusion is presented for this small demo.

## Archive fixtures and Pages

The retained [archive fixture bundle](data/archive-newspapers.json) uses
three earlier public archive pages, with two curated excerpts each:

- [Omaha Daily Bee, 1 January 1900, page 7](https://nebnewspapers.unl.edu/lccn/sn99021999/1900-01-01/ed-1/seq-7/): Nebraska Newspapers.
- [Bend Bulletin, 18 October 1918, page 4](https://oregonnews.uoregon.edu/lccn/sn90051770/1918-10-18/ed-1/seq-4/): Historic Oregon Newspapers.
- [Sunday Oregonian, 18 April 1920, printed page 19](https://oregonnews.uoregon.edu/lccn/sn83045782/1920-04-18/ed-1/seq-43/): Historic Oregon Newspapers.

Their original archive OCR, human-readable transcriptions, correction notes,
source links, dimensions and approximate regions remain in the bundle.
Records retain `review_required=true`; display labels are not persistent IDs.
Historical wording is not endorsed. Third-party material is not relicensed
by this project. Confirm reuse terms before adding new public assets.

The [Pages workflow](../.github/workflows/pages.yml) validates the static files
and uploads only `website/` from `main` or the explicit showcase branch
`feat/37-static-pipeline-showcase`. The latter permits an initial collaborator
preview without merging unreviewed source into main. It rejects a local
research directory. GitHub Pages uses the GitHub Actions publishing source.
Local preview commands never deploy or change repository settings.
All paths support GitHub Pages repository prefixes. Public hosts never fetch
the optional local research bundle.

## Checks

```bash
node --check website/app.mjs
node --test tests/website/*.test.mjs
python -m pytest tests/test_website.py
python -m pytest
```

Tests use local fixtures and mocked browser objects; no credentials or network
inference. Native browser inspection may require leaving Chrome idle.
