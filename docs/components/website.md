# Static Pipeline Showcase

[Interaction diagram](../architecture/website.mmd)

The optional `website/` directory is an independent buildless HTML/CSS/JS
showcase, not a pipeline stage. It supports GitHub Pages repository prefixes.

## Scroll flow

The page presents the scan, then job rows, an optional resume prompt editor
and synthetic template-population, saved experiment and candidate-output examples
in normal vertical document flow.
The city/year selector remains above the original large newspaper preview.
Enlarging it displays the complete newspaper page. The jobs section below shows
at most three job previews in desktop columns (stacked on mobile), while search
always considers every available record for the selected newspaper.
Clearing search restores the explicit `featuredIds` order, falling back to the
bundle's order when absent. Counts show total matches and previews shown.
Reviewed crops preserve their complete aspect ratios at compact sizes.
The Boston bundle includes source-image areas for all 59 results.
Six regions were previously located manually. The remainder were matched from
saved Vision word coordinates and adjusted locally; `cropMethod` distinguishes
these approximate previews. Hover text and alt text identify approximate areas,
which may contain neighboring text or omit fragments when extraction merged
ads or OCR reading order mixed columns. This does not establish verified per-ad
source attribution or change the OCR-stage contract. Curation remains local;
the browser does no inference or source matching. Records without a usable
source area still fall back to labeled text previews.
Clicking any preview opens its full extracted text in an accessible native dialog;
Close or Escape returns to the image grid. There are no visible per-ad titles
or body text in the grid, and no selector or carousel. The original newspaper
preview retains its separate full-page enlargement and zoom.
One centered continuous line connects the scan to the jobs, without provider
icons, tool names or intermediate captions. The line is hidden from assistive
technology. Matching connectors continue the optional resume/population flow.
No inference runs while scrolling.
The jobs section has search, approximate source images and full extracted text
on demand. The sections remain visible, without Scan/Jobs navigation or a
separate date caption. Scroll position updates the stage bookmark.
IntersectionObserver progressively reveals content, with visible defaults when
unsupported, keyboard-focus visibility and a reduced-motion fallback.
Paper changes reset search; browser history restores paper/stage.
An empty search result clears the cards and disables CSV export.

CSV export includes all matching records, not just the three previews, preserving source-region IDs, source
text when available, city/date/page provenance and review flags. Formula-like
prefixes are escaped for spreadsheet safety. Display labels are not IDs.
Source/transcription notes remain in the bundle, and raw OCR also remains in
CSV exports. They are not shown in an on-page accordion.

## Resume prompt editor

A third scroll section appears only when the selected paper includes a valid
`resumeDemo` bound to an existing job ID. The local Administrative Assistant
example, approved for public sharing, has three prompt presets: Strong fit, Transferable skills, and More
detail. The source job image appears on the left, preserving its crop aspect
ratio; clicking enlarges it. Jobs without a source region show extracted text
instead. On the right, the style buttons sit directly above a labeled editable
textarea containing the exact variant-instruction paragraph. Shared instructions
are omitted from the editor. A shorter editor leaves room for a left-aligned
`Generate resume` button underneath. For an unchanged preset with saved output,
it opens a native dialog labeled `Saved resume example`, with two small template
buttons for the pair generated jointly for this preset (`N=2`). Each template
describes a distinct fictional applicant. The resume is typeset
as a document: serif text, centered contact placeholders, small-cap section
headings with thin rules, paragraphs and real bullet lists. No LaTeX compiler,
external font service, text-card border or new generation request is involved.
Close or Escape returns to the prompt editor. The saved prose is not rewritten.
Canonical placeholders such as `{{name}}` and `{{address}}` have a subtle
highlight and dashed underline. Hover or keyboard focus explains that they are
intentional and invite the visitor to close the preview and scroll down to see
candidate details filled in. Each
focusable placeholder has an associated tooltip; Escape dismisses that note
without closing the resume, and focus/hover can reveal it again. This does not
submit a generation request or modify the saved template.
Edited prompts and presets without saved output disable the button with an
explanatory tooltip rather than presenting an old result as newly generated.
The two columns stack on mobile. The UI uses plain `resume`, without accents.
Edits are kept only in page memory, independently for each paper/job/style,
including intentionally blank drafts. Switching styles or visiting another
paper and back preserves drafts; reloading the page resets them.

Generation was performed offline through the existing `TemplateGenerator`,
shared inference adapter and structured parts contract. The local bundle keeps
the actual request IDs, fingerprints and model identity; prompt files, YAML
configs and CSV checkpoints remain ignored local artifacts.
Editing and switching variants perform no fetch or inference and do not change
the saved prompts or outputs. Earlier outputs are previewed only for their exact
original prompt, not as results of editing. A valid prompt-only demo does not
require generated outputs. Source binding prevents using another job's image
or draft. Papers without a matching demo hide this section and its connector,
clearing the visible editor, image and saved-document dialog.
The `#resumes` bookmark is accepted only when such a demo exists.

## Synthetic template population

Below the editor, `Templates become candidates.` shows one typeset
resume and two small candidate buttons. The caption is `Different resumes.
Ready for review.` and the examples are explicitly labeled synthetic.
The two fixed profiles have stable synthetic IDs and deliberately illustrative
names/addresses; they are not paper assignments, sampled demographic groups,
or a researcher-defined audit design.

The section uses the currently selected unchanged preset's two distinct saved
templates. Explicit candidate-ID to template-ID assignments bind each candidate
to their own generated background; content-derived template IDs are not display
positions. Missing, duplicate, reused or incompatible mappings hide population
rather than copying one template for both candidates. Single-template artifacts
can still be previewed but cannot drive this paired example.
Only exact `{{name}}` and `{{address}}` tokens are replaced within each assigned
template; that template's prose stays unchanged. Switching candidates therefore
changes the background as well as personal details. It is not a same-qualification
identity comparison, and no such claim is shown.
A brief highlight marks changed values when switching candidates, with no
animation under reduced-motion preferences. Buttons expose pressed state, and
a concise live status announces the selected candidate without rereading the
entire resume. The same document renderer is used for the template and filled
example; no extra text-card border or new API request is introduced.

Missing output, unsupported placeholders, or an edited prompt hide this section
and its connector and clear stale content. Choosing a valid saved preset brings
it back. `#population` opens this section only when the paper's default preset
supports the fixed examples; scrolling keeps the bookmark current. Hiding an
active population section falls back to the resume section or archive bookmark.
Paper changes reset candidate selection. No candidate data is persisted.

## Saved experiment evaluation

`How does the model decide?` follows population with the same continuous-line
connector. Small input-review buttons open the exact job text and both typeset
candidate resumes. A labeled editable hiring-prompt window and one `Run
experiment` button sit below. Only the fixed model name is shown beside it.
Clicking reveals the two saved interview decisions and the original explanation
as plain text, not a reconstructed or invented answer. The model and button
tooltips explain that responses are previously recorded; no saved-run suffix or
response heading is shown. There is no simulated waiting or browser API call.

The Boston examples were rerun for each of the three paired resume presets
through `ExperimentRunner` and the shared EDSL adapter, using
`gpt-4o-2024-08-06`, temperature 0, and token log probabilities. The existing
runner validated `Yes`/`No` decisions and their emitted-token log probabilities.
This is illustrative, not an estimate of bias or a reproduction of the paper's
assignments. Raw checkpoints,
YAML, persona/system text and full rendered prompts stay in the ignored local
experiment-pairs directory; earlier one-template runs remain untouched under
experiment-demo. Saved exports retain request/scenario/experiment IDs,
model configuration, exact source text, candidate/template IDs, ordered inputs and logprobs.

An example is available only when its job ID/text, resume-generation prompt,
templates and their assignments, ordered candidate IDs/names/addresses/resumes, hiring prompt, complete
decisions and provenance match. Prompt edits disable `Run experiment` and clear
the previous result; they are not submitted. Generation edits, changed source
data, missing results or a paper/preset change cannot reuse a stale response.
Hiring-prompt drafts are scoped to paper/job and survive preset switches in page
memory only. `#experiment` and scroll bookmarks follow the same optional-stage
rules as population. The published Boston bundle includes these examples;
papers without experiment payloads hide this section and connector.

## Final candidate-output table

`From decisions to data.` ends the flow with six candidate-level rows from the
three validated preset evaluations. The visible columns are resume preset,
candidate, Yes/No decision, emitted-answer logprob and model. Logprob is the
natural log probability of the emitted answer, not a calibrated probability of
hiring. It is rounded to four significant digits for display; hovering retains
the exact numeric value, and CSV export preserves full precision.

The download also includes numeric `decision` (`1`/`0`), variant/candidate/template
IDs, scenario/request/experiment IDs, model configuration/provider, source ad ID,
address and the run-level explanation. `(request_id, candidate_id)` distinguishes
candidate rows across presets. Values come from validated saved results, never
from a new model call or fabricated probabilities. Formula-like string cells
are escaped for spreadsheet safety without turning negative numeric logprobs
into text. This is a simplified candidate-level analysis view, not the native
wide experiment checkpoint or an R-preparation export: no `audit_id`, substantive
covariates or regression outputs are inferred.

All configured preset examples must validate; otherwise the final table and
connector are hidden rather than silently showing a partial dataset. Editing
the active generation/hiring prompt also hides and clears the table and disables
download. The table describes the original saved presets, not unsent drafts.
`#results` bookmarks this section; papers without completed examples do
not expose it. A scrollable semantic table supports smaller screens.

The closing `Take it from here.` message links to the GitHub repository and invites
researchers to scale to thousands of applications and take the data into their
own analysis. The demo does not manufacture a large dataset or draw statistical
conclusions from the six examples. Regression remains a separate researcher step.

Beyond fixed synthetic substitution and saved-output playback, no uploads,
live browser OCR/generation, research sampling, live experiments or regression
are implemented.
These are illustrative prompt presets and candidates, not a
validated research comparison or hiring recommendation.

## Data boundary

The default `website/data/newspapers.json` and Boston image under
`website/assets/` are the maintainer-approved public display copy of the full
Boston demo: 59 saved OCR ads, six fictional resume templates and three real
saved model evaluations. Public sharing was explicitly approved on 19 November
2026. Third-party newspaper content is not relicensed as MIT, and the source
date remains filename-inferred. The earlier public archive excerpt bundle is
retained as `website/data/archive-newspapers.json` for tests and source credits;
it is not the deployed default.

On loopback hosts only, an optional ignored `website/local/newspapers.json`
can replace the public bundle for local research previews. A missing file (404)
falls back to the approved public Boston bundle; malformed data and other failures
display an error instead of silently substituting sources. Public hosts never request
the local bundle. The Boston example uses a 1990 scan and all 59
unedited results from a saved AuditKit OCR run. Administrative Assistant,
Operations Staff, and Travel Reservationist remain the three featured images.
All records now have manually located or approximate source-image areas.
Full-page Vision text
is exported as full-page raw text, not a per-ad excerpt.
Crop locations remain manually located or approximate, and the filename-derived date is documented.
The original manual transcriptions are retained locally for comparison.

Unapproved research data and credentials must not enter the Pages artifact.
Only the approved display copy is tracked; the workflow rejects `website/local`
and publishes only the static folder from main or the explicit showcase branch.
This allows a collaborator preview without merging unreviewed code into main.
Local preview commands do not deploy. See the [website README](../../website/README.md)
for commands and source credits.

## Implementation and checks

`app.mjs` manages DOM state with text APIs, never HTML evaluation.
`lib.mjs` provides search, selection, CSV safety, crop coordinates, date/URL
handling and bundle selection. No third-party browser scripts or analytics.
Native controls, focus states, a skip link, modal dialog, responsive layout,
reduced-motion support and a live result count support keyboard inspection.

Offline JS tests cover the pure helpers and mocked DOM interactions; Python
tests check asset integrity, target IDs and the publication boundary.
