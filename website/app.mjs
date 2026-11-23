import {csvForRecords, jobPreview, cropStyle, stateFromUrl, loadBundle, resumeDemo, savedResumeVariant, resumePromptText, inlineResumeVariant, resumeBlocks, resumeTextParts, populationExamples, resumeTemplates, experimentExample, experimentPerspectives, formatAnswerProbability, finalOutputRows, resultCsv, candidateFieldPresets, replaceCandidateFields} from "./lib.mjs?v=experiment-artifacts-30";

const $ = id => document.getElementById(id);
const state = {papers: [], paperId: null, step: "archive", query: "", variantId: null, perspectiveId: null};
const promptDrafts = new Map();
const experimentDrafts = new Map();
const selectedSettings = new Map();
const selectedPerspectives = new Map();
const candidateEdits = new Map();
const fieldTriggers = new Map();
let activeFieldTrigger = null;
let placeholderTrigger = null;
const paper = () => state.papers.find(item => item.id === state.paperId);
const draftKey = (demo, variantId) => JSON.stringify([state.paperId, demo.jobId, variantId]);
const perspectiveKey = () => JSON.stringify([state.paperId, paper().resumeDemo?.jobId]);
const experimentDraftKey = () => JSON.stringify([state.paperId, paper().resumeDemo?.jobId, state.variantId, state.perspectiveId]);

function syncUrl(push = false) {
  const url = new URL(location.href);
  url.searchParams.set("paper", state.paperId);
  url.hash = state.step;
  history[push ? "pushState" : "replaceState"]({}, "", url);
}

function render() {
  const selected = paper();
  $("paper-select").value = selected.id;
  $("archive-view").hidden = false;
  $("data-view").hidden = false;
  $("scan-image").src = selected.imageSrc;
  $("scan-image").alt = `${selected.title}, ${selected.date}, ${selected.pageLabel}`;
  $("source-footer").hidden = !selected.sourceUrl;
  if (selected.sourceUrl) $("archive-source").href = selected.sourceUrl;
  renderJobs();
  renderResumes();
}

function renderResumes() {
  candidateEdits.clear(); $("candidate-field-dialog").close();
  const perspectives = experimentPerspectives(paper());
  state.perspectiveId = selectedPerspectives.get(perspectiveKey()) ?? perspectives[0]?.id ?? null;
  $("resume-dialog").close();
  $("resume-document").replaceChildren();
  $("resume-template-options").replaceChildren();
  const demo = resumeDemo(paper());
  closePopulationHelp();
  $("interactive-prompt").hidden = !demo?.inlineControls;
  $("variant-prompt").hidden = Boolean(demo?.inlineControls);
  $("resume-view").hidden = !demo;
  $("resume-connector").hidden = !demo;
  if (!demo) {
    state.variantId = null;
    $("prompt-variants").replaceChildren();
    $("prompt-variants").hidden = true;
    $("variant-prompt").value = "";
    $("resume-source-image").src = "";
    $("resume-source-image").alt = "";
    $("resume-source-text").textContent = "";
    $("generate-resume").disabled = true;
    renderPopulation(null);
    return;
  }
  const job = paper().records.find(record => record.id === demo.jobId);
  const hasCrop = Array.isArray(job.bbox);
  $("resume-source").hidden = !hasCrop;
  $("resume-source-text").hidden = hasCrop;
  $("resume-source-text").textContent = hasCrop ? "" : job.text;
  if (hasCrop) {
    $("resume-source").style.aspectRatio = `${job.bbox[2]} / ${job.bbox[3]}`;
    $("resume-source-image").src = paper().imageSrc;
    $("resume-source-image").alt = job.cropMethod === "approximate-ocr-text-alignment"
      ? `Approximate newspaper source area for ${job.title}` : `Source advertisement for ${job.title}`;
    $("resume-source").title = job.cropMethod === "approximate-ocr-text-alignment"
      ? "Approximate source area; may include neighboring ads. Enlarge posting" : "Enlarge posting";
    Object.assign($("resume-source-image").style, cropStyle(paper(), job));
  } else {
    $("resume-source-image").src = "";
    $("resume-source-image").alt = "";
  }
  $("prompt-variants").hidden = Boolean(demo.inlineControls) || demo.variants.length < 2;
  if (demo.inlineControls) state.variantId = selectedSettings.get(JSON.stringify([state.paperId, demo.jobId])) ?? null;
  $("prompt-variants").replaceChildren(...demo.variants.map(variant => {
    const button = document.createElement("button");
    button.type = "button"; button.className = "variant-button";
    button.dataset.variantId = variant.id; button.textContent = variant.label;
    button.addEventListener("click", () => {state.variantId = variant.id; renderVariant(demo);});
    return button;
  }));
  renderVariant(demo);
}

function renderVariant(demo) {
  candidateEdits.clear(); $("candidate-field-dialog").close();
  const key = JSON.stringify([state.paperId, demo.jobId]);
  const variant = demo.variants.find(item => item.id === state.variantId)
    || (demo.inlineControls && demo.variants.find(item => item.id === selectedSettings.get(key))) || demo.variants[0];
  state.variantId = variant.id;
  if (demo.inlineControls) {
    selectedSettings.set(key, variant.id);
    $("resume-count").value = String(variant.settings.resumes);
    $("job-skill-count").value = String(variant.settings.jobSkills);
    $("experience-level").value = variant.settings.experience;
    $("prompt-location").textContent = `${paper().city}, ${paper().date.slice(0, 4)}`;
    $("prompt-education").textContent = variant.placeholderFields?.includes("high_school") ? "school" : "university";
  }
  for (const button of $("prompt-variants").children) {
    button.setAttribute("aria-pressed", String(button.dataset.variantId === variant.id));
  }
  $("variant-prompt").value = promptDrafts.get(draftKey(demo, variant.id)) ?? resumePromptText(variant);
  updateResumeButton(demo);
}

function changeInlineSettings() {
  candidateEdits.clear(); $("candidate-field-dialog").close();
  const demo = resumeDemo(paper());
  const variant = inlineResumeVariant(demo, {resumes: Number($("resume-count").value),
    jobSkills: Number($("job-skill-count").value), experience: $("experience-level").value});
  closePopulationHelp();
  $("resume-dialog").close(); $("resume-document").replaceChildren(); $("resume-template-options").replaceChildren();
  if (!variant) {
    state.variantId = null; $("variant-prompt").value = ""; $("generate-resume").disabled = true;
    renderPopulation(null); return;
  }
  state.variantId = variant.id; renderVariant(demo);
}

function closePopulationHelp() {
  $("population-help").hidden = true;
  for (const id of ["prompt-name", "prompt-address", "prompt-education", "prompt-dates"])
    $(id).setAttribute("aria-expanded", "false");
}

function updateResumeButton(demo) {
  const saved = savedResumeVariant(demo, state.variantId, $("variant-prompt").value);
  $("generate-resume").disabled = !saved;
  $("generate-resume").title = saved ? "Inspect previously generated templates for these settings; no live generation."
    : "Saved examples are available for the original prompt summary only; live generation is not connected.";
  renderPopulation(saved);
}

function showResume() {
  const saved = savedResumeVariant(resumeDemo(paper()), state.variantId, $("variant-prompt").value);
  if (!saved) return;
  const templates = resumeTemplates(saved);
  const selectTemplate = id => {
    const selected = templates.find(template => template.id === id);
    renderResumeDocument($("resume-document"), selected.text);
    for (const button of $("resume-template-options").children)
      button.setAttribute("aria-pressed", String(button.dataset.templateId === id));
  };
  $("resume-template-options").replaceChildren(...templates.map((template, index) => {
    const button = document.createElement("button"); button.type = "button";
    button.className = "variant-button"; button.dataset.templateId = template.id;
    button.textContent = `Template ${index + 1}`;
    button.addEventListener("click", () => selectTemplate(template.id));
    return button;
  }));
  selectTemplate(templates[0].id);
  $("resume-dialog-title").textContent = "Saved resume example";
  $("resume-dialog").showModal();
  $("resume-dialog").scrollTo(0, 0);
}

function renderPopulation(saved) {
  const population = currentPopulation(saved);
  const available = population !== null;
  fieldTriggers.clear();
  $("go-to-population").disabled = !available;
  $("population-caption").hidden = !candidateEdits.size;
  $("population-caption").textContent = candidateEdits.size ? "Reset details to see saved model results." : "";
  $("reset-candidates").disabled = !candidateEdits.size;
  $("population-view").hidden = !available;
  $("population-connector").hidden = !available;
  renderExperiment(available ? saved : null);
  if (!available) {
    $("populated-document").replaceChildren();
    $("candidate-status").textContent = "";
    if (state.step === "population") {
      state.step = $("resume-view").hidden ? "archive" : "resumes";
      syncUrl();
    }
    return;
  }
  $("populated-document").replaceChildren(...population.map(candidate => {
    const card = document.createElement("section"); card.className = "resume-sheet";
    card.dataset.candidateId = candidate.id;
    const heading = document.createElement("div"); heading.className = "resume-sheet-toolbar";
    const label = document.createElement("h3"); label.textContent = candidate.label;
    const enlarge = document.createElement("button"); enlarge.type = "button"; enlarge.textContent = "View full resume";
    enlarge.setAttribute("aria-label", `View full resume for ${candidate.label}`);
    enlarge.addEventListener("click", () => showPopulatedCandidate(candidate));
    heading.append(label, enlarge);
    const doc = document.createElement("article"); doc.className = "typeset-resume populated-resume";
    doc.setAttribute("aria-label", `${candidate.label} resume`);
    renderResumeDocument(doc, candidate.template, candidate, candidateEdits.has(candidate.id), (field, trigger) => openCandidateField(saved, candidate.id, field, trigger));
    card.append(heading, doc); return card;
  }));
}

function currentPopulation(saved) {
  return populationExamples(saved)?.map(candidate => candidateEdits.get(candidate.id) ?? candidate) ?? null;
}

function openCandidateField(saved, candidateId, field, trigger) {
  const baseline = populationExamples(saved);
  const original = baseline.find(candidate => candidate.id === candidateId);
  const candidate = currentPopulation(saved).find(candidate => candidate.id === candidateId);
  const presets = candidateFieldPresets(original, baseline, field, saved.populationPools);
  if (!presets.length) return;
  activeFieldTrigger = trigger;
  $("candidate-field-title").textContent = field === "work_end" || /_(month|year)$/.test(field) ? "Change dates" : `Change ${field === "high_school" ? "school" : field}`;
  $("candidate-field-options").replaceChildren(...presets.map(preset => {
    const button = document.createElement("button"); button.type = "button"; button.textContent = preset.label;
    button.addEventListener("click", () => {
      const updated = replaceCandidateFields(candidate, preset.changes);
      if (!updated) return;
      if (updated.resume === original.resume) candidateEdits.delete(candidateId); else candidateEdits.set(candidateId, updated);
      $("candidate-field-dialog").close(); renderPopulation(saved);
      $("candidate-status").textContent = `${candidate.label} details updated. ${candidateEdits.size ? "Reset details to see the saved model evaluation." : "Original details restored."}`;
      fieldTriggers.get(trigger.dataset.triggerKey)?.focus();
    }); return button;
  }));
  $("candidate-field-dialog").showModal();
}

function currentExperiment() {
  const saved = savedResumeVariant(resumeDemo(paper()), state.variantId, $("variant-prompt").value);
  const example = experimentExample(paper(), saved, state.perspectiveId);
  const population = currentPopulation(saved);
  return example && population?.every((candidate, index) => candidate.resume === example.candidates[index].resume) ? example : null;
}

function clearExperimentResult() {
  $("experiment-result").hidden = true;
  $("experiment-decisions").replaceChildren();
  $("experiment-explanation").textContent = "";
}

function renderExperiment(saved) {
  const perspectives = experimentPerspectives(paper());
  $("experiment-perspectives").hidden = !perspectives.length;
  $("experiment-perspectives").replaceChildren(...perspectives.map(perspective => {
    const button = document.createElement("button"); button.type = "button"; button.className = "variant-button";
    button.textContent = perspective.label; button.dataset.perspectiveId = perspective.id;
    button.setAttribute("aria-pressed", String(state.perspectiveId === perspective.id));
    button.addEventListener("click", () => {
      state.perspectiveId = perspective.id; selectedPerspectives.set(perspectiveKey(), perspective.id);
      renderExperiment(saved);
    }); return button;
  }));
  const example = saved ? currentExperiment() : null;
  $("experiment-view").hidden = !example;
  $("experiment-connector").hidden = !example;
  clearExperimentResult();
  if (!example) {
    $("experiment-prompt").value = "";
    $("experiment-model").textContent = "";
    $("experiment-status").textContent = "";
    $("run-experiment").disabled = true;
    renderFinalOutput(false);
    if (state.step === "experiment") {
      state.step = !$("population-view").hidden ? "population" : !$("resume-view").hidden ? "resumes" : "archive";
      syncUrl();
    }
    return;
  }
  $("experiment-prompt").value = experimentDrafts.get(experimentDraftKey()) ?? example.prompt;
  $("experiment-model").textContent = example.model === "gpt-4o-2024-08-06" ? "GPT-4o" : example.model;
  $("experiment-model").title = `${example.model} · previously recorded response; no live generation.`;
  updateExperimentButton();
}

function updateExperimentButton() {
  clearExperimentResult();
  const example = currentExperiment();
  const matches = example && $("experiment-prompt").value === example.prompt;
  $("run-experiment").disabled = !matches;
  $("run-experiment").title = "Show the previously recorded response for these exact inputs; no live generation.";
  $("experiment-status").textContent = example && !matches
    ? "This saved run uses the original prompt. Live generation isn’t connected." : "";
  renderFinalOutput(Boolean(matches));
}

function renderFinalOutput(enabled) {
  const rows = enabled ? currentResultRows() : [];
  $("results-view").hidden = !rows.length;
  $("results-connector").hidden = !rows.length;
  $("download-results").disabled = !rows.length;
  const count = new Set(rows.map(row => row.variant_id)).size;
  $("results-count").textContent = rows.length ? `${rows.length} candidate evaluations · ${count} resume prompt${count === 1 ? "" : "s"}` : "";
  $("final-output-rows").replaceChildren(...rows.map(row => {
    const tr = document.createElement("tr");
    const values = [row.preset, row.candidate_name, row.answer, formatAnswerProbability(row.logprob), row.model === "gpt-4o-2024-08-06" ? "GPT-4o" : row.model];
    values.forEach((value, index) => {
      const td = document.createElement("td"); td.textContent = value;
      if (index === 3) {td.className = "numeric"; td.title = `${row.answer_probability_pct}% likelihood of the emitted ${row.answer} answer tokens`;}
      if (index === 4) td.title = row.model;
      tr.append(td);
    });
    return tr;
  }));
  if (!rows.length && state.step === "results") {
    state.step = !$("experiment-view").hidden ? "experiment" : !$("population-view").hidden ? "population" : !$("resume-view").hidden ? "resumes" : "archive";
    syncUrl();
  }
}

function currentResultRows() {
  return currentExperiment() ? finalOutputRows(paper(), resumeDemo(paper())?.inlineControls ? state.variantId : undefined, state.perspectiveId) : [];
}

function showExperimentResult() {
  const example = currentExperiment();
  if (!example || $("experiment-prompt").value !== example.prompt) return;
  $("experiment-decisions").replaceChildren(...example.decisions.map((decision, index) => {
    const row = document.createElement("div");
    const name = document.createElement("h4"); name.textContent = `${example.candidates[index].label} · ${example.candidates[index].name}`;
    const answer = document.createElement("p"); answer.textContent = decision.invite ? "Invite to interview" : "Do not invite";
    const probability = document.createElement("p"); probability.className = "decision-probability";
    probability.textContent = `${formatAnswerProbability(decision.logprob)} answer probability`;
    row.append(name, answer, probability); return row;
  }));
  $("experiment-explanation").textContent = example.explanation;
  $("experiment-result").hidden = false;
  $("experiment-result").scrollIntoView({behavior: "instant", block: "nearest"});
}

function showPopulatedCandidate(candidate) {
  $("resume-dialog-title").textContent = candidate.label;
  $("resume-template-options").replaceChildren();
  renderResumeDocument($("resume-document"), candidate.template, candidate);
  $("resume-dialog").showModal(); $("resume-dialog").scrollTo(0, 0);
}

function renderResumeDocument(target, template, candidate = null, animate = false, edit = null) {
  let placeholderIndex = 0;
  const setText = (node, text) => {
    node.replaceChildren(...resumeTextParts(text).map(part => {
      const span = document.createElement(part.placeholder && candidate && edit ? "button" : "span"); span.textContent = part.text;
      if (part.placeholder && candidate) {
        const field = part.text.slice(2, -2);
        span.textContent = field === "name" || field === "address" ? candidate[field] : candidate.values[field];
        span.className = animate ? "candidate-value is-updated" : "candidate-value";
        if (edit) {
          span.type = "button"; span.dataset.field = field;
          span.setAttribute("aria-label", `Change ${field.replaceAll("_", " ")} for ${candidate.label}: ${span.textContent}`);
          span.addEventListener("click", () => edit(field, span));
          span.dataset.triggerKey = `${candidate.id}:${field}:${++placeholderIndex}`;
          fieldTriggers.set(span.dataset.triggerKey, span);
        }
      } else if (part.placeholder) {
        span.className = "resume-placeholder"; span.tabIndex = 0;
        const tip = document.createElement("span");
        tip.id = `placeholder-tip-${++placeholderIndex}`;
        tip.className = "placeholder-tooltip"; tip.setAttribute("role", "tooltip");
        tip.textContent = "Left blank on purpose! Close this preview and scroll down to see these details filled in.";
        span.setAttribute("aria-describedby", tip.id);
        span.append(tip);
        span.addEventListener("mouseenter", () => {span.dataset.dismissed = "false";});
        span.addEventListener("focus", () => {span.dataset.dismissed = "false";});
        span.addEventListener("keydown", event => {
          if (event.key === "Escape") {
            span.dataset.dismissed = "true";
            event.preventDefault(); event.stopPropagation();
          }
        });
      }
      return span;
    }));
  };
  target.replaceChildren(...resumeBlocks(template).map(block => {
    if (block.kind === "contact") {
      const header = document.createElement("header"); header.className = "resume-contact";
      block.lines.forEach((line, index) => {
        const node = document.createElement(index === 0 ? "h2" : "p");
        setText(node, line); header.append(node);
      });
      return header;
    }
    if (block.kind === "list") {
      const list = document.createElement("ul");
      block.items.forEach(text => {
        const item = document.createElement("li"); setText(item, text); list.append(item);
      });
      return list;
    }
    const node = document.createElement(block.kind === "heading" ? "h3" : "p");
    setText(node, block.text);
    return node;
  }));
}

function showScan(record = null) {
  $("enlarged-image").src = paper().imageSrc;
  $("enlarged-image").alt = record ? `Scanned ${record.title} advertisement` : $("scan-image").alt;
  Object.assign($("enlarged-image").style, record ? cropStyle(paper(), record)
    : {width: "100%", left: "0", top: "0", transform: "none"});
  $("enlarged-crop").style.aspectRatio = record ? `${record.bbox[2]} / ${record.bbox[3]}`
    : `${paper().imageWidth} / ${paper().imageHeight}`;
  $("enlarged-crop").style.width = "100%";
  $("image-dialog-title").textContent = record?.title || `${paper().city}, ${paper().date.slice(0, 4)}`;
  $("zoom-select").value = "100";
  $("image-dialog").showModal(); document.querySelector(".enlarged-scroll").scrollTo(0, 0);
}

function renderJobs() {
  const selected = paper();
  const {matches, visible} = jobPreview(selected, state.query);
  $("job-cards").replaceChildren(...visible.map(record => {
    const card = document.createElement("article");
    card.className = "job-card"; card.dataset.recordId = record.id;
    const crop = document.createElement("button"); crop.type = "button";
    const hasCrop = Array.isArray(record.bbox);
    crop.className = hasCrop ? "source-crop" : "text-preview";
    crop.setAttribute("aria-label", `Read full text for ${record.title}`);
    const approximate = record.cropMethod === "approximate-ocr-text-alignment";
    crop.title = approximate
      ? `Approximate source area; may include neighboring ads. Read ${record.title}`
      : `Read ${record.title}`;
    if (hasCrop) {
      crop.style.width = `min(100%, ${Math.min(300, 280 * record.bbox[2] / record.bbox[3])}px)`;
      crop.style.aspectRatio = `${record.bbox[2]} / ${record.bbox[3]}`;
      const image = document.createElement("img"); image.src = selected.imageSrc;
      image.alt = approximate ? `Approximate newspaper source area for ${record.title}`
        : `Source advertisement for ${record.title}`;
      Object.assign(image.style, cropStyle(selected, record));
      crop.append(image);
    } else {
      const label = document.createElement("small"); label.textContent = "Text preview";
      const title = document.createElement("strong"); title.textContent = record.title;
      const excerpt = document.createElement("p"); excerpt.textContent = record.text.slice(0, 180) + (record.text.length > 180 ? "…" : "");
      crop.append(label, title, excerpt);
    }
    crop.addEventListener("click", () => {
      $("job-dialog-title").textContent = record.title;
      $("job-full-text").textContent = record.text;
      $("job-dialog").showModal(); $("job-dialog").scrollTo(0, 0);
    });
    card.append(crop);
    return card;
  }));
  const category = state.query.trim() ? (matches.length === 1 ? "match" : "matches") : "jobs";
  $("results-summary").textContent = `Showing ${visible.length} of ${matches.length} ${category}`;
  $("empty-state").hidden = visible.length > 0;
  $("download-button").disabled = !visible.length;
}

function scrollToStep() {
  const target = state.step === "results" ? "results-view" : state.step === "experiment" ? "experiment-view" : state.step === "population" ? "population-view"
    : state.step === "resumes" ? "resume-view" : state.step === "data" ? "data-view" : "archive-view";
  $(target).scrollIntoView({
    behavior: "instant", block: "start",
  });
}

function setupScrollFlow() {
  // Normal document flow remains readable without animation support.
  if ("IntersectionObserver" in window) {
    const observer = new window.IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    }, {threshold: 0.08});
    document.querySelectorAll(".reveal").forEach(node => {
      node.classList.add("will-reveal"); observer.observe(node);
    });
  }
  window.addEventListener("scroll", () => {
    let step = $("data-view").getBoundingClientRect().top < window.innerHeight * 0.6 ? "data" : "archive";
    if (!$("resume-view").hidden && $("resume-view").getBoundingClientRect().top < window.innerHeight * 0.6) step = "resumes";
    if (!$("population-view").hidden && $("population-view").getBoundingClientRect().top < window.innerHeight * 0.6) step = "population";
    if (!$("experiment-view").hidden && $("experiment-view").getBoundingClientRect().top < window.innerHeight * 0.6) step = "experiment";
    if (!$("results-view").hidden && $("results-view").getBoundingClientRect().top < window.innerHeight * 0.6) step = "results";
    if (state.step !== step) {state.step = step; syncUrl();}
  }, {passive: true});
}

async function start() {
  const bundle = await loadBundle(fetch, location.hostname,
    new URL("./data/newspapers.json?v=experiment-artifacts-30", import.meta.url), new URL("./local/newspapers.json", import.meta.url));
  state.papers = bundle.newspapers;
  Object.assign(state, stateFromUrl(location.href, state.papers));
  $("paper-select").replaceChildren(...state.papers.map(item => {
    const option = document.createElement("option"); option.value = item.id;
    option.textContent = `${item.city}, ${item.date.slice(0, 4)}`;
    return option;
  }));
  $("paper-select").addEventListener("change", event => {
    state.paperId = event.target.value; state.variantId = null;
    state.query = ""; $("search-input").value = ""; render(); syncUrl(true);
  });
  $("search-input").addEventListener("input", event => {state.query = event.target.value; renderJobs();});
  $("variant-prompt").addEventListener("input", event => {
    const demo = resumeDemo(paper());
    if (demo && state.variantId) {
      promptDrafts.set(draftKey(demo, state.variantId), event.target.value);
      updateResumeButton(demo);
    }
  });
  $("generate-resume").addEventListener("click", showResume);
  for (const id of ["resume-count", "job-skill-count", "experience-level"])
    $(id).addEventListener("change", changeInlineSettings);
  for (const id of ["prompt-name", "prompt-address", "prompt-education", "prompt-dates"]) $(id).addEventListener("click", () => {
    placeholderTrigger = $(id);
    const open = $("population-help").hidden;
    closePopulationHelp(); $("population-help").hidden = !open;
    if (open) $(id).setAttribute("aria-expanded", "true");
  });
  $("interactive-prompt").addEventListener("keydown", event => {
    if (event.key === "Escape" && !$("population-help").hidden) {
      closePopulationHelp(); placeholderTrigger?.focus();
    }
  });
  $("go-to-population").addEventListener("click", () => {
    if ($("population-view").hidden) return;
    closePopulationHelp(); state.step = "population"; syncUrl(true); scrollToStep();
    $("population-heading").focus({preventScroll: true});
  });
  $("experiment-prompt").addEventListener("input", event => {
    experimentDrafts.set(experimentDraftKey(), event.target.value); updateExperimentButton();
  });
  $("run-experiment").addEventListener("click", showExperimentResult);
  $("download-results").addEventListener("click", () => {
    const example = currentExperiment();
    if (!example || $("experiment-prompt").value !== example.prompt) return;
    const rows = currentResultRows();
    if (!rows.length) return;
    const blob = new Blob([resultCsv(rows)], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = `${paper().id}${state.perspectiveId ? "-" + state.perspectiveId : ""}-candidate-results.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("reset-candidates").addEventListener("click", () => {
    candidateEdits.clear();
    const saved = savedResumeVariant(resumeDemo(paper()), state.variantId, $("variant-prompt").value);
    renderPopulation(saved); $("candidate-status").textContent = "Original applicant details restored.";
  });
  const closeCandidateField = () => {$("candidate-field-dialog").close(); activeFieldTrigger?.focus();};
  $("close-candidate-field").addEventListener("click", closeCandidateField);
  $("candidate-field-dialog").addEventListener("cancel", event => {event.preventDefault(); closeCandidateField();});
  $("close-resume-dialog").addEventListener("click", () => $("resume-dialog").close());
  $("resume-source").addEventListener("click", () => {
    const demo = resumeDemo(paper());
    const job = paper().records.find(record => record.id === demo?.jobId);
    if (Array.isArray(job?.bbox)) showScan(job);
  });
  $("download-button").addEventListener("click", () => {
    const blob = new Blob([csvForRecords(paper(), jobPreview(paper(), state.query).matches)], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = `${paper().id}-jobs.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("open-scan").addEventListener("click", () => showScan());
  $("zoom-select").addEventListener("change", event => {$("enlarged-crop").style.width = `${event.target.value}%`;});
  $("close-dialog").addEventListener("click", () => $("image-dialog").close());
  $("close-job-dialog").addEventListener("click", () => $("job-dialog").close());
  window.addEventListener("popstate", () => {
    Object.assign(state, stateFromUrl(location.href, state.papers)); state.query = "";
    $("search-input").value = ""; render(); scrollToStep();
  });
  $("load-status").hidden = true; render(); syncUrl(); setupScrollFlow();
  if (state.step !== "archive") scrollToStep();
}

start().catch(() => {
  $("load-status").hidden = false;
  $("load-status").textContent = "Could not load this preview. Reload the page to get the latest files.";
  $("resume-view").hidden = true;
  $("resume-connector").hidden = true;
  $("population-view").hidden = true;
  $("population-connector").hidden = true;
  $("experiment-view").hidden = true;
  $("experiment-connector").hidden = true;
  $("results-view").hidden = true;
  $("results-connector").hidden = true;
});
