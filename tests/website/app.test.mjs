import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {syntheticExperiment, pairedVariant, inlineVariants, withControlledFields, withPopulationPools, withHiringPerspectives} from "./experiment-fixture.mjs";

class Element {
  constructor() {
    this.children = []; this.style = {}; this.dataset = {}; this.attributes = {}; this.events = {}; this.hidden = false;
    this.classes = new Set(); this.classList = {add: value => this.classes.add(value)};
    this.top = 1000;
  }
  setAttribute(key, value) {this.attributes[key] = value;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  addEventListener(name, fn) {this.events[name] = fn;}
  scrollTo() {}
  scrollIntoView(options) {this.lastScroll = options;}
  getBoundingClientRect() {return {top: this.top};}
  showModal() {this.open = true;}
  close() {this.open = false;}
  focus() {this.focused = true;}
  click() {this.clicked = true;}
  fire(name, value) {return this.events[name]?.({target: {value}});}
}

const resumeText = node => node.className === "placeholder-tooltip" ? ""
  : (node.textContent || "") + node.children.map(resumeText).join("");
const qualifications = node => node.className?.startsWith("candidate-value") ? ""
  : (node.textContent || "") + node.children.map(qualifications).join("");
const candidateValues = node => node.className?.startsWith("candidate-value") ? [node]
  : node.children.flatMap(candidateValues);

for (const {revealSupported, failRender} of [
  {revealSupported: true}, {revealSupported: false}, {revealSupported: false, failRender: true},
]) {
test(`preview rendering with reveal support ${revealSupported}, failure ${Boolean(failRender)}`, async () => {
  const html = await readFile(new URL("../../website/index.html", import.meta.url), "utf8");
  const bundle = JSON.parse(await readFile(new URL("../../website/data/archive-newspapers.json", import.meta.url), "utf8"));
  bundle.newspapers[0].records.push({...bundle.newspapers[0].records[0],
    id: "synthetic-third-ad", title: "Third synthetic job", text: "Third job", rawText: ""});
  for (let i = 1; i <= 4; i++) bundle.newspapers[0].records.push({
    id: `hidden-job-${i}`, title: `Nursing example ${i}`, text: `Nursing hidden job ${i}`, rawText: "",
    bbox: i === 1 ? bundle.newspapers[0].records[0].bbox : null,
    cropMethod: i === 1 ? "approximate-ocr-text-alignment" : undefined,
  });
  bundle.newspapers[0].resumeDemo = {
    jobId: bundle.newspapers[0].records[0].id,
    variants: [
      {id: "strong", label: "Strong fit", prompt: "Create a strong-fit applicant with relevant office experience.", template: "{{name}}\n{{address}}\n\nEXPERIENCE\nFictional Office, 1987-1990\n- Filing & phones\n- <script>literal</script> for {{name}}"},
      {id: "transfer", label: "Transferable skills", prompt: "Create an applicant with retail experience and transferable skills.", template: "{{name}}\nTransferable-skills resume\n{{address}}"},
      {id: "detail", label: "More detail", prompt: "Create a strong-fit applicant with an expanded history.", template: "{{name}}\nDetailed resume\n{{address}}"},
    ],
  };
  bundle.newspapers[0].resumeDemo.variants = bundle.newspapers[0].resumeDemo.variants.map(pairedVariant);
  bundle.newspapers[0].experimentDemo = syntheticExperiment(bundle.newspapers[0]);
  const secondDemo = structuredClone(bundle.newspapers[0]);
  secondDemo.id = "synthetic-other-paper";
  secondDemo.city = "Example City";
  secondDemo.imageSrc = "./assets/other-paper.jpg";
  secondDemo.records = secondDemo.records.map(record => ({...record, id: `other-${record.id}`, text: `Other paper: ${record.text}`}));
  secondDemo.resumeDemo.jobId = secondDemo.records[0].id;
  secondDemo.resumeDemo.variants = secondDemo.resumeDemo.variants.slice(0, 1).map(variant => ({...variant, prompt: `Other paper full instructions: ${variant.prompt}`, promptSummary: "Other paper: a short prompt summary"}));
  secondDemo.experimentDemo = syntheticExperiment(secondDemo);
  bundle.newspapers.push(secondDemo);
  const controlledPaper = structuredClone(secondDemo);
  controlledPaper.id = "synthetic-inline-paper";
  controlledPaper.resumeDemo = {jobId: controlledPaper.records[0].id, inlineControls: true, variants: inlineVariants().map(withControlledFields).map(withPopulationPools)};
  controlledPaper.experimentDemo = withHiringPerspectives(controlledPaper);
  bundle.newspapers.push(controlledPaper);
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element()]));
  const downloadLinks = [];
  const scroll = new Element();
  const windowEvents = {};
  let revealObserver;
  class Observer {
    constructor(callback) {this.callback = callback; this.observed = new Set(); revealObserver = this;}
    observe(node) {this.observed.add(node);}
    unobserve(node) {this.observed.delete(node);}
  }
  const previous = Object.fromEntries(["document", "window", "location", "history", "fetch"].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const put = (key, value) => Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  put("document", {
    getElementById: id => {
      assert.ok(nodes.has(id), id);
      return failRender && id === "variant-prompt" ? null : nodes.get(id);
    },
    createElement: tag => {const node = new Element(); if (tag === "a") downloadLinks.push(node); return node;},
    querySelectorAll: selector => {assert.equal(selector, ".reveal"); return [nodes.get("data-view"), nodes.get("resume-view"), nodes.get("population-view"), nodes.get("experiment-view"), nodes.get("results-view")];},
    querySelector: selector => {assert.equal(selector, ".enlarged-scroll"); return scroll;},
  });
  put("window", {addEventListener: (name, fn) => {windowEvents[name] = fn;}, innerHeight: 800,
    ...(revealSupported ? {IntersectionObserver: Observer} : {})});
  put("location", {href: "https://example.org/kit/", hostname: "example.org"});
  put("history", {
    replaceState: (_state, _title, url) => {globalThis.location.href = String(url);},
    pushState: (_state, _title, url) => {globalThis.location.href = String(url);},
  });
  let fetches = 0;
  put("fetch", async () => {fetches++; return {ok: true, json: async () => bundle};});
  const find = (node, id) => node.id === id ? node : node.children.map(child => find(child, id)).find(Boolean);
  const get = id => nodes.get(id) ?? [...nodes.values()].map(node => find(node, id)).find(Boolean);
  const resume = index => get("populated-document").children[index].children[1];
  const field = (index, name) => candidateValues(resume(index)).find(node => node.dataset.field === name);
  try {
    await import(`../../website/app.mjs?grid=${revealSupported}&failure=${Boolean(failRender)}`);
    await new Promise(resolve => setImmediate(resolve));
    if (failRender) {
      assert.equal(get("load-status").hidden, false);
      assert.match(get("load-status").textContent, /Reload the page/);
      assert.equal(get("resume-view").hidden, true);
      assert.equal(get("resume-connector").hidden, true);
      assert.equal(get("population-view").hidden, true);
      assert.equal(get("population-connector").hidden, true);
      assert.equal(get("experiment-view").hidden, true);
      assert.equal(get("experiment-connector").hidden, true);
      assert.equal(get("results-view").hidden, true);
      assert.equal(get("results-connector").hidden, true);
      return;
    }
    assert.equal(get("load-status").hidden, true);
    assert.equal(get("archive-view").hidden, false);
    assert.equal(get("data-view").hidden, false);
    assert.equal(get("scan-image").src, bundle.newspapers[0].imageSrc);
    assert.equal(get("resume-view").hidden, false);
    assert.equal(get("resume-connector").hidden, false);
    assert.ok(!nodes.has("resume-job"));
    assert.equal(get("prompt-variants").children.length, 3);
    assert.ok(!nodes.has("resume-output"));
    assert.equal(get("variant-prompt").value, bundle.newspapers[0].resumeDemo.variants[0].prompt);
    assert.equal(get("generate-resume").disabled, false);
    assert.equal(get("population-view").hidden, false);
    assert.equal(get("population-connector").hidden, false);
    assert.equal(get("populated-document").children.length, 2);
    assert.equal(get("population-caption").hidden, true);
    assert.equal(get("population-caption").textContent, "");
    assert.ok(!nodes.has("experiment-candidates") && !nodes.has("experiment-job"));
    assert.equal(get("experiment-view").hidden, false);
    assert.equal(get("experiment-result").hidden, true);
    assert.equal(get("results-view").hidden, false);
    assert.equal(get("results-connector").hidden, false);
    assert.ok(!nodes.has("results-count"));
    assert.equal(get("final-output-rows").children.length, 6);
    assert.deepEqual(get("final-output-rows").children[0].children.map(node => node.textContent), ["Strong fit", "Alex Morgan", "Yes", "90.5%", "synthetic-test-model", "…", "…", "…"]);
    assert.ok(get("final-output-rows").children[0].children.slice(5).every(node => node.attributes["aria-label"].includes("full value available in the CSV")));
    assert.equal(get("final-output-rows").children[1].children[2].textContent, "No");
    let downloadBlob;
    const createUrl = URL.createObjectURL;
    URL.createObjectURL = blob => {downloadBlob = blob; return createUrl(blob);};
    try {get("download-results").fire("click");} finally {URL.createObjectURL = createUrl;}
    assert.equal(downloadLinks.at(-1).clicked, true);
    assert.equal(downloadLinks.at(-1).download, `${bundle.newspapers[0].id}-candidate-results.csv`);
    const downloaded = await downloadBlob.text();
    assert.ok(downloaded.includes('"logprob"') && downloaded.includes('"template_id"') && downloaded.includes('"request_id"'));
    assert.ok(downloaded.includes('"-0.1"'));
    assert.equal(fetches, 1);
    assert.equal(get("run-experiment").disabled, false);
    const hiringPrompt = bundle.newspapers[0].experimentDemo.prompt;
    assert.equal(get("experiment-prompt").value, hiringPrompt);
    assert.equal(get("experiment-model").textContent, "synthetic-test-model");
    assert.match(get("experiment-model").title, /previously recorded response/);
    for (const [index, name] of ["Alex Morgan", "Jordan Taylor"].entries()) {
      get("populated-document").children[index].children[0].children[1].fire("click");
      assert.equal(get("resume-dialog").open, true);
      assert.equal(get("resume-dialog-title").textContent, `Candidate ${index + 1}`);
      assert.ok(resumeText(get("resume-document")).includes(name));
      assert.ok(!resumeText(get("resume-document")).includes("{{name}}"));
      if (index === 1) assert.match(resumeText(get("resume-document")), /Different fictional employer/);
      get("close-resume-dialog").fire("click");
    }
    get("run-experiment").fire("click");
    assert.equal(get("experiment-result").hidden, false);
    assert.equal(get("experiment-decisions").children.length, 2);
    assert.equal(get("experiment-decisions").children[0].children[1].textContent, "Invite to interview");
    assert.equal(get("experiment-decisions").children[0].children[2].textContent, "90.5% answer probability");
    assert.equal(get("experiment-decisions").children[1].children[1].textContent, "Do not invite");
    assert.equal(get("experiment-explanation").textContent, bundle.newspapers[0].experimentDemo.examples[0].explanation);
    get("experiment-prompt").value = "Edited hiring prompt";
    get("experiment-prompt").fire("input", "Edited hiring prompt");
    assert.equal(get("results-view").hidden, true);
    assert.equal(get("results-connector").hidden, true);
    assert.equal(get("final-output-rows").children.length, 0);
    assert.equal(get("download-results").disabled, true);
    const previousDownloads = downloadLinks.length;
    get("download-results").fire("click");
    assert.equal(downloadLinks.length, previousDownloads);
    assert.equal(get("run-experiment").disabled, true);
    assert.equal(get("experiment-result").hidden, true);
    assert.equal(get("experiment-explanation").textContent, "");
    assert.match(get("experiment-status").textContent, /original summary/);
    get("run-experiment").fire("click");
    assert.equal(get("experiment-result").hidden, true);
    get("prompt-variants").children[1].fire("click");
    assert.equal(get("experiment-prompt").value, hiringPrompt);
    assert.equal(get("run-experiment").disabled, false);
    get("prompt-variants").children[0].fire("click");
    assert.equal(get("experiment-prompt").value, "Edited hiring prompt");
    get("experiment-prompt").value = hiringPrompt;
    get("experiment-prompt").fire("input", hiringPrompt);
    assert.equal(get("results-view").hidden, false);
    get("run-experiment").fire("click");
    assert.equal(get("experiment-result").hidden, false);
    const firstQualifications = qualifications(resume(0));
    assert.deepEqual(candidateValues(resume(0)).map(node => node.textContent), ["Alex Morgan", "12 Example Street", "Alex Morgan"]);
    assert.deepEqual(candidateValues(resume(1)).map(node => node.textContent), ["Jordan Taylor", "48 Sample Avenue"]);
    assert.notEqual(qualifications(resume(1)), firstQualifications);
    assert.match(qualifications(resume(1)), /Different fictional employer/);
    get("populated-document").children[1].children[0].children[1].fire("click");
    assert.match(resumeText(get("resume-document")), /Jordan Taylor/);
    get("close-resume-dialog").fire("click");
    field(0, "name").fire("click");
    assert.equal(get("candidate-field-dialog").open, true);
    get("candidate-field-options").children[2].fire("click");
    assert.equal(get("candidate-field-dialog").open, false);
    assert.equal(field(0, "name").textContent, "Casey Lee");
    assert.equal(field(0, "name").focused, true);
    assert.equal(qualifications(resume(0)), firstQualifications);
    assert.equal(field(1, "name").textContent, "Jordan Taylor");
    assert.equal(get("experiment-view").hidden, true);
    assert.equal(get("results-view").hidden, true);
    assert.equal(get("population-caption").hidden, false);
    assert.equal(get("population-caption").textContent, "Reset details to see saved model results.");
    assert.equal(get("experiment-explanation").textContent, "");
    const editedDownloads = downloadLinks.length;
    get("download-results").fire("click");
    assert.equal(downloadLinks.length, editedDownloads);
    get("reset-candidates").fire("click");
    assert.equal(field(0, "name").textContent, "Alex Morgan");
    assert.equal(get("experiment-view").hidden, false);
    assert.equal(get("results-view").hidden, false);
    assert.equal(get("population-caption").hidden, true);
    field(1, "address").fire("click");
    get("candidate-field-dialog").events.cancel({preventDefault() {}});
    assert.equal(get("candidate-field-dialog").open, false);
    assert.equal(field(1, "address").focused, true);
    assert.match(get("generate-resume").title, /previously generated templates/);
    get("generate-resume").fire("click");
    assert.equal(get("resume-dialog").open, true);
    const blocks = get("resume-document").children;
    assert.equal(blocks[0].className, "resume-contact");
    assert.deepEqual(blocks[0].children.map(resumeText), ["{{name}}", "{{address}}"]);
    assert.equal(resumeText(blocks[1]), "EXPERIENCE");
    assert.equal(resumeText(blocks[2]), "Fictional Office, 1987-1990");
    assert.equal(resumeText(blocks[3].children[1]), "<script>literal</script> for {{name}}");
    const placeholders = [blocks[0].children[0].children[0], blocks[0].children[1].children[0],
      blocks[3].children[1].children[1]];
    const tipIds = new Set();
    for (const token of placeholders) {
      assert.equal(token.className, "resume-placeholder");
      assert.equal(token.tabIndex, 0);
      const tip = token.children[0];
      assert.equal(tip.attributes.role, "tooltip");
      assert.equal(token.attributes["aria-describedby"], tip.id);
      assert.equal(tip.textContent, "Left blank on purpose! Close this preview and scroll down to see these details filled in.");
      tipIds.add(tip.id);
      let prevented = false, stopped = false;
      token.events.keydown({key: "Escape", preventDefault: () => {prevented = true;}, stopPropagation: () => {stopped = true;}});
      assert.equal(token.dataset.dismissed, "true");
      assert.ok(prevented && stopped);
      assert.equal(get("resume-dialog").open, true);
      token.fire("focus");
      assert.equal(token.dataset.dismissed, "false");
      token.dataset.dismissed = "true"; token.fire("mouseenter");
      assert.equal(token.dataset.dismissed, "false");
    }
    assert.equal(tipIds.size, 3);
    assert.equal(get("resume-template-options").children.length, 2);
    get("resume-template-options").children[1].fire("click");
    assert.match(resumeText(get("resume-document")), /Different fictional employer/);
    assert.equal(get("resume-template-options").children[1].attributes["aria-pressed"], "true");
    get("resume-template-options").children[0].fire("click");
    assert.match(resumeText(get("resume-document")), /Fictional Office/);
    get("close-resume-dialog").fire("click");
    assert.equal(get("resume-dialog").open, false);
    assert.equal(get("resume-source-image").src, bundle.newspapers[0].imageSrc);
    assert.equal(get("resume-source").style.aspectRatio, bundle.newspapers[0].records[0].bbox.slice(2).join(" / "));
    get("resume-source").fire("click");
    assert.equal(get("image-dialog").open, true);
    assert.equal(get("image-dialog-title").textContent, bundle.newspapers[0].records[0].title);
    assert.equal(get("enlarged-image").style.width, get("resume-source-image").style.width);
    get("close-dialog").fire("click");
    const draft = "My edited prompt <not HTML>";
    get("variant-prompt").value = draft;
    get("variant-prompt").fire("input", draft);
    assert.equal(get("generate-resume").disabled, true);
    assert.equal(get("population-view").hidden, true);
    assert.equal(get("population-connector").hidden, true);
    assert.equal(get("populated-document").children.length, 0);
    assert.equal(get("experiment-view").hidden, true);
    assert.equal(get("experiment-connector").hidden, true);
    assert.equal(get("experiment-result").hidden, true);
    assert.equal(get("experiment-explanation").textContent, "");
    get("generate-resume").fire("click"); // Guard even if a disabled event is forced.
    assert.equal(get("resume-dialog").open, false);
    get("prompt-variants").children[1].fire("click");
    assert.equal(get("prompt-variants").children[1].attributes["aria-pressed"], "true");
    assert.equal(get("prompt-variants").children[0].attributes["aria-pressed"], "false");
    assert.equal(get("variant-prompt").value, bundle.newspapers[0].resumeDemo.variants[1].prompt);
    assert.equal(get("generate-resume").disabled, false);
    assert.equal(get("population-view").hidden, false);
    assert.match(resumeText(get("populated-document")), /Transferable-skills resume/);
    assert.ok(!resumeText(get("populated-document")).includes("Fictional Office"));
    assert.equal(get("experiment-view").hidden, false);
    assert.equal(get("experiment-result").hidden, true);
    get("run-experiment").fire("click");
    assert.equal(get("experiment-explanation").textContent, bundle.newspapers[0].experimentDemo.examples[1].explanation);
    get("variant-prompt").value = "";
    get("variant-prompt").fire("input", "");
    get("prompt-variants").children[2].fire("click");
    assert.equal(get("variant-prompt").value, bundle.newspapers[0].resumeDemo.variants[2].prompt);
    get("prompt-variants").children[1].fire("click");
    assert.equal(get("variant-prompt").value, "");
    assert.equal(get("generate-resume").disabled, true);
    get("prompt-variants").children[0].fire("click");
    assert.equal(get("variant-prompt").value, draft);
    assert.equal(bundle.newspapers[0].resumeDemo.variants[0].prompt, "Create a strong-fit applicant with relevant office experience.");
    assert.equal(fetches, 1); // Editing/switching prompts never calls a service.
    assert.ok(!nodes.has("scan-examples"));
    assert.ok(!nodes.has("record-list") && !nodes.has("record-detail"));
    assert.equal(get("job-cards").children.length, 3);
    assert.equal(get("results-summary").textContent, "Showing 3 of 7 jobs");
    for (const [index, card] of get("job-cards").children.entries()) {
      const record = bundle.newspapers[0].records[index];
      assert.equal(card.dataset.recordId, record.id);
      assert.equal(card.children.length, 1); // Images only; no visible titles or body text.
      assert.equal(card.children[0].children[0].src, bundle.newspapers[0].imageSrc);
      assert.equal(card.children[0].attributes["aria-label"], `Read full text for ${record.title}`);
    }
    if (revealSupported) {
      revealObserver.callback([{target: get("data-view"), isIntersecting: true}]);
      assert.ok(get("data-view").classes.has("is-visible"));
      assert.ok(!revealObserver.observed.has(get("data-view")));
    } else assert.ok(!get("data-view").classes.has("will-reveal"));
    assert.ok(!nodes.has("preview-note") && !nodes.has("scan-caption"));
    assert.ok(!html.includes("data-step") && !html.includes("processing-tool") && !html.includes("<details"));
    assert.equal(get("paper-select").children[0].textContent, "Omaha, 1900");
    for (const [index, card] of get("job-cards").children.entries()) {
      card.children[0].fire("click");
      assert.equal(get("job-dialog").open, true);
      assert.equal(get("job-dialog-title").textContent, bundle.newspapers[0].records[index].title);
      assert.equal(get("job-full-text").textContent, bundle.newspapers[0].records[index].text);
      assert.equal(get("job-cards").children.length, 3);
      get("close-job-dialog").fire("click");
      assert.equal(get("job-dialog").open, false);
    }
    get("open-scan").fire("click");
    assert.equal(get("image-dialog").open, true);
    assert.equal(get("enlarged-image").src, bundle.newspapers[0].imageSrc);
    assert.equal(get("enlarged-image").style.width, "100%");
    assert.equal(get("enlarged-image").style.transform, "none");
    get("zoom-select").fire("change", "200");
    assert.equal(get("enlarged-crop").style.width, "200%");
    get("close-dialog").fire("click");
    get("data-view").top = 900; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#archive");
    get("data-view").top = 100; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#data");
    get("resume-view").top = 100; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#resumes");
    get("resume-view").top = 1000;
    get("prompt-variants").children[2].fire("click");
    get("population-view").top = 100; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#population");
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#population";
    windowEvents.popstate();
    assert.equal(get("population-view").lastScroll.behavior, "instant");
    get("experiment-view").top = 100; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#experiment");
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#experiment";
    windowEvents.popstate();
    assert.equal(get("experiment-view").lastScroll.behavior, "instant");
    get("results-view").top = 100; windowEvents.scroll();
    assert.equal(new URL(globalThis.location.href).hash, "#results");
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#results";
    windowEvents.popstate();
    assert.equal(get("results-view").lastScroll.behavior, "instant");
    get("variant-prompt").value = "Edited detail";
    get("variant-prompt").fire("input", "Edited detail");
    assert.equal(get("population-view").hidden, true);
    assert.equal(new URL(globalThis.location.href).hash, "#resumes");
    get("population-view").top = 1000;
    get("experiment-view").top = 1000;
    get("results-view").top = 1000;
    get("search-input").fire("input", "definitely-not-present");
    assert.equal(get("job-cards").children.length, 0);
    assert.equal(get("empty-state").hidden, false);
    assert.equal(get("download-button").disabled, true);
    get("search-input").fire("input", "horse");
    assert.equal(get("job-cards").children.length, 1);
    assert.equal(get("empty-state").hidden, true);
    assert.equal(get("download-button").disabled, false);
    get("search-input").fire("input", "nursing");
    assert.equal(get("job-cards").children.length, 3);
    assert.equal(get("results-summary").textContent, "Showing 3 of 4 matches");
    assert.equal(get("job-cards").children[0].dataset.recordId, "hidden-job-1");
    assert.equal(get("job-cards").children[0].children[0].className, "source-crop");
    assert.match(get("job-cards").children[0].children[0].children[0].alt, /Approximate newspaper source area/);
    assert.match(get("job-cards").children[0].children[0].title, /may include neighboring ads/);
    assert.equal(get("job-cards").children[1].children[0].className, "text-preview");
    get("job-cards").children[1].children[0].fire("click");
    assert.equal(get("job-full-text").textContent, "Nursing hidden job 2");
    get("close-job-dialog").fire("click");
    get("search-input").fire("input", "");
    assert.equal(get("job-cards").children.length, 3);
    assert.equal(get("job-cards").children[0].dataset.recordId, bundle.newspapers[0].records[0].id);
    get("paper-select").fire("change", bundle.newspapers[1].id);
    assert.equal(get("search-input").value, "");
    assert.equal(get("job-cards").children.length, 2);
    assert.equal(get("scan-image").src, bundle.newspapers[1].imageSrc);
    assert.equal(get("resume-view").hidden, true);
    assert.equal(get("resume-connector").hidden, true);
    assert.equal(get("variant-prompt").value, "");
    assert.equal(get("resume-source-image").src, "");
    assert.equal(get("prompt-variants").children.length, 0);
    assert.equal(get("resume-document").children.length, 0);
    assert.equal(get("resume-dialog").open, false);
    assert.equal(get("generate-resume").disabled, true);
    assert.equal(get("population-view").hidden, true);
    assert.equal(get("candidate-status").textContent, "");
    assert.equal(get("experiment-view").hidden, true);
    assert.equal(get("run-experiment").disabled, true);
    assert.equal(get("experiment-prompt").value, "");
    assert.equal(get("experiment-model").textContent, "");
    assert.equal(get("results-view").hidden, true);
    assert.equal(get("final-output-rows").children.length, 0);
    assert.equal(get("populated-document").children.length, 0);
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#resumes";
    windowEvents.popstate();
    assert.equal(get("resume-view").hidden, false);
    assert.equal(get("resume-view").lastScroll.behavior, "instant");
    assert.equal(get("variant-prompt").value, draft);
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[2].id + "#data";
    windowEvents.popstate();
    assert.equal(get("data-view").lastScroll.behavior, "instant");
    assert.equal(get("scan-image").src, bundle.newspapers[2].imageSrc);
    assert.equal(get("job-cards").children.length, 2);
    get("paper-select").fire("change", secondDemo.id);
    assert.equal(get("scan-image").src, secondDemo.imageSrc);
    assert.equal(get("resume-source-image").src, secondDemo.imageSrc);
    assert.equal(get("resume-view").hidden, false);
    assert.equal(get("variant-prompt").value, secondDemo.resumeDemo.variants[0].promptSummary);
    assert.equal(get("prompt-variants").hidden, true);
    assert.equal(get("population-view").hidden, false);
    assert.equal(get("populated-document").children.length, 2);
    assert.equal(get("experiment-result").hidden, true);
    get("run-experiment").fire("click");
    assert.equal(get("experiment-explanation").textContent, secondDemo.experimentDemo.examples[0].explanation);
    assert.equal(get("results-view").hidden, false);
    assert.equal(get("final-output-rows").children.length, 2);
    get("variant-prompt").value = "Edited summary";
    get("variant-prompt").fire("input", "Edited summary");
    assert.equal(get("generate-resume").disabled, true);
    assert.equal(get("results-view").hidden, true);
    get("variant-prompt").value = secondDemo.resumeDemo.variants[0].promptSummary;
    get("variant-prompt").fire("input", get("variant-prompt").value);
    assert.equal(get("generate-resume").disabled, false);
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#resumes";
    windowEvents.popstate();
    assert.equal(get("variant-prompt").value, draft); // Drafts never leak to the second paper.
    assert.equal(get("generate-resume").disabled, true);
    assert.equal(fetches, 1);
    get("paper-select").fire("change", controlledPaper.id);
    assert.equal(get("interactive-prompt").hidden, false);
    assert.equal(get("variant-prompt").hidden, true);
    assert.equal(get("prompt-variants").hidden, true);
    assert.equal(get("resume-count").value, "2");
    assert.equal(get("job-skill-count").value, "2");
    assert.equal(get("experience-level").value, "entry-level");
    assert.deepEqual(get("experiment-perspectives").children.map(node => node.textContent), ["Role-play", "Historian"]);
    assert.equal(get("experiment-prompt").value, "Synthetic role-play prompt for two applicants");
    assert.ok(!/fictional|JSON/.test(get("experiment-prompt").value));
    const fullRolePrompt = controlledPaper.experimentDemo.perspectives[0].prompts["2"];
    assert.notEqual(get("experiment-prompt").value, fullRolePrompt);
    get("experiment-prompt").value = fullRolePrompt;
    get("experiment-prompt").fire("input", fullRolePrompt);
    assert.equal(get("run-experiment").disabled, true);
    get("experiment-prompt").value = "Synthetic role-play prompt for two applicants";
    get("experiment-prompt").fire("input", get("experiment-prompt").value);
    assert.equal(get("run-experiment").disabled, false);
    get("generate-resume").fire("click");
    assert.equal(get("resume-template-options").children.length, 2);
    assert.match(resumeText(get("resume-document")), /\{\{university\}\}/);
    assert.match(resumeText(get("resume-document")), /\{\{work_start_month\}\}/);
    assert.match(resumeText(get("populated-document")), /Fictional College/);
    assert.match(resumeText(get("populated-document")), /June 1988–July 1990/);
    assert.ok(!resumeText(get("populated-document")).includes("{{"));
    assert.equal(field(0, "address").textContent, "10 Test Road");
    field(0, "address").fire("click");
    assert.deepEqual(get("candidate-field-options").children.map(node => node.textContent), ["10 Test Road", "20 Test Road", "30 Test Road", "40 Test Road"]);
    get("close-candidate-field").fire("click");
    assert.match(resumeText(resume(1)), /Other Fictional College/);
    get("populated-document").children[1].children[0].children[1].fire("click");
    assert.match(resumeText(get("resume-document")), /Other Fictional College/);
    assert.ok(!resumeText(get("resume-document")).includes("{{"));
    get("job-skill-count").value = "4";
    get("job-skill-count").fire("change", "4");
    assert.equal(get("resume-dialog").open, false);
    assert.equal(get("experiment-result").hidden, true);
    assert.equal(get("variant-prompt").value, "Summary for controls-2-4-entry-level");
    get("resume-count").value = "4";
    get("resume-count").fire("change", "4");
    get("experience-level").value = "experienced";
    get("experience-level").fire("change", "experienced");
    get("generate-resume").fire("click");
    assert.equal(get("resume-template-options").children.length, 4);
    get("resume-template-options").children[3].fire("click");
    assert.match(resumeText(get("resume-document")), /Fourth distinct background/);
    get("close-resume-dialog").fire("click");
    assert.equal(get("populated-document").children.length, 4);
    assert.equal(get("population-caption").hidden, true);
    assert.equal(get("population-caption").textContent, "");
    assert.match(resumeText(resume(3)), /Riley Parker/);
    get("populated-document").children[3].children[0].children[1].fire("click");
    assert.match(resumeText(get("resume-document")), /Riley Parker/);
    get("close-resume-dialog").fire("click");
    get("run-experiment").fire("click");
    assert.match(get("experiment-explanation").textContent, /controls-4-4-experienced/);
    assert.equal(get("final-output-rows").children.length, 4);
    assert.equal(get("experiment-decisions").children.length, 4);
    assert.equal(get("final-output-rows").children[0].children[0].textContent, "Role-play");
    URL.createObjectURL = blob => {downloadBlob = blob; return createUrl(blob);};
    try {get("download-results").fire("click");} finally {URL.createObjectURL = createUrl;}
    const selectedCsv = await downloadBlob.text();
    assert.ok(selectedCsv.includes('"controls-4-4-experienced"'));
    assert.ok(!selectedCsv.includes('"controls-2-2-entry-level"'));
    assert.ok(selectedCsv.includes('"synthetic-candidate-4"'));
    assert.equal(selectedCsv.trim().split("\r\n").length, 5);
    field(3, "university").fire("click");
    get("candidate-field-options").children[0].fire("click");
    assert.match(resumeText(resume(3)), /Fictional College/);
    assert.equal(get("results-view").hidden, true);
    field(3, "work_start_year").fire("click");
    get("candidate-field-options").children[1].fire("click");
    assert.match(resumeText(resume(3)), /June 1987–July 1990/);
    assert.match(resumeText(resume(3)), /1983–1987/);
    get("reset-candidates").fire("click");
    assert.match(resumeText(resume(3)), /June 1988–July 1990/);
    assert.equal(get("final-output-rows").children.length, 4);
    get("experiment-perspectives").children[1].fire("click");
    assert.equal(get("experiment-perspectives").children[1].attributes["aria-pressed"], "true");
    assert.equal(get("experiment-prompt").value, "Synthetic historian prompt for four applicants");
    assert.equal(get("experiment-result").hidden, true);
    assert.equal(get("final-output-rows").children[0].children[2].textContent, "No");
    assert.equal(get("final-output-rows").children[0].children[3].textContent, "20.0%");
    assert.equal(get("final-output-rows").children[0].children[0].textContent, "Historian");
    assert.ok(get("final-output-rows").children.every(row => row.children.length === 8 && row.children.slice(5).every(cell => cell.textContent === "…")));
    get("run-experiment").fire("click");
    assert.match(get("experiment-explanation").textContent, /Perspective: historian/);
    get("experiment-prompt").value = "Edited historian prompt";
    get("experiment-prompt").fire("input", "Edited historian prompt");
    assert.equal(get("results-view").hidden, true);
    get("experiment-perspectives").children[0].fire("click");
    assert.equal(get("run-experiment").disabled, false);
    assert.equal(get("experiment-prompt").value, "Synthetic role-play prompt for four applicants");
    get("experiment-perspectives").children[1].fire("click");
    assert.equal(get("run-experiment").disabled, true);
    assert.equal(get("experiment-prompt").value, "Edited historian prompt");
    get("experiment-prompt").value = "Synthetic historian prompt for four applicants";
    get("experiment-prompt").fire("input", get("experiment-prompt").value);
    URL.createObjectURL = blob => {downloadBlob = blob; return createUrl(blob);};
    try {get("download-results").fire("click");} finally {URL.createObjectURL = createUrl;}
    assert.match(downloadLinks.at(-1).download, /-historian-candidate-results.csv$/);
    const historianCsv = await downloadBlob.text();
    assert.ok(historianCsv.includes('"Historian"') && historianCsv.includes('"answer_probability_pct"'));
    assert.ok(!historianCsv.includes('"Role-play"'));
    assert.ok(historianCsv.includes('"synthetic-candidate-4"'));
    assert.ok(historianCsv.includes('"synthetic-request-controls-4-4-experienced-historian"'));
    assert.ok(historianCsv.includes("Perspective: historian"));
    assert.ok(!historianCsv.includes("…"));
    get("prompt-name").fire("click");
    assert.equal(get("population-help").hidden, false);
    assert.equal(get("prompt-name").attributes["aria-expanded"], "true");
    get("interactive-prompt").events.keydown({key: "Escape"});
    assert.equal(get("population-help").hidden, true);
    assert.equal(get("prompt-name").focused, true);
    for (const id of ["prompt-education", "prompt-dates"]) {
      get(id).fire("click");
      assert.equal(get("population-help").hidden, false);
      get("interactive-prompt").events.keydown({key: "Escape"});
      assert.equal(get(id).focused, true);
    }
    get("prompt-address").fire("click");
    get("go-to-population").fire("click");
    assert.equal(new URL(globalThis.location.href).hash, "#population");
    assert.equal(get("population-heading").focused, true);
    get("paper-select").fire("change", secondDemo.id);
    assert.equal(get("interactive-prompt").hidden, true);
    assert.equal(get("variant-prompt").hidden, false);
    assert.equal(get("experiment-result").hidden, true);
    globalThis.location.href = `https://example.org/kit/?paper=${controlledPaper.id}#resumes`;
    windowEvents.popstate();
    assert.equal(get("resume-count").value, "4");
    assert.equal(get("job-skill-count").value, "4");
    assert.equal(get("experience-level").value, "experienced");
    assert.equal(get("experiment-perspectives").children[1].attributes["aria-pressed"], "true");
    get("resume-count").value = "999";
    get("resume-count").fire("change", "999");
    assert.equal(get("generate-resume").disabled, true);
    assert.equal(get("experiment-view").hidden, true);
    assert.equal(get("results-view").hidden, true);
    get("resume-count").value = "2";
    get("resume-count").fire("change", "2");
    assert.equal(get("generate-resume").disabled, false);
    assert.equal(get("populated-document").children.length, 2);
    assert.equal(get("final-output-rows").children.length, 2);
    assert.equal(get("experiment-decisions").children.length, 0);
    assert.equal(get("experiment-prompt").value, "Synthetic historian prompt for two applicants");
    assert.equal(fetches, 1); // All supported choices are local saved examples.
    bundle.newspapers[0].resumeDemo.jobId = "hidden-job-2";
    globalThis.location.href = "https://example.org/kit/?paper=" + bundle.newspapers[0].id + "#resumes";
    windowEvents.popstate();
    assert.equal(get("variant-prompt").value, bundle.newspapers[0].resumeDemo.variants[0].prompt);
    assert.equal(get("resume-source").hidden, true);
    assert.equal(get("resume-source-text").hidden, false);
    assert.equal(get("resume-source-text").textContent, "Nursing hidden job 2");
    assert.equal(get("resume-source-image").src, "");
    assert.equal(get("experiment-view").hidden, true);
  } finally {
    for (const [key, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});
}
