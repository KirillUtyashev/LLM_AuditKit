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
    assert 'new URL("./data/newspapers.json", import.meta.url)' in app
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
    assert {"population-view", "population-connector", "candidate-options", "candidate-status", "populated-document"} <= set(page.ids)
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


def test_changed_resume_assets_have_matching_cache_versions():
    html = (WEBSITE / "index.html").read_text()
    app = (WEBSITE / "app.mjs").read_text()
    versions = [
        re.search(r'\./styles\.css\?v=([^"\s]+)', html).group(1),
        re.search(r'\./app\.mjs\?v=([^"\s]+)', html).group(1),
        re.search(r'\./lib\.mjs\?v=([^"\s]+)', app).group(1),
    ]
    assert len(set(versions)) == 1


def test_resume_posting_precedes_editable_prompt_with_adjacent_presets():
    html = (WEBSITE / "index.html").read_text()
    workspace = html.split('class="resume-workspace"', 1)[1].split("</section>", 1)[0]
    assert workspace.index('id="resume-source"') < workspace.index('class="prompt-editor"')
    editor = workspace.split('class="prompt-editor"', 1)[1]
    assert editor.index('id="prompt-variants"') < editor.index('<textarea id="variant-prompt"')
    assert 'for="variant-prompt"' in editor
    assert "readonly" not in editor and "Resume template" not in workspace
    assert 'rows="6"' in editor
    assert editor.index('<textarea id="variant-prompt"') < editor.index('id="generate-resume"')
    button = re.search(r'<button id="generate-resume"([^>]+)>Generate resume</button>', editor)
    assert button and "disabled" in button.group(1)  # Enabled only for a matching saved result.
    css = (WEBSITE / "styles.css").read_text()
    assert "max-width:860px" not in re.search(r"\.resume-workspace\s*\{([^}]+)\}", css).group(1)
    assert "max-width:380px" in re.search(r"\.resume-posting\s*\{([^}]+)\}", css).group(1)
    assert "min-height:200px" in re.search(r"#variant-prompt\s*\{([^}]+)\}", css).group(1)
    assert "justify-content:flex-start" in re.search(r"\.prompt-actions\s*\{([^}]+)\}", css).group(1)


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
    assert "Templates become candidates." in section
    assert "Different resumes. Ready for review." in section
    assert "Same qualifications" not in html
    assert "Synthetic examples." in section
    assert 'class="typeset-resume populated-resume"' in section
    assert 'role="group" aria-label="Synthetic candidates"' in section
    css = (WEBSITE / "styles.css").read_text()
    assert "@keyframes candidate-update" in css
    assert "margin:24px 0 24px" in re.search(r"#population-view\s*\{([^}]+)\}", css).group(1)
    assert "padding-bottom:24px" in re.search(r"\.typeset-resume\.populated-resume\s*\{([^}]+)\}", css).group(1)
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
    assert all(f'id="experiment-{field}"' in section for field in ["job", "candidate-1", "candidate-2"])
    assert "Saved model response" not in section and "Run experiment" in section
    assert 'id="experiment-result" aria-live="polite" hidden' in section


def test_final_table_hands_off_to_analysis_without_claiming_regression_results():
    html = (WEBSITE / "index.html").read_text()
    assert html.index('id="experiment-view"') < html.index('id="results-connector"') < html.index('id="results-view"')
    section = html.split('id="results-view"', 1)[1].split("</section>", 1)[0]
    assert "From decisions to data." in section and "Take it from here." in section
    assert section.count('scope="col"') == 5
    assert all(field in section for field in ["Resume preset", "Candidate", "Decision", "Logprob", "Model"])
    assert "not a calibrated hiring probability" in section
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
    assert len(paper["resumeDemo"]["variants"]) == 3
    assert all(len(variant["templates"]) == 2 for variant in paper["resumeDemo"]["variants"])
    assert len(paper["experimentDemo"]["examples"]) == 3
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
        assert len(paper["resumeDemo"]["variants"]) == len(paper["experimentDemo"]["examples"]) == 3
        for example in paper["experimentDemo"]["examples"]:
            assert example["jobPosting"] == records[example["jobId"]]["text"]
            assert paper["city"] in example["renderedSystemPrompt"]
            assert paper["date"][:4] in example["renderedSystemPrompt"]
        ad_ids.extend(records)
    assert len(ad_ids) == len(set(ad_ids))
    assert "ProQuest" in bundle["newspapers"][1]["sourceNotice"]


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
