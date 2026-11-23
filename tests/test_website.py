"""Static assets and offline website checks, independent of live archive APIs."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        for name in ("src", "href"):
            value = attrs.get(name, "")
            if value.startswith("./"):
                self.paths.append(value)


def test_website_local_references_and_accessible_targets():
    page = PageLinks()
    page.feed((WEBSITE / "index.html").read_text())
    assert len(page.ids) == len(set(page.ids))
    assert {"main", "archive-view", "data-view", "image-dialog", "job-cards", "paper-select", "open-scan", "scan-image", "enlarged-crop", "job-dialog", "job-full-text"} <= set(page.ids)
    for target in page.paths:
        assert (WEBSITE / urlsplit(target).path).exists(), target
    app = (WEBSITE / "app.mjs").read_text()
    assert set(re.findall(r'\$\("([a-z0-9-]+)"\)', app)) <= set(page.ids)
    assert re.search(r'new URL\("\./data/newspapers\.json\?v=[^"\s]+", import\.meta\.url\)', app)
    assert "innerHTML" not in app
    assert "eval(" not in app
    assert "prefers-reduced-motion" in (WEBSITE / "styles.css").read_text()
    assert "preview-note" not in page.ids
    assert "next-button" not in page.ids and "back-button" not in page.ids
    assert "scan-caption" not in page.ids
    assert "data-step" not in (WEBSITE / "index.html").read_text()
    assert "transcription-note" not in page.ids and "raw-text" not in page.ids
    assert "<details" not in (WEBSITE / "index.html").read_text()
    assert {"resume-view", "prompt-variants", "variant-prompt", "resume-source", "resume-source-image"} <= set(page.ids)
    assert "resume-output" not in page.ids
    assert {"population-view", "population-connector", "reset-candidates", "candidate-status", "populated-document", "candidate-field-dialog"} <= set(page.ids)
    assert {"experiment-view", "experiment-connector", "experiment-prompt", "run-experiment", "experiment-result", "experiment-explanation"} <= set(page.ids)
    assert {"results-view", "results-connector", "results-heading", "results-count", "final-output-rows", "download-results"} <= set(page.ids)
    assert "Prompt highlights" not in (WEBSITE / "index.html").read_text()
    assert "résumé" not in (WEBSITE / "index.html").read_text()


def test_original_newspaper_is_preserved_and_jobs_use_three_columns():
    html = (WEBSITE / "index.html").read_text()
    assert 'id="open-scan"' in html and 'id="scan-image"' in html
    assert 'id="scan-examples"' not in html and 'id="record-list"' not in html
    css = (WEBSITE / "styles.css").read_text()
    rule = re.search(r"\.jobs-view\s*\{([^}]+)\}", css).group(1)
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in rule
    assert "page-preview" in css and ".job-button" not in css


def test_extraction_and_generation_labels_identify_their_inputs_and_outputs():
    html = (WEBSITE / "index.html").read_text()
    scan = html.split('id="archive-view"', 1)[1].split("</section>", 1)[0]
    jobs = html.split('id="data-view"', 1)[1].split("</section>", 1)[0]
    assert '<span>Input</span><span aria-hidden="true">·</span>Newspaper scan' in scan
    assert '<span>Output</span><span aria-hidden="true">·</span>Extracted text' in jobs
    assert scan.index('class="artifact-label"') < scan.index('id="open-scan"')
    assert jobs.index('class="artifact-label"') < jobs.index('id="job-cards"')
    resumes = html.split('id="resume-view"', 1)[1].split("</section>", 1)[0]
    assert '<span>Input</span><span aria-hidden="true">·</span>Job posting + prompt' in resumes
    assert '<span>Output</span><span aria-hidden="true">·</span>Resume templates' in resumes
    assert html.count('class="artifact-label"') == 6
    assert "Advertisements from the page." not in jobs
    css = (WEBSITE / "styles.css").read_text()
    assert "flex-wrap:wrap" in re.search(r"\.artifact-label\s*\{([^}]+)\}", css).group(1)


def test_job_output_explains_text_and_context_images_without_changing_csv_export():
    html = (WEBSITE / "index.html").read_text()
    jobs = html.split('id="data-view"', 1)[1].split("</section>", 1)[0]
    note = "Each posting is stored as text. Scan excerpts are shown for context—click one to read the extracted text."
    assert note in jobs
    assert jobs.index(note) < jobs.index('id="job-cards"')
    button = re.search(r'<button id="download-button"([^>]+)>([^<]+)</button>', jobs)
    assert button.group(2) == "Download job text"
    assert "as CSV" in button.group(1) and "all matching" in button.group(1)
    assert 'id="job-cards" class="jobs-view"' in jobs
    # The later candidate-results download keeps its own CSV label.
    assert '>Download CSV</button>' in html.split('id="results-view"', 1)[1]


def test_changed_resume_assets_have_matching_cache_versions():
    html = (WEBSITE / "index.html").read_text()
    app = (WEBSITE / "app.mjs").read_text()
    versions = [
        re.search(r'\./styles\.css\?v=([^"\s]+)', html).group(1),
        re.search(r'\./app\.mjs\?v=([^"\s]+)', html).group(1),
        re.search(r'\./lib\.mjs\?v=([^"\s]+)', app).group(1),
        re.search(r'\./data/newspapers\.json\?v=([^"\s]+)', app).group(1),
    ]
    assert len(set(versions)) == 1


def test_resume_posting_precedes_editable_prompt_with_adjacent_presets():
    html = (WEBSITE / "index.html").read_text()
    workspace = html.split('class="resume-workspace"', 1)[1].split("</section>", 1)[0]
    assert workspace.index('id="resume-source"') < workspace.index('class="prompt-editor"')
    editor = workspace.split('class="prompt-editor"', 1)[1]
    assert editor.index('id="prompt-variants"') < editor.index('<textarea id="variant-prompt"')
    assert 'for="variant-prompt"' in editor
    assert "readonly" not in editor
    assert 'class="prompt-summary-label" for="variant-prompt">Prompt summary' in editor
    assert 'rows="6"' in editor
    assert editor.index('<textarea id="variant-prompt"') < editor.index('id="generate-resume"')
    button = re.search(r'<button id="generate-resume"([^>]+)>Inspect templates</button>', editor)
    assert button and "disabled" in button.group(1)  # Enabled only for a matching saved result.
    css = (WEBSITE / "styles.css").read_text()
    assert "max-width:860px" not in re.search(r"\.resume-workspace\s*\{([^}]+)\}", css).group(1)
    assert "max-width:380px" in re.search(r"\.resume-posting\s*\{([^}]+)\}", css).group(1)
    assert "min-height:200px" in re.search(r"#variant-prompt\s*\{([^}]+)\}", css).group(1)
    assert "justify-content:flex-start" in re.search(r"\.prompt-actions\s*\{([^}]+)\}", css).group(1)


def test_prompt_controls_are_inline_accessible_and_distinct_from_population_links():
    html = (WEBSITE / "index.html").read_text()
    section = html.split('id="interactive-prompt"', 1)[1].split('<textarea id="variant-prompt"', 1)[0]
    assert 'role="group" aria-labelledby="prompt-summary-label"' in section
    assert all(f'id="{name}"' in section for name in ("resume-count", "job-skill-count", "experience-level"))
    assert 'value="2">2 resumes' in section and 'value="4">4 resumes' in section
    assert 'value="2">2 job-related skills' in section and 'value="4">4 job-related skills' in section
    assert "Number of resume templates" in section and "Number of job-related skills" in section
    assert 'aria-controls="population-help"' in section
    assert "Filled in during template population" in section
    assert "Counts and experience guide the prompt" not in section
    assert 'class="prompt-guidance"' not in section


def test_saved_resume_uses_a_typeset_document_not_a_text_box():
    html = (WEBSITE / "index.html").read_text()
    assert '<dialog id="resume-dialog" aria-labelledby="resume-dialog-title"' in html
    assert "Saved resume example" in html
    assert 'class="typeset-resume"' in html and 'id="close-resume-dialog"' in html
    css = (WEBSITE / "styles.css").read_text()
    document = re.search(r"\.typeset-resume\s*\{([^}]+)\}", css).group(1)
    assert "Palatino" in document and "border:" not in document
    assert "font-variant-caps:all-small-caps" in css
    assert ".resume-placeholder:hover .placeholder-tooltip" in css
    assert ".resume-placeholder:focus .placeholder-tooltip" in css
    assert ".resume-placeholder[data-dismissed=true] .placeholder-tooltip" in css


def test_population_section_continues_the_scroll_flow_with_synthetic_candidates():
    html = (WEBSITE / "index.html").read_text()
    assert html.index('id="resume-view"') < html.index('id="population-connector"') < html.index('id="population-view"')
    section = html.split('id="population-view"', 1)[1].split("</section>", 1)[0]
    assert "Templates become applications." in section
    assert "Click highlighted details to change them." not in section
    assert "Same qualifications" not in html
    assert "Synthetic examples." not in section
    assert 'class="synthetic-note"' not in section
    assert 'id="population-caption" class="population-caption" hidden></p>' in section
    assert 'class="resume-grid"' in section
    assert 'role="group" aria-label="Ready applications"' in section
    assert "View full resume" in (WEBSITE / "app.mjs").read_text()
    assert 'id="candidate-field-dialog" aria-labelledby="candidate-field-title"' in html
    assert 'aria-label="Replacement presets"' in html
    css = (WEBSITE / "styles.css").read_text()
    assert "@keyframes candidate-update" in css
    assert "margin:24px 0 24px" in re.search(r"#population-view\s*\{([^}]+)\}", css).group(1)
    assert "padding-bottom:24px" in re.search(r"\.typeset-resume\.populated-resume\s*\{([^}]+)\}", css).group(1)
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in re.search(r"\.resume-grid\s*\{([^}]+)\}", css).group(1)
    # Shorter documents leave blank space below their text, rather than ending
    # their sheet border above the neighboring resume. No fixed/clipped height.
    grid = re.search(r"\.resume-grid\s*\{([^}]+)\}", css).group(1)
    sheet = re.search(r"\.resume-sheet\s*\{([^}]+)\}", css).group(1)
    assert "align-items:stretch" in grid
    assert not re.search(r"(?:^|;)\s*(?:max-)?height\s*:", sheet)
    assert "grid-template-columns:1fr" in css.split("@media(max-width:700px)", 1)[1]
    assert "animation:none!important" in css.split("@media(prefers-reduced-motion:reduce)", 1)[1]


def test_scan_connects_to_jobs_with_one_continuous_line_without_icons_or_captions():
    html = (WEBSITE / "index.html").read_text()
    between = html.split('id="archive-view"', 1)[1].split('id="data-view"', 1)[0]
    assert "processing-flow" not in html and "processing-tool" not in html
    assert "google-vision.svg" not in html and "openai.svg" not in html
    assert 'class="flow-connector" aria-hidden="true"' in between
    assert between.count('class="flow-line"') == 1
    css = (WEBSITE / "styles.css").read_text()
    connector = re.search(r"\.flow-connector\s*\{([^}]+)\}", css).group(1)
    assert "align-items:center" in connector
    assert "flex-direction:column" in connector
    assert "gap:" not in connector
    line = re.search(r"\.flow-line\s*\{([^}]+)\}", css).group(1)
    assert "height:84px" in line


def test_experiment_section_has_editable_prompt_inputs_and_explicit_saved_response():
    html = (WEBSITE / "index.html").read_text()
    assert html.index('id="population-view"') < html.index('id="experiment-connector"') < html.index('id="experiment-view"')
    section = html.split('id="experiment-view"', 1)[1].split("</section>", 1)[0]
    assert "How does the model decide?" in section
    assert '<textarea id="experiment-prompt"' in section and 'for="experiment-prompt"' in section
    assert '<label class="prompt-summary-label" for="experiment-prompt">Prompt summary</label>' in section
    assert '<span>Input</span><span aria-hidden="true">·</span>Job posting + resumes' in section
    assert '<span>Output</span><span aria-hidden="true">·</span>Interview decisions' in section
    assert section.index('Job posting + resumes') < section.index('id="experiment-perspectives"')
    assert section.index('id="experiment-result"') < section.index('Interview decisions') < section.index('id="experiment-decisions"')
    assert "Review inputs" not in section
    assert 'id="experiment-job"' not in section and 'id="experiment-candidates"' not in section
    assert "Saved model response" not in section and "Inspect model decisions" in section
    assert 'id="experiment-perspectives"' in section and 'aria-label="Hiring perspective"' in section
    assert 'id="experiment-result" aria-live="polite" hidden' in section


def test_final_table_hands_off_to_analysis_without_claiming_regression_results():
    html = (WEBSITE / "index.html").read_text()
    assert html.index('id="experiment-view"') < html.index('id="results-connector"') < html.index('id="results-view"')
    section = html.split('id="results-view"', 1)[1].split("</section>", 1)[0]
    assert "From decisions to data." in section and "Take it from here." in section
    assert section.count('scope="col"') == 5
    assert all(field in section for field in ["Resume prompt", "Candidate", "Decision", "Answer probability", "Model"])
    assert ">Logprob<" not in section
    assert "not calibrated confidence that the decision is correct" in section
    assert "CSV retains raw log probabilities" in section
    assert "thousands of applications" in section and "own analysis" in section
    assert "Download CSV" in section
    assert '<a href="https://github.com/KirillUtyashev/LLM_AuditKit">Run your own audit</a>' in section
    assert "overflow-x:auto" in (WEBSITE / "styles.css").read_text()


def test_public_archive_bundle_has_local_images_and_no_research_payloads():
    bundle = json.loads((WEBSITE / "data/archive-newspapers.json").read_text())
    assert bundle["schemaVersion"] == 1
    assert "not AuditKit OCR" in bundle["transcriptionPolicy"]
    ids = []
    for paper in bundle["newspapers"]:
        assert paper["sourceUrl"].startswith(("https://oregonnews.uoregon.edu/", "https://nebnewspapers.unl.edu/"))
        assert paper["imageSrc"].startswith("./assets/")
        for relative in {paper["imageSrc"], *(record["cropSrc"] for record in paper["records"])}:
            data = (WEBSITE / relative).read_bytes()
            assert data[:2] == b"\xff\xd8", relative
            assert 1000 < len(data) < 4_000_000
        for record in paper["records"]:
            ids.append(record["id"])
            assert record["reviewRequired"] is True
            assert not {"candidate_id", "resume", "picks", "generated_response"} & record.keys()
    assert len(ids) == len(set(ids)) == 6


def test_public_boston_scan_and_demo_are_explicitly_approved_and_self_contained():
    text = (WEBSITE / "data/newspapers.json").read_text()
    bundle = json.loads(text)
    assert bundle["publication"]["maintainerApproved"] is True
    assert bundle["mode"] == "saved-auditkit-pipeline-showcase"
    paper = bundle["newspapers"][0]
    assert paper["city"] == "Boston" and paper["date"].startswith("1990")
    assert len(paper["records"]) == 59
    assert paper["imageSrc"] == "./assets/boston-1990-08-05.jpg"
    assert (WEBSITE / paper["imageSrc"]).read_bytes()[:2] == b"\xff\xd8"
    assert len(paper["resumeDemo"]["variants"]) == 8
    assert all(len(variant["templates"]) == variant["settings"]["resumes"] for variant in paper["resumeDemo"]["variants"])
    assert len(paper["experimentDemo"]["examples"]) == 16
    assert not re.search(r"/Users/|/var/folders/|\.\/local/|BEGIN [A-Z ]*PRIVATE KEY|AIza[0-9A-Za-z_-]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{25,}", text)


def test_additional_papers_have_their_own_scans_sources_and_completed_runs():
    bundle = json.loads((WEBSITE / "data/newspapers.json").read_text())
    assert [(paper["city"], paper["date"][:4]) for paper in bundle["newspapers"]] == [
        ("Boston", "1990"), ("Chicago", "1970"), ("Birmingham", "2000")]
    ad_ids = []
    for paper in bundle["newspapers"]:
        assert (WEBSITE / paper["imageSrc"]).read_bytes()[:2] == b"\xff\xd8"
        assert len(set(paper["featuredIds"])) == 3
        records = {record["id"]: record for record in paper["records"]}
        assert all(records[ad_id].get("bbox") for ad_id in paper["featuredIds"])
        assert len(paper["resumeDemo"]["variants"]) == 8
        assert len(paper["experimentDemo"]["examples"]) == 16
        variant = paper["resumeDemo"]["variants"][0]
        assert variant["promptSource"]["function"] == {"Boston": "prompt_1990", "Chicago": "prompt_1970", "Birmingham": "prompt_2001"}[paper["city"]]
        assert variant["promptSource"]["revision"] == "c9391854ea55806ec252625cd2f48fb9edb156cd"
        assert len(variant["prompt"]) > len(variant["promptSummary"])
        assert paper["city"] in variant["promptSummary"] and paper["date"][:4] in variant["promptSummary"]
        assert records[paper["resumeDemo"]["jobId"]]["text"] in variant["prompt"]
        for example in paper["experimentDemo"]["examples"]:
            variant = next(item for item in paper["resumeDemo"]["variants"] if item["id"] == example["variantId"])
            assert example["jobPosting"] == records[example["jobId"]]["text"]
            assert paper["city"] in example["renderedSystemPrompt"]
            assert paper["date"][:4] in example["renderedSystemPrompt"]
            assert example["generationPrompt"] == variant["prompt"]
            assert example["generationSystemPrompt"] == variant["systemPrompt"]
        ad_ids.extend(records)
    assert len(ad_ids) == len(set(ad_ids))
    assert "ProQuest" in bundle["newspapers"][1]["sourceNotice"]


def test_saved_skill_counts_and_all_inline_combinations_are_inspected():
    bundle = json.loads((WEBSITE / "data/newspapers.json").read_text())
    for paper in bundle["newspapers"]:
        variants = paper["resumeDemo"]["variants"]
        assert paper["resumeDemo"]["inlineControls"] is True
        assert {(v["settings"]["resumes"], v["settings"]["jobSkills"], v["settings"]["experience"]) for v in variants} == {
            (n, skills, experience) for n in (2, 4) for skills in (2, 4) for experience in ("entry-level", "experienced")}
        for variant in variants:
            assert variant["inspectedJobSkillCount"] is True
            assert len(variant["assignments"]) == variant["settings"]["resumes"]
            for template in variant["templates"]:
                section = re.split(r"(?m)^JOB[- ]RELATED SKILLS:?\s*$", template["text"])[1]
                assert len(re.findall(r"(?m)^- ", section)) == variant["settings"]["jobSkills"]


def test_saved_school_and_dates_are_controlled_fields_with_exact_populated_inputs():
    bundle = json.loads((WEBSITE / "data/newspapers.json").read_text())
    for paper in bundle["newspapers"]:
        school = "high_school" if paper["city"] == "Chicago" else "university"
        fields = {"name", "address", school, "education_end_year", "work_start_month", "work_start_year"}
        if paper["city"] == "Chicago":
            fields |= {"work_end_month", "work_end_year"}
        else:
            fields |= {"education_start_year", "work_end"}
        if paper["city"] == "Birmingham":
            fields |= {"school_work_start_month", "school_work_start_year", "school_work_end_month", "school_work_end_year"}
        for variant in paper["resumeDemo"]["variants"]:
            assert set(variant["placeholderFields"]) == fields
            templates = {template["id"]: template["text"] for template in variant["templates"]}
            for text in templates.values():
                assert set(re.findall(r"\{\{([a-z_]+)\}\}", text)) == fields
            example = next(e for e in paper["experimentDemo"]["examples"] if e["variantId"] == variant["id"])
            assert len(example["candidates"]) == len(example["decisions"]) == variant["settings"]["resumes"]
            assert example["experimentId"].endswith(f"{example['perspectiveId']}-{variant['settings']['resumes']}-v1")
            perspective = next(p for p in paper["experimentDemo"]["perspectives"] if p["id"] == example["perspectiveId"])
            assert example["prompt"] == perspective["prompts"][str(variant["settings"]["resumes"])]
            pools = variant["populationPools"]
            assert len(pools["addresses"]) == 4
            assert variant["populationSource"]["codePath"] == "jobs_to_experiment/experiment_setup.py"
            assert variant["populationSource"]["revision"] == "c9391854ea55806ec252625cd2f48fb9edb156cd"
            assert variant["generationProjection"]["kind"] == "controlled-date-labels"
            for assignment in variant["assignments"]:
                values = assignment["values"]
                assert set(values) == fields - {"name", "address"}
                assert all(isinstance(value, str) and value.strip() for value in values.values())
                candidate = next(c for c in example["candidates"] if c["id"] == assignment["candidateId"])
                assert candidate["values"] == values
                assert candidate["address"] == assignment["address"] in pools["addresses"]
                assert values[school] in pools["schools"]
                dates = {k: v for k, v in values.items() if k == "work_end" or k.endswith(("_year", "_month"))}
                assert dates in [preset["values"] for preset in pools["dates"]]
                if paper["city"] != "Chicago":
                    assert values["work_end"] == "Present"
                populated = re.sub(r"\{\{([a-z_]+)\}\}",
                                   lambda match: {**values, "name": candidate["name"], "address": candidate["address"]}[match[1]],
                                   templates[assignment["templateId"]])
                assert candidate["resume"] == populated
                assert "{{" not in populated
                assert populated in example["renderedUserPrompt"]


def test_published_replacements_use_original_paper_institution_pools_not_fictional_schools():
    bundle = json.loads((WEBSITE / "data/newspapers.json").read_text())
    schools = {
        "Boston": {"University of Lowell", "Southeastern Massachusetts University"},
        "Chicago": {"Gage Park High School", "Jones Commercial High School"},
        "Birmingham": {"University of Montevallo", "University of Alabama at Birmingham"},
    }
    for paper in bundle["newspapers"]:
        for variant in paper["resumeDemo"]["variants"]:
            assert set(variant["populationPools"]["schools"]) == schools[paper["city"]]
            assert all(not any(word in a for word in ("Example", "Sample", "Practice", "Demo")) for a in variant["populationPools"]["addresses"])


def test_both_hiring_perspectives_have_independent_complete_saved_runs():
    bundle = json.loads((WEBSITE / "data/newspapers.json").read_text())
    request_ids = set()
    observations = 0
    for paper in bundle["newspapers"]:
        demo = paper["experimentDemo"]
        assert [(p["id"], p["label"]) for p in demo["perspectives"]] == [("role-play", "Role-play"), ("historian", "Historian")]
        for perspective in demo["perspectives"]:
            for n in ("2", "4"):
                summary = perspective["summaries"][n]
                assert not re.search(r"\bfictional\b|JSON", summary, re.I)
                assert "Answer Yes or No" in summary
                assert "both applicants" in summary if n == "2" else "four applicants" in summary
                assert "JSON" in perspective["prompts"][n]
                assert "fictional" in perspective["prompts"][n]
        assert {(e["variantId"], e["perspectiveId"]) for e in demo["examples"]} == {
            (v["id"], p["id"]) for v in paper["resumeDemo"]["variants"] for p in demo["perspectives"]}
        for example in demo["examples"]:
            perspective = next(p for p in demo["perspectives"] if p["id"] == example["perspectiveId"])
            n = len(example["candidates"])
            assert example["prompt"] == perspective["prompts"][str(n)]
            assert example["personaId"] == perspective["personaId"]
            assert example["personaTrait"] == perspective["trait"]
            assert example["personaInstruction"] == perspective["instruction"]
            assert perspective["trait"] in example["renderedSystemPrompt"]
            assert perspective["instruction"] in example["renderedSystemPrompt"]
            assert example["prompt"] in example["renderedUserPrompt"]
            assert len(example["decisions"]) == n
            assert example["requestId"] not in request_ids
            request_ids.add(example["requestId"])
            observations += n
    assert len(request_ids) == 48
    assert observations == 144


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is required for the offline website JS tests")
def test_offline_javascript_website_helpers():
    result = subprocess.run(["node", "--test", *map(str, sorted((ROOT / "tests/website").glob("*.test.mjs")))],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_pages_publishing_is_scoped_to_the_static_folder():
    text = (ROOT / ".github/workflows/pages.yml").read_text()
    assert "path: website" in text
    assert "refs/heads/main" in text
    assert "refs/heads/feat/37-static-pipeline-showcase" in text
    assert "test ! -e website/local" in text
    assert "pull_request_target" not in text
    assert "OPENAI_API_KEY" not in text and "GOOGLE_API_KEY" not in text


def test_local_research_scans_are_ignored_and_not_tracked():
    ignored = subprocess.run(["git", "check-ignore", "website/local/example.jpg"],
                             cwd=ROOT, capture_output=True, text=True)
    assert ignored.returncode == 0
    tracked = subprocess.run(["git", "ls-files", "website/local"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    assert not tracked.stdout.strip()
