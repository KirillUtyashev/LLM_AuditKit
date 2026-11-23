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
Each has its own scan and actual AuditKit OCR output. Each also has a matching
year-specific job-agency prompt with eight saved setting combinations: 2/4
templates, 2/4 job-related skills, and entry-level/experienced backgrounds.
Every combination has genuine generated templates and a real evaluation of all two or four
explicitly assigned candidates. Switching papers changes the complete
walkthrough, not just its opening image. Candidate names remain fixed fictional
demonstration profiles; addresses, schools and dates use recorded paper values.
Generated work histories and model outcomes
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
AuditKit structured parts, two or four templates per prompt, gpt-5.5 medium generation,
and gpt-4o-2024-08-06 evaluation with temperature 0 and log probabilities.
Maintainer-local YAML, checkpoints and curation commands are under ignored
`website/local/controlled-fields-v1/` and `website/local/controlled_fields_demo.py`.
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
The source posting image is on the left. On the right, `Prompt summary` embeds
three highlighted native dropdowns directly in its sentences: resume count,
job-related skill count and experience. Clicking a phrase opens its menu;
keyboard selection works without a custom menu implementation. The old style
buttons and free-text editor are hidden for these controlled examples.
Choices are remembered independently per paper/job until reload. The summary
shows the gist, not the full instructions. `Inspect templates` opens the selected
combination's two or four jointly generated templates as typeset documents with
serif text, centered contact placeholders and restrained section headings.
Small `Template 1` … `Template N` buttons switch the preview. Each template has
a distinct fictional background, not just a different name. The dialog is
explicitly labeled as a saved example. Invalid or unavailable settings cannot
show another combination's output. This static demo does not run inference.
Names, addresses, schools and dates have highlighted buttons: clicking explains
that they are filled during population and offers a link to that next step.
Escape dismisses the explanation and restores focus to its trigger.
Switching settings clears open documents and model responses, then updates
population, evaluation and the final table/CSV to the exact saved selection.
Highlighted placeholders explain on hover or keyboard focus that candidate
details are intentionally filled in next; Escape dismisses the explanation.
The UI uses plain `resume` without accents.

HTML asset URLs, the helper-module import and the public data URL share a cache
revision; bump all four together when changing their DOM/data contract. Both
public and local JSON revalidate on reload. This prevents cached pre-control
data from silently falling back to the older textarea after a UI update. An
already open/cached HTML page may still need a hard refresh after deployment.
Startup rendering errors show a visible reload message
instead of leaving empty resume panels.

Saved outputs were generated through AuditKit's template-generation API with
`templates_per_scenario: 2` or `4` and
shared inference using gpt-5.5, medium reasoning, and structured parts mode.
Name, address, school and education/employment dates remain literal placeholders
for the later population stage. Boston and Birmingham use `{{university}}`;
Chicago's 1970 format uses `{{high_school}}`. Date fields include education start/end
years (Chicago has only a recorded graduation year) and work months/years;
Boston/Birmingham retain `{{work_end}}` for the recorded `Present` value.
Birmingham also has in-school work dates.
The source is `jobs_to_experiment/prompts.py` plus the job-agency persona from
`jobs_to_experiment/resume_creation.py`, pinned reference revision
`c9391854ea55806ec252625cd2f48fb9edb156cd`.
The year-specific content guidance is retained, but explicit control settings
override template/skill counts and entry-level versus experienced backgrounds.
The demo uses structured parts for every controlled field, rather than allowing
the model to invent school names or dates. SSNs are omitted, phone numbers use reserved
example ranges, and anachronistic job-website references are omitted from the
agency persona. These are explicit adaptations, not byte-for-byte paper runs or
a validated research design. There are no Historian/Role-play generation variants.
Full generation user/system prompts, reference path/function/revision and the
adaptation list are retained in each public saved variant; `promptSummary` is
separate presentation text. Evaluation matching uses the full generation inputs,
never the summary. Editing the summary cannot submit a new model request.
Template count is schema-constrained; skill count and experience are prompt
guidance, not general package guarantees. Job-related skill bullet counts were
checked for the saved examples before publication. Each complete combination
was actually generated, not assembled by trimming or duplicating another resume.
Generation commands below are maintainer-local: the ignored run artifacts are
not included in a fresh checkout and are not needed to view the published demo.
YAML settings, CSV checkpoints and source snapshots stay under
`website/local/controlled-fields-v1/`. Earlier inline-control and year-prompt runs remain preserved.
To explicitly generate pending Boston setting combinations (paid):

```bash
EDSL_DATABASE_PATH=sqlite:///website/local/controlled-fields-v1/boston-cache.db PYTHONPATH=src .venv/bin/python website/local/controlled_fields_demo.py boston-1990 generate
```

The browser makes no generation requests. Each saved output retains its real
request ID and generation fingerprint in the display bundle. Selecting another
paper without a matching saved demo hides the whole resume section rather than
reusing another newspaper's image or prompt. The approved public Boston bundle
includes the saved examples; other local research artifacts are not published.

## Templates become applications

Scroll below the editor or open <http://127.0.0.1:8765/#population>.
Two or four explicitly synthetic profiles fill identity, school and date fields
in their own assigned templates. Every selected template becomes one application;
stable candidate IDs map to distinct content-derived template IDs. All resumes
appear in a two-column document grid (stacked on mobile); four produces a 2×2 grid.
`View full resume` enlarges any application. Highlighted fields are buttons:
click to choose a preset name, address, school or coherent date range.
The prose within each original template stays unchanged. Motion is disabled for
reduced-motion preferences. This is not a controlled same-qualification comparison.

Each variant declares its exact `placeholderFields`; each candidate/template
assignment carries explicit `values` for school and dates. Names/addresses come
from separate explicit profile fields, not that map: names remain synthetic,
while assignment `address` and `populationPools` reuse the original paper's
city/year address and institution pools. Boston uses University of Lowell and
Southeastern Massachusetts University; Birmingham uses University of Montevallo
and UAB; Chicago uses Gage Park and Jones Commercial high schools.
Date presets are selected recorded field sets, not newly shifted years.
Chicago records graduation only; Boston/Birmingham preserve `Present` literally.
The experience menu controls writing guidance, independently of populated dates.
Missing, extra, blank or out-of-pool assignment values are rejected.

`populationSource` records the pinned `jobs_to_experiment/experiment_setup.py`
revision, pool names, relative date-source file, source date and selected-value
hash. Only requested replacement fields are reused; no original names, private
resume rows, demographics or old outcomes are exported. These new applications
are not exact replications of the original source jobs or researcher assignments.
`generationProjection` documents deterministic date-label changes after generation:
remove invented Chicago attendance starts and retain `Present` as one end field.
It preserves original template IDs/field lists; original generation artifacts stay
local. Other generated prose stays unchanged. These projections receive new
content-derived template IDs and fresh evaluations.

Edits exist only in page memory and keep candidate/template IDs and generated
prose unchanged. Date presets choose complete recorded education/employment sets,
not disconnected or invented years. Changed inputs hide the saved experiment and CSV until
`Reset details` restores the evaluated resumes. Paper or generation-setting
changes clear edits. The browser does not evaluate changed applications.

These are fixed local presentation examples, not the paper's sampling procedure
or research assignments. No inference or extra fetch runs when switching.
Selecting unsupported settings hides downstream output rather than reusing a
stale result. Legacy free-text summaries still disable playback when edited.
Saved templates are never modified; unsupported placeholders
are not silently left unfilled. Bundles without saved resume outputs hide this
optional section; the published Boston bundle includes the complete examples.

## How does the model decide?

Continue scrolling or open <http://127.0.0.1:8765/#experiment>.
`Input · Job posting + resumes` identifies the supplied artifacts without another
button row; inspect jobs and full resumes in the earlier sections.
`Output · Interview decisions` appears with the revealed results. Choose `Role-play`
(a period hiring manager) or `Historian` (a descriptive prediction of an employer's
period decisions). The visible `Prompt summary` omits the applicant qualifier
and JSON-output boilerplate. Full prompts remain unchanged in the saved data;
these two versions were authored for the website, not copied verbatim from the paper.
`Inspect model decisions`
reveals the saved interview decisions and original model explanation for the
unchanged summary. Editing the summary disables playback and clears the
result; this static site cannot run a new model request.
The underlying full prompt, persona and populated resumes must still match
the saved evaluation. Summaries are separate presentation strings, never
substitutes for the actual recorded inference inputs.

Each newspaper's eight selected applicant sets were actually run under both
perspectives through `ExperimentRunner`
and shared inference with `gpt-4o-2024-08-06`, temperature 0 and log probabilities.
These small synthetic examples are not evidence
of bias or a replication of the paper. No browser inference runs.

YAML, fixed source snapshots, prompt/persona files and CSV checkpoints live under
ignored `website/local/hiring-perspectives-v1/<paper>/<perspective>/experiment-2/`
and `experiment-4/`. The two personas have distinct stable IDs and standard EDSL
trait/instruction rendering through the existing adapter. All 48 interviews
(144 candidate observations) have actual saved responses. Switching perspectives
clears stale decisions and changes the table/CSV; prompt drafts are scoped to
paper, generation setting and perspective. Choices are remembered per paper until reload.
All templates derive from genuine generation, with explicit date-label projections
and fresh prompts, decisions and log probabilities for the changed populated
resumes—not earlier outcomes. Earlier one-template
and style-comparison runs remain untouched in their old directories and are not
reused for the new resumes. To explicitly execute a pending Boston evaluation (paid):

```bash
EDSL_DATABASE_PATH=sqlite:///website/local/hiring-perspectives-v1/boston-cache.db PYTHONPATH=src .venv/bin/python website/local/perspective_demo.py boston-1990
```

Exported examples preserve exact input bindings, original rendered prompts,
request IDs, model configuration and emitted-answer log probabilities. Changes
to the source, candidate ordering, generation preset or hiring prompt cannot
display an unrelated result. Only the explicitly approved demonstration payload
is public; other research runs and local directories remain excluded.

## From decisions to data

Open <http://127.0.0.1:8765/#results> or continue scrolling. The final table shows
the selected newspaper and settings' two or four candidate evaluations: candidate, decision,
answer probability (%) and model. The percentage is `100 * exp(logprob)` for
the emitted Yes/No answer tokens—not calibrated confidence in correctness or
a probability of hiring. A `No` percentage describes that No answer; it is not
inverted into a Yes probability. It is not a self-reported confidence score.
Percentages display to one decimal, with `<0.1%`/`>99.9%` for extremes;
zero logprob displays `100.0%` at reported precision.
`Download CSV` retains full-precision `answer_probability_pct` and raw `logprob`,
numeric decisions, explanations, perspective/persona identity and stable
candidate/template/request/model IDs. Only the selected perspective is exported.

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
