import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {CSV_COLUMNS, chooseRecord, csvForRecords, filterRecords, formatDate, normalizedBox, stateFromUrl, cropStyle, loadBundle, jobPreview, resumeDemo, savedResumeVariant, resumePromptText, inlineResumeVariant, resumeBlocks, resumeTextParts, DEMO_CANDIDATES, populateResumeExample, populationExamples, resumeTemplates, experimentExample, finalOutputRows, resultCsv, RESULT_COLUMNS} from "../../website/lib.mjs";
import {syntheticExperiment, pairedVariant, inlineVariants} from "./experiment-fixture.mjs";

const bundle = JSON.parse(await readFile(new URL("../../website/data/archive-newspapers.json", import.meta.url), "utf8"));
const papers = bundle.newspapers;

test("published papers each expose their own full pipeline without local assets", async () => {
  const published = JSON.parse(await readFile(new URL("../../website/data/newspapers.json", import.meta.url), "utf8"));
  assert.equal(published.mode, "saved-auditkit-pipeline-showcase");
  assert.equal(published.publication.maintainerApproved, true);
  assert.deepEqual(published.newspapers.map(paper => [paper.city, paper.date.slice(0, 4)]),
    [["Boston", "1990"], ["Chicago", "1970"], ["Birmingham", "2000"]]);
  assert.equal(published.newspapers[0].records.length, 59);
  const jobIds = new Set(), requestIds = new Set(), templateIds = new Set();
  for (const paper of published.newspapers) {
    assert.equal(finalOutputRows(paper).length, 16);
    const url = `https://example.org/LLM_AuditKit/?paper=${paper.id}#results`;
    assert.deepEqual(stateFromUrl(url, published.newspapers), {paperId: paper.id, step: "results"});
    assert.ok(paper.imageSrc.startsWith("./assets/"));
    assert.equal(paper.featuredIds.length, 3);
    for (const record of paper.records) if (record.bbox) normalizedBox(paper, record);
    const demo = resumeDemo(paper);
    assert.equal(demo.inlineControls, true);
    assert.equal(demo.variants.length, 8);
    assert.ok(!jobIds.has(demo.jobId)); jobIds.add(demo.jobId);
    assert.ok(paper.featuredIds.includes(demo.jobId));
    for (const variant of demo.variants) {
      assert.equal(resumeTemplates(variant).length, variant.settings.resumes);
      assert.equal(finalOutputRows(paper, variant.id).length, 2);
      assert.ok(variant.prompt.length > resumePromptText(variant).length);
      const example = experimentExample(paper, variant);
      assert.ok(example);
      assert.ok(!requestIds.has(example.requestId)); requestIds.add(example.requestId);
      assert.ok(example.renderedSystemPrompt.includes(paper.city));
      assert.ok(example.renderedSystemPrompt.includes(paper.date.slice(0, 4)));
      for (const template of variant.templates) {
        assert.ok(!templateIds.has(template.id)); templateIds.add(template.id);
      }
    }
    const otherPaper = published.newspapers.find(other => other.id !== paper.id);
    assert.equal(experimentExample({...paper, experimentDemo: otherPaper.experimentDemo}, demo.variants[0]), null);
  }
  assert.ok(!JSON.stringify(published).includes("./local/"));
});

test("archive bundle is explicit about static provenance and persistent identity", () => {
  assert.equal(bundle.mode, "curated-archive-preview");
  assert.equal(papers.length, 3);
  const allIds = [];
  for (const paper of papers) {
    assert.ok(paper.sourceUrl.startsWith("https://"));
    assert.ok(paper.ocrUrl.endsWith("/ocr.txt"));
    assert.ok(paper.imageWidth > 0 && paper.imageHeight > 0);
    assert.equal(paper.records.length, 2);
    for (const record of paper.records) {
      assert.ok(record.id.startsWith("sn"));
      assert.equal(record.reviewRequired, true);
      assert.ok(record.rawText && record.text && record.reviewNote);
      assert.ok(record.cropSourceUrl.startsWith("https://"));
      assert.notEqual(record.rawText, record.text);
      allIds.push(record.id);
    }
  }
  assert.equal(new Set(allIds).size, allIds.length);
});

test("search is case-insensitive, trims space and considers readable plus raw text", () => {
  const records = papers[0].records;
  assert.equal(filterRecords(records, "  PAINT  references ")[0].title, "Paint salesmen");
  assert.equal(filterRecords(records, "palosmon")[0].title, "Paint salesmen");
  assert.equal(filterRecords(records, "horse")[0].title, "Newspaper delivery");
  assert.equal(filterRecords(records, "no-matching-phrase").length, 0);
  assert.deepEqual(filterRecords(records, "  "), records);
  assert.notEqual(filterRecords(records, ""), records);
  assert.equal(filterRecords([{id: "employer-only", title: "Role", employer: "Example Company", text: ""}], "example company").length, 1);
});

test("job search covers the complete dataset but renders at most three", () => {
  const records = Array.from({length: 8}, (_, i) => ({id: `job-${i}`, title: `Job ${i}`, text: "shared phrase", rawText: ""}));
  const paper = {...papers[0], records, featuredIds: ["job-6", "job-2", "job-4"]};
  assert.deepEqual(jobPreview(paper, "").visible.map(r => r.id), paper.featuredIds);
  assert.deepEqual(jobPreview(paper, "  ").visible.map(r => r.id), paper.featuredIds);
  const all = jobPreview(paper, "shared");
  assert.equal(all.matches.length, 8);
  assert.equal(all.visible.length, 3);
  assert.equal(jobPreview(paper, "Job 7").visible[0].id, "job-7");
  assert.equal(jobPreview(paper, "not-present").visible.length, 0);
  assert.ok(csvForRecords(paper, all.matches).includes('"job-7"')); // Export is not capped.
});

test("preview defaults tolerate fewer records and missing or duplicate feature IDs", () => {
  const records = papers[0].records;
  assert.deepEqual(jobPreview({...papers[0], featuredIds: ["unknown", records[1].id, records[1].id]}, "").visible,
    [records[1], records[0]]);
  assert.equal(jobPreview({...papers[0], records: []}, "").visible.length, 0);
});

test("selection survives filtering and empty results never display an unrelated record", () => {
  const records = papers[0].records;
  assert.equal(chooseRecord(records, records[1].id), records[1]);
  assert.equal(chooseRecord([records[0]], records[1].id), records[0]);
  assert.equal(chooseRecord([], records[1].id), null);
});

test("all approximate highlights fit the original image coordinate system", () => {
  for (const paper of papers) for (const record of paper.records) {
    const box = normalizedBox(paper, record);
    assert.ok(box.left >= 0 && box.top >= 0);
    assert.ok(box.width > 0 && box.height > 0);
    assert.ok(box.left + box.width <= 100 && box.top + box.height <= 100);
  }
  assert.throws(() => normalizedBox(papers[0], {bbox: [-1, 3, 40, 50]}));
  assert.throws(() => normalizedBox(papers[0], {bbox: [0, 0, 1e10, 50]}));
  assert.throws(() => normalizedBox({...papers[0], imageWidth: 0}, papers[0].records[0]));
});

test("CSV preserves raw OCR, exact persistent IDs, page provenance and review flags", () => {
  const paper = papers[0];
  const record = paper.records[0];
  const csv = csvForRecords(paper, [record]);
  assert.equal(CSV_COLUMNS.length, 9);
  assert.ok(csv.startsWith('"ad_id","Text","raw_text"'));
  assert.ok(csv.includes(`"${record.id}"`));
  assert.ok(csv.includes(`"${paper.sourceUrl}"`));
  assert.ok(csv.includes(record.rawText));
  assert.ok(csv.endsWith('"true"\r\n'));
  assert.ok(!csv.includes(paper.records[1].id));
  assert.ok(!csv.includes("smoke_variant") && !csv.includes("resume"));
});

test("CSV quoting handles multiline OCR, quotes, commas and spreadsheet formulas", () => {
  const original = papers[0].records[0];
  const record = {...original, text: 'A "quoted", multiline\nentry', rawText: '=HYPERLINK("bad")'};
  const csv = csvForRecords(papers[0], [record]);
  assert.ok(csv.includes('"A ""quoted"", multiline\nentry"'));
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));
  assert.equal(original.text, papers[0].records[0].text);
});

test("saved pipeline CSV includes shared full-page OCR without treating it as per-ad text", () => {
  const paper = {...papers[0], rawText: "FULL PAGE OCR"};
  const record = {...paper.records[0], rawText: ""};
  assert.ok(csvForRecords(paper, [record]).includes('"FULL PAGE OCR"'));
  assert.equal(filterRecords([record], "FULL PAGE OCR").length, 0);
});

test("bookmarked steps work under a GitHub Pages repository prefix", () => {
  const url = "https://example.github.io/LLM_AuditKit/?paper=bend-bulletin-1918#data";
  assert.deepEqual(stateFromUrl(url, papers), {paperId: "bend-bulletin-1918", step: "data"});
  assert.deepEqual(stateFromUrl("https://example.github.io/LLM_AuditKit/?paper=unknown#other", papers),
    {paperId: papers[0].id, step: "archive"});
  assert.equal(new URL("./data/newspapers.json", "https://example.github.io/LLM_AuditKit/app.mjs").pathname,
    "/LLM_AuditKit/data/newspapers.json");
});

test("source dates do not change with browser timezone", () => {
  assert.equal(formatDate("1900-01-01"), "1 January 1900");
  assert.equal(formatDate("1918-10-18"), "18 October 1918");
});

test("resume demo binds saved variants to a real job and supports bookmarks", () => {
  const paper = {...papers[0], resumeDemo: {
    jobId: papers[0].records[0].id,
    variants: [pairedVariant({id: "one", label: "Strong fit", prompt: "Create a concise strong-fit resume.", template: "{{name}}\nResume\n{{address}}"})],
  }};
  assert.equal(resumeDemo(paper).jobTitle, paper.records[0].title);
  assert.equal(stateFromUrl("https://example.org/?paper=" + paper.id + "#resumes", [paper]).step, "resumes");
  assert.equal(stateFromUrl("https://example.org/?paper=" + paper.id + "#population", [paper]).step, "population");
  assert.equal(resumeDemo({...paper, records: []}), null);
  assert.equal(resumeDemo(papers[0]), null);
  assert.equal(resumeDemo({...paper, resumeDemo: {...paper.resumeDemo, variants: []}}), null);
  assert.equal(resumeDemo({...paper, resumeDemo: {...paper.resumeDemo, variants: [...paper.resumeDemo.variants, ...paper.resumeDemo.variants]}}), null);
  assert.ok(resumeDemo({...paper, resumeDemo: {...paper.resumeDemo,
    variants: [{id: "prompt-only", label: "Strong fit", prompt: "Create a concise resume."}]}}));
  for (const prompt of [undefined, "", "   ", ["Summary"]]) {
    assert.equal(resumeDemo({...paper, resumeDemo: {...paper.resumeDemo,
      variants: [{...paper.resumeDemo.variants[0], prompt}]}}), null);
  }
  assert.equal(stateFromUrl("https://example.org/#resumes", papers).step, "archive");
  assert.equal(stateFromUrl("https://example.org/#population", papers).step, "archive");
  const promptOnly = {...paper, resumeDemo: {...paper.resumeDemo, variants: [{id: "no-output", label: "Prompt", prompt: "Draft"}]}};
  assert.equal(stateFromUrl("https://example.org/#population", [promptOnly]).step, "archive");
});

test("population demo replaces only explicit name/address tokens, without changing prose", () => {
  const source = "{{name}}\n{{address}}\nEXPERIENCE\nFive years of office work.\nRef: {{name}}";
  const copies = DEMO_CANDIDATES.map(candidate => populateResumeExample(source, candidate));
  for (const [index, candidate] of DEMO_CANDIDATES.entries()) {
    assert.equal(copies[index], `${candidate.name}\n${candidate.address}\nEXPERIENCE\nFive years of office work.\nRef: ${candidate.name}`);
  }
  assert.notEqual(copies[0], copies[1]);
  assert.equal(source, "{{name}}\n{{address}}\nEXPERIENCE\nFive years of office work.\nRef: {{name}}");
  assert.equal(new Set(DEMO_CANDIDATES.map(candidate => candidate.id)).size, 2);
  assert.ok(Object.isFrozen(DEMO_CANDIDATES) && DEMO_CANDIDATES.every(Object.isFrozen));
  for (const template of [undefined, "", "No placeholders", "{{name}}", "{{name}} {{address}} {{city}}", "{{name}} {{address}} {{constructor}}"])
    assert.equal(populateResumeExample(template, DEMO_CANDIDATES[0]), null);
  for (const candidate of [null, {}, {name: "", address: "A"}, {name: "A", address: 1}])
    assert.equal(populateResumeExample(source, candidate), null);
  assert.equal(populateResumeExample("{{name}} / {{address}}", {name: "$& <script>literal</script>", address: "Test address"}), "$& <script>literal</script> / Test address");
});

test("population uses explicit candidate/template IDs and never duplicates one template", () => {
  const variant = pairedVariant({id: "pair", label: "Pair", template: "{{name}}\n{{address}}\nFirst applicant background"});
  const examples = populationExamples(variant);
  assert.equal(examples[0].templateId, variant.templates[0].id);
  assert.equal(examples[1].templateId, variant.templates[1].id);
  assert.match(examples[0].resume, /First applicant background/);
  assert.match(examples[1].resume, /Different fictional employer/);
  assert.ok(!examples[1].resume.includes("First applicant background"));
  assert.deepEqual(populationExamples({...variant, assignments: [...variant.assignments].reverse()}), examples);
  assert.equal(populationExamples({template: variant.template}), null);
  for (const mutate of [
    data => {data.assignments = [];},
    data => {data.assignments[1].candidateId = data.assignments[0].candidateId;},
    data => {data.assignments[1].templateId = data.assignments[0].templateId;},
    data => {data.assignments[1].templateId = "missing-template";},
    data => {data.templates[1].id = data.templates[0].id;},
    data => {data.templates[1].text = data.templates[0].text;},
    data => {data.templates[1].text = "Missing placeholders";},
    data => {data.template += " stale alias";},
  ]) {
    const changed = structuredClone(variant); mutate(changed);
    assert.equal(populationExamples(changed), null);
  }
  assert.equal(resumeTemplates(variant).length, 2);
});

test("inline settings resolve one complete saved combination and never invent outputs", () => {
  const variants = inlineVariants("settings-test");
  const paper = {...papers[0], resumeDemo: {jobId: papers[0].records[0].id, inlineControls: true, variants}};
  paper.experimentDemo = syntheticExperiment(paper);
  const demo = resumeDemo(paper);
  assert.ok(demo);
  for (const variant of variants) {
    assert.equal(inlineResumeVariant(demo, variant.settings), variant);
    assert.equal(resumeTemplates(variant).length, variant.settings.resumes);
    assert.equal(populationExamples(variant).length, 2); // Two explicit assignments, even for four templates.
    assert.equal(finalOutputRows(paper, variant.id).length, 2);
    assert.ok(finalOutputRows(paper, variant.id).every(row => row.variant_id === variant.id));
  }
  assert.equal(finalOutputRows(paper).length, 16);
  assert.deepEqual(finalOutputRows(paper, "unknown-combination"), []);
  for (const settings of [{resumes: 3, jobSkills: 2, experience: "entry-level"}, {resumes: 2, jobSkills: "2", experience: "entry-level"}, {resumes: 2, jobSkills: 2, experience: "unknown"}]) {
    assert.equal(inlineResumeVariant(demo, settings), null);
  }
  assert.equal(resumeDemo({...paper, resumeDemo: {...demo, variants: variants.slice(1)}}), null);
  assert.equal(resumeDemo({...paper, resumeDemo: {...demo, variants: [...variants.slice(1), variants[1]]}}), null);
  const broken = structuredClone(variants); broken[0].settings.resumes = 4;
  assert.equal(resumeDemo({...paper, resumeDemo: {...demo, variants: broken}}), null);
});

test("experiment examples must match the exact prompt, job, template and ordered candidates", () => {
  const variant = pairedVariant({id: "synthetic-v", label: "Preset", prompt: "Generate a fictional resume", template: "{{name}}\n{{address}}\nQualifications"});
  const paper = {...papers[0], resumeDemo: {jobId: papers[0].records[0].id, variants: [variant]}};
  paper.experimentDemo = syntheticExperiment(paper);
  assert.ok(experimentExample(paper, variant));
  assert.equal(stateFromUrl("https://example.org/#experiment", [paper]).step, "experiment");
  assert.equal(stateFromUrl("https://example.org/#experiment", papers).step, "archive");
  assert.equal(experimentExample(paper, null), null);
  assert.equal(experimentExample({...paper, experimentDemo: undefined}, variant), null);
  for (const mutate of [
    data => {data.prompt += " changed";},
    data => {data.examples[0].prompt += " changed";},
    data => {data.examples[0].jobPosting += " changed";},
    data => {data.examples[0].jobId = "other-job";},
    data => {data.examples[0].template += " changed";},
    data => {data.examples[0].generationPrompt += " changed";},
    data => {data.examples[0].candidates.reverse();},
    data => {data.examples[0].candidates[0].resume += " changed";},
    data => {data.examples[0].candidates[0].name = "Different name";},
    data => {data.examples[0].candidates[1].templateId = "other-template";},
    data => {data.examples[0].decisions.reverse();},
    data => {data.examples[0].decisions[0].invite = "Yes";},
    data => {data.examples[0].decisions[0].logprob = 1;},
    data => {data.examples[0].decisions[0].logprob = null;},
    data => {data.examples[0].explanation = "";},
    data => {data.examples[0].requestId = "";},
    data => {data.examples.push({...data.examples[0]});},
  ]) {
    const changed = structuredClone(paper.experimentDemo); mutate(changed);
    assert.equal(experimentExample({...paper, experimentDemo: changed}, variant), null);
  }
  assert.equal(experimentExample(paper, {...variant, template: variant.template + " edited"}), null);
  const changedPair = structuredClone(variant); changedPair.templates[1].text += " New duties";
  assert.equal(experimentExample(paper, changedPair), null);
  assert.equal(experimentExample({...paper, records: []}, variant), null);
});

test("final output flattens validated decisions with full-precision logprobs and provenance", () => {
  const variant = pairedVariant({id: "final-test", label: "Preset", prompt: "Generate fictional resumes", template: "{{name}}\n{{address}}\nQualifications"});
  const paper = {...papers[0], resumeDemo: {jobId: papers[0].records[0].id, variants: [variant]}};
  paper.experimentDemo = syntheticExperiment(paper);
  const precise = -0.0000000123456789;
  paper.experimentDemo.examples[0].decisions[1].logprob = precise;
  const rows = finalOutputRows(paper);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(row => row.decision), [1, 0]);
  assert.deepEqual(rows.map(row => row.answer), ["Yes", "No"]);
  assert.equal(rows[1].logprob, precise);
  assert.equal(rows[1].template_id, variant.templates[1].id);
  assert.equal(rows[1].candidate_id, DEMO_CANDIDATES[1].id);
  assert.equal(rows[1].request_id, paper.experimentDemo.examples[0].requestId);
  assert.equal(new Set(rows.map(row => `${row.request_id}:${row.candidate_id}`)).size, rows.length);
  assert.equal(stateFromUrl("https://example.org/#results", [paper]).step, "results");
  assert.equal(stateFromUrl("https://example.org/#results", papers).step, "archive");
  assert.deepEqual(finalOutputRows(papers[0]), []);
  const stale = structuredClone(paper); stale.experimentDemo.examples[0].candidates[1].resume += " stale";
  assert.deepEqual(finalOutputRows(stale), []);
  assert.equal(stateFromUrl("https://example.org/#results", [stale]).step, "archive");
  const incomplete = structuredClone(paper); incomplete.resumeDemo.variants.push(pairedVariant({...variant, id: "no-result"}));
  assert.deepEqual(finalOutputRows(incomplete), []);
  const csv = resultCsv([{...rows[1], candidate_name: "=FORMULA", explanation: 'Line one, "quoted"\nLine two'}]);
  assert.ok(csv.startsWith(RESULT_COLUMNS.map(field => `"${field}"`).join(",")));
  assert.ok(csv.includes(`"${precise}"`)); // Numeric negatives must not become apostrophe-prefixed strings.
  assert.ok(!csv.includes(`"'${precise}"`));
  assert.ok(csv.includes('"\'=FORMULA"'));
  assert.ok(csv.includes('"Line one, ""quoted""\nLine two"'));
  assert.ok(csv.includes(rows[1].request_id) && csv.includes(rows[1].template_id));
  assert.equal(resultCsv([]).split("\r\n").length, 2);
});

test("saved resumes are available only for the selected unchanged preset", () => {
  const variant = {id: "a", prompt: "Original prompt", template: "{{name}}\nSaved prose"};
  const demo = {variants: [variant]};
  assert.equal(savedResumeVariant(demo, "a", variant.prompt), variant);
  assert.equal(savedResumeVariant(demo, "a", "Edited prompt"), null);
  assert.equal(savedResumeVariant(demo, "b", variant.prompt), null);
  assert.equal(savedResumeVariant(null, "a", variant.prompt), null);
  for (const template of [undefined, "", "   ", {}]) {
    assert.equal(savedResumeVariant({variants: [{...variant, template}]}, "a", variant.prompt), null);
  }
});

test("prompt summaries are display text, never substitutes for full saved generation inputs", () => {
  const variant = pairedVariant({id: "year-prompt", label: "Job agency", prompt: "Full generation instructions and source job", promptSummary: "A short gist", systemPrompt: "Agency system instructions", template: "{{name}}\n{{address}}\nQualifications"});
  const paper = {...papers[0], resumeDemo: {jobId: papers[0].records[0].id, variants: [variant]}};
  paper.experimentDemo = syntheticExperiment(paper);
  paper.experimentDemo.examples[0].generationSystemPrompt = variant.systemPrompt;
  assert.equal(resumePromptText(variant), "A short gist");
  assert.equal(savedResumeVariant(paper.resumeDemo, variant.id, "A short gist"), variant);
  assert.equal(savedResumeVariant(paper.resumeDemo, variant.id, variant.prompt), null);
  assert.equal(savedResumeVariant(paper.resumeDemo, variant.id, "An edited gist"), null);
  assert.ok(experimentExample(paper, variant));
  assert.equal(experimentExample(paper, {...variant, prompt: variant.prompt + " changed"}), null);
  assert.equal(experimentExample(paper, {...variant, systemPrompt: "Other agency instructions"}), null);
  for (const promptSummary of ["", " ", null, {}]) {
    assert.equal(resumeDemo({...paper, resumeDemo: {...paper.resumeDemo, variants: [{...variant, promptSummary}]}}), null);
  }
  assert.equal(resumePromptText({prompt: "Old-style prompt"}), "Old-style prompt");
});

test("typesetting preserves resume content, placeholders, sections and bullets", () => {
  assert.deepEqual(resumeBlocks("\r\n{{name}}\r\n{{address}}\r\n\r\nEXPERIENCE\r\nFictional Office, 1987-1990\r\n- Filing & phones\r\n• <script>literal</script>\r\n\r\nEDUCATION\r\nFictional School"), [
    {kind: "contact", lines: ["{{name}}", "{{address}}"]},
    {kind: "heading", text: "EXPERIENCE"},
    {kind: "paragraph", text: "Fictional Office, 1987-1990"},
    {kind: "list", items: ["Filing & phones", "<script>literal</script>"]},
    {kind: "heading", text: "EDUCATION"},
    {kind: "paragraph", text: "Fictional School"},
  ]);
  assert.deepEqual(resumeBlocks(""), []);
  assert.deepEqual(resumeBlocks("Unstructured resume\nNo invented headings"), [
    {kind: "paragraph", text: "Unstructured resume"}, {kind: "paragraph", text: "No invented headings"},
  ]);
  assert.equal(resumeBlocks("{{name}}\n{{address}}\nEXPERIENCE")[1].kind, "heading");
});

test("placeholder highlighting splits text without replacing values or interpreting HTML", () => {
  const text = "<script>literal</script> {{name}}{{address}} in {{city_2}}. {{not valid}}";
  const parts = resumeTextParts(text);
  assert.equal(parts.map(part => part.text).join(""), text);
  assert.deepEqual(parts.filter(part => part.placeholder).map(part => part.text), ["{{name}}", "{{address}}", "{{city_2}}"]);
  assert.deepEqual(resumeTextParts("No placeholders"), [{text: "No placeholders", placeholder: false}]);
  assert.deepEqual(resumeTextParts(""), []);
});

test("source crop positioning uses original image coordinates", () => {
  const paper = {imageWidth: 1000, imageHeight: 2000};
  const style = cropStyle(paper, {bbox: [200, 400, 500, 800]});
  assert.deepEqual(style, {width: "200%", left: "-40%", top: "0", transform: "translateY(-20%)"});
  assert.throws(() => cropStyle(paper, {bbox: [-1, 0, 10, 20]}));
});

test("public hosts never request a local research bundle", async () => {
  const calls = [];
  const fetcher = async url => {calls.push(url); return {ok: true, json: async () => bundle};};
  assert.equal(await loadBundle(fetcher, "example.github.io", "public", "private"), bundle);
  assert.deepEqual(calls, ["public"]);
});

test("loopback preview selects local scan and missing local data falls back", async () => {
  for (const host of ["localhost", "127.0.0.1", "[::1]"]) {
    const calls = [];
    const local = {newspapers: [{id: "synthetic-local-test"}]};
    const fetcher = async (url, options) => {
      assert.equal(options.cache, "no-cache");
      calls.push(url); return {ok: true, json: async () => local};
    };
    assert.equal(await loadBundle(fetcher, host, "public", "private"), local);
    assert.deepEqual(calls, ["private"]);
  }
  const calls = [];
  const fetcher = async url => {
    calls.push(url);
    return url === "private" ? {ok: false, status: 404} : {ok: true, json: async () => bundle};
  };
  assert.equal(await loadBundle(fetcher, "localhost", "public", "private"), bundle);
  assert.deepEqual(calls, ["private", "public"]);
});

test("data errors are visible instead of silently substituting another source", async () => {
  await assert.rejects(loadBundle(async () => ({ok: false, status: 500}), "localhost", "public", "private"));
  await assert.rejects(loadBundle(async () => ({ok: false, status: 404}), "example.org", "public", "private"));
  await assert.rejects(loadBundle(async () => ({ok: true, json: async () => ({newspapers: []})}), "localhost", "public", "private"));
  await assert.rejects(loadBundle(async () => ({ok: true, json: async () => {throw new Error("Invalid JSON");}}), "localhost", "public", "private"));
});
