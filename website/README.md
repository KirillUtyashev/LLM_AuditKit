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
Extraction labels its artifacts `Input · Newspaper scan` and `Output · Extracted
text`. Generation adds `Input · Job posting + prompt` and `Output · Resume
templates`. These are small text labels, not new panels.
The note below the jobs heading explains that the images provide source context:
postings are stored as text and clicking an image opens that extracted text.
`Download job text` exports all matches as CSV, not images.
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
Each has its own scan and actual AuditKit OCR output. Each also has one matching
year-specific job-agency prompt, two distinct generated resume templates, and a
real evaluation of that pair. Switching papers changes the complete
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
AuditKit structured parts, two templates per prompt, gpt-5.5 medium generation,
and gpt-4o-2024-08-06 evaluation with temperature 0 and log probabilities.
Maintainer-local YAML, checkpoints and curation commands are under ignored
`website/local/year-prompts-v1/` and `website/local/year_prompt_demo.py`.
Earlier OCR/style runs remain under their existing ignored directories.
The public site needs none of those local files and
makes no live model requests. These runs use EDSL's own configured local cache,
not a website-side inference cache.

The final hiring questions explicitly request JSON decisions rather than a
bullet list. Earlier runs remain preserved locally; changed generation inputs
have new evaluations and fresh checkpoints, not relabeled old model answers.

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
The Boston example uses the Administrative Assistant ad and the paper's 1990
job-agency generation prompt. Chicago uses `prompt_1970`; Birmingham 2000 uses
the paper's `prompt_2001` function, which also covers 2000–2002.
The source posting image is on the left. The editable `Prompt summary` on the
right shows only the gist, not the full instructions or source posting. One
prompt is configured per paper, so the old style buttons are hidden. Drafts
are scoped to paper/job/prompt and reset on page reload. For an unchanged
summary, `Generate resume` opens the two jointly generated templates as typeset documents with
serif text, centered contact placeholders and restrained section headings.
Small `Template 1` / `Template 2` buttons switch the preview. Each template has
a distinct fictional background, not just a different name. The dialog is
explicitly labeled as a saved example. Edited summaries or prompts
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
The source is `jobs_to_experiment/prompts.py` plus the job-agency persona from
`jobs_to_experiment/resume_creation.py`, pinned reference revision
`c9391854ea55806ec252625cd2f48fb9edb156cd`.
The year-specific content guidance is retained, but this demo uses two templates
instead of four, structured parts, and only canonical name/address placeholders.
Dates and school details formerly controlled by other paper placeholders are
generated example background here. SSNs are omitted, phone numbers use reserved
example ranges, and anachronistic job-website references are omitted from the
agency persona. These are explicit adaptations, not byte-for-byte paper runs or
a validated research design. There are no Historian/Role-play generation variants.
Full generation user/system prompts, reference path/function/revision and the
adaptation list are retained in each public saved variant; `promptSummary` is
separate presentation text. Evaluation matching uses the full generation inputs,
never the summary. Editing the summary cannot submit a new model request.
Generation commands below are maintainer-local: the ignored run artifacts are
not included in a fresh checkout and are not needed to view the published demo.
YAML settings, CSV checkpoints and source snapshots stay under
`website/local/year-prompts-v1/`. To explicitly regenerate pending Boston outputs (paid):

```bash
EDSL_DATABASE_PATH=sqlite:///website/local/year-prompts-v1/boston-cache.db PYTHONPATH=src .venv/bin/python website/local/year_prompt_demo.py boston-1990 generate
```

The browser makes no generation requests. Each saved output retains its real
request ID and generation fingerprint in the display bundle. Selecting another
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
Editing a prompt summary hides the filled example until the original summary is
restored. Saved templates are never modified; unsupported placeholders
are not silently left unfilled. Bundles without saved resume outputs hide this
optional section; the published Boston bundle includes the complete examples.

## How does the model decide?

Continue scrolling or open <http://127.0.0.1:8765/#experiment>. Review the posting
or either candidate's exact resume using the input buttons. `Run experiment`
reveals the saved interview decisions and original model explanation for the
unchanged prompt. Editing the hiring prompt disables playback and clears the
result; this static site cannot run a new model request.

Each newspaper's new resume pair was actually run through `ExperimentRunner`
and shared inference with `gpt-4o-2024-08-06`, temperature 0 and log probabilities.
These small synthetic examples are not evidence
of bias or a replication of the paper. No browser inference runs.

YAML, fixed source snapshots, prompt/persona files and CSV checkpoints live under
ignored `website/local/year-prompts-v1/<paper>/experiment/`. Earlier one-template
and style-comparison runs remain untouched in their old directories and are not
reused for the new resumes. To explicitly execute a pending Boston evaluation (paid):

```bash
EDSL_DATABASE_PATH=sqlite:///website/local/year-prompts-v1/boston-cache.db PYTHONPATH=src .venv/bin/python website/local/year_prompt_demo.py boston-1990 experiments
```

Exported examples preserve exact input bindings, original rendered prompts,
request IDs, model configuration and emitted-answer log probabilities. Changes
to the source, candidate ordering, generation preset or hiring prompt cannot
display an unrelated result. Only the explicitly approved demonstration payload
is public; other research runs and local directories remain excluded.

## From decisions to data

Open <http://127.0.0.1:8765/#results> or continue scrolling. The final table shows
the selected newspaper's two candidate evaluations: candidate, decision,
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
