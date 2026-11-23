// Pure, dependency-free view/data helpers. IDs always come from the source bundle.
export const CSV_COLUMNS = Object.freeze([
  "ad_id", "Text", "raw_text", "city", "year", "publication_date", "source_page", "source_url", "review_required",
]);
export const RESULT_COLUMNS = Object.freeze([
  "preset", "candidate_name", "decision", "answer", "logprob", "model",
  "variant_id", "candidate_id", "template_id", "scenario_id", "request_id",
  "experiment_id", "model_config_id", "provider", "source_ad_id", "address", "explanation",
]);

// Explicitly fictional presentation examples, not a researcher sampling design.
export const DEMO_CANDIDATES = Object.freeze([
  Object.freeze({id: "synthetic-candidate-1", label: "Candidate 1", name: "Alex Morgan", address: "12 Example Street"}),
  Object.freeze({id: "synthetic-candidate-2", label: "Candidate 2", name: "Jordan Taylor", address: "48 Sample Avenue"}),
  Object.freeze({id: "synthetic-candidate-3", label: "Candidate 3", name: "Casey Lee", address: "16 Practice Road"}),
  Object.freeze({id: "synthetic-candidate-4", label: "Candidate 4", name: "Riley Parker", address: "72 Demo Lane"}),
]);

export function formatDate(date) {
  return new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"})
    .format(new Date(`${date}T12:00:00Z`));
}

export function filterRecords(records, query) {
  const words = String(query).trim().toLocaleLowerCase("en").split(/\s+/).filter(Boolean);
  return records.filter(record => {
    const content = [record.id, record.code, record.title, record.employer, record.text, record.rawText].join(" ").toLocaleLowerCase("en");
    return words.every(word => content.includes(word));
  });
}

export function jobPreview(paper, query) {
  const matches = filterRecords(paper.records, query);
  if (String(query).trim()) return {matches, visible: matches.slice(0, 3)};
  const featured = new Set(paper.featuredIds || []);
  // Keep explicit researcher/demo ordering rather than the full export's sort.
  const byId = new Map(matches.map(record => [record.id, record]));
  const preferred = [...new Set(paper.featuredIds || [])].map(id => byId.get(id)).filter(Boolean);
  return {matches, visible: [...preferred, ...matches.filter(record => !featured.has(record.id))].slice(0, 3)};
}

export function chooseRecord(records, requestedId) {
  return records.find(record => record.id === requestedId) ?? records[0] ?? null;
}

export function normalizedBox(paper, record) {
  const [x, y, width, height] = record.bbox;
  if (![x, y, width, height, paper.imageWidth, paper.imageHeight].every(Number.isFinite)
      || x < 0 || y < 0 || width <= 0 || height <= 0 || paper.imageWidth <= 0 || paper.imageHeight <= 0
      || x + width > paper.imageWidth || y + height > paper.imageHeight) {
    throw new Error("Invalid source region");
  }
  return {left: x / paper.imageWidth * 100, top: y / paper.imageHeight * 100,
    width: width / paper.imageWidth * 100, height: height / paper.imageHeight * 100};
}

export function csvForRecords(paper, records) {
  // Protect spreadsheet readers from formula execution while preserving ordinary
  // archival text. Never treat a row position or visible code as durable identity.
  const quote = value => {
    let text = String(value);
    if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const rows = records.map(record => [record.id, record.text, record.rawText || paper.rawText || "", paper.city,
    paper.date.slice(0, 4), paper.date, paper.pageLabel, paper.sourceUrl, record.reviewRequired]);
  return [CSV_COLUMNS, ...rows].map(row => row.map(quote).join(",")).join("\r\n") + "\r\n";
}

export function stateFromUrl(url, papers) {
  const parsed = new URL(url);
  const paper = papers.find(item => item.id === parsed.searchParams.get("paper")) ?? papers[0];
  const demo = resumeDemo(paper);
  const population = populationExamples(demo?.variants[0]);
  const step = parsed.hash === "#results" && finalOutputRows(paper).length ? "results"
    : parsed.hash === "#experiment" && experimentExample(paper, demo?.variants[0]) ? "experiment"
    : parsed.hash === "#population" && population !== null ? "population"
    : parsed.hash === "#resumes" && demo ? "resumes"
    : parsed.hash === "#data" ? "data" : "archive";
  return {paperId: paper.id, step};
}

export function resumeDemo(paper) {
  const demo = paper.resumeDemo;
  const job = paper.records.find(record => record.id === demo?.jobId);
  if (!job || !Array.isArray(demo?.variants) || !demo.variants.length) return null;
  const ids = new Set();
  for (const variant of demo.variants) {
    if (typeof variant.id !== "string" || !variant.id.trim() || ids.has(variant.id)
        || typeof variant.label !== "string" || !variant.label.trim()
        || typeof variant.prompt !== "string" || !variant.prompt.trim()
        || (variant.promptSummary !== undefined && (typeof variant.promptSummary !== "string" || !variant.promptSummary.trim()))) return null;
    ids.add(variant.id);
  }
  if (demo.inlineControls === true) {
    const keys = new Set();
    for (const variant of demo.variants) {
      const settings = variant.settings;
      if (!validResumeSettings(settings) || resumeTemplates(variant).length !== settings.resumes) return null;
      keys.add(JSON.stringify([settings.resumes, settings.jobSkills, settings.experience]));
    }
    if (demo.variants.length !== 8 || keys.size !== 8) return null;
  }
  return {...demo, jobTitle: job.title};
}

function validResumeSettings(settings) {
  return settings && [2, 4].includes(settings.resumes) && [2, 4].includes(settings.jobSkills)
    && ["entry-level", "experienced"].includes(settings.experience);
}

export function inlineResumeVariant(demo, settings) {
  if (!demo?.inlineControls || !validResumeSettings(settings)) return null;
  const matches = demo.variants.filter(variant => variant.settings?.resumes === settings.resumes
    && variant.settings?.jobSkills === settings.jobSkills && variant.settings?.experience === settings.experience);
  return matches.length === 1 ? matches[0] : null;
}

export function cropStyle(paper, record) {
  const box = normalizedBox(paper, record);
  return {width: `${10000 / box.width}%`, left: `${-box.left / box.width * 100}%`,
    top: "0", transform: `translateY(${-box.top}%)`};
}

// Summary text is presentation only; full prompts remain bound to saved results.
export function resumePromptText(variant) {
  return variant?.promptSummary ?? variant?.prompt ?? "";
}

export function savedResumeVariant(demo, variantId, prompt) {
  return demo?.variants.find(variant => variant.id === variantId
    && resumePromptText(variant) === prompt && resumeTemplates(variant).length) ?? null;
}

export function resumeTemplates(variant) {
  if (!variant) return [];
  if (variant.templates === undefined) return typeof variant.template === "string" && variant.template.trim()
    ? [{id: "single-template-preview", text: variant.template}] : [];
  if (!Array.isArray(variant.templates) || !variant.templates.length
      || variant.templates.some(template => !template || typeof template.id !== "string" || !template.id.trim()
        || typeof template.text !== "string" || !template.text.trim())
      || new Set(variant.templates.map(template => template.id)).size !== variant.templates.length
      || new Set(variant.templates.map(template => template.text.trim())).size !== variant.templates.length
      || variant.template !== variant.templates[0].text) return [];
  if (variant.placeholderFields !== undefined) {
    const fields = variant.placeholderFields;
    if (!Array.isArray(fields) || !fields.includes("name") || !fields.includes("address")
        || fields.some(field => typeof field !== "string" || !/^[a-z_]+$/.test(field))
        || new Set(fields).size !== fields.length) return [];
    for (const template of variant.templates) {
      const used = new Set(resumeTextParts(template.text).filter(part => part.placeholder).map(part => part.text.slice(2, -2)));
      if (used.size !== fields.length || fields.some(field => !used.has(field))) return [];
    }
  }
  return variant.templates;
}

export function populationExamples(variant) {
  const templates = resumeTemplates(variant);
  const assignments = variant?.assignments;
  const pools = variant?.populationPools;
  if (pools !== undefined && (!pools || ![pools.addresses, pools.schools].every(values => Array.isArray(values)
      && values.length && values.every(value => typeof value === "string" && value.trim()))
      || !Array.isArray(pools.dates) || !pools.dates.length || pools.dates.some(preset => !preset
        || typeof preset.label !== "string" || !preset.label.trim() || !preset.values || typeof preset.values !== "object"
        || Array.isArray(preset.values) || Object.values(preset.values).some(value => typeof value !== "string" || !value.trim())))) return null;
  const count = templates.length;
  if (![2, 4].includes(count) || !Array.isArray(assignments)
      || assignments.length !== count || assignments.some(assignment => !assignment)
      || new Set(assignments.map(item => item.candidateId)).size !== count
      || new Set(assignments.map(item => item.templateId)).size !== count) return null;
  const examples = DEMO_CANDIDATES.slice(0, count).map(candidate => {
    const assignment = assignments.find(item => item.candidateId === candidate.id);
    const template = templates.find(item => item.id === assignment?.templateId);
    const values = assignment?.values ?? {};
    if (variant.placeholderFields && (Object.keys(values).length !== variant.placeholderFields.length - 2
        || Object.keys(values).some(field => !variant.placeholderFields.includes(field)))) return null;
    const address = assignment?.address ?? candidate.address;
    if (typeof address !== "string" || !address.trim()
        || (pools && !pools.addresses.includes(address))) return null;
    if (pools) {
      const school = values.university ?? values.high_school;
      const dates = Object.fromEntries(Object.entries(values).filter(([key]) => key === "work_end" || /_(month|year)$/.test(key)));
      if (!pools.schools.includes(school) || !pools.dates.some(preset => Object.keys(preset.values).length === Object.keys(dates).length
        && Object.entries(dates).every(([key, value]) => preset.values[key] === value))) return null;
    }
    const populated = {...candidate, address, values};
    const resume = populateResumeExample(template?.text, populated);
    return resume === null ? null : {...populated, templateId: template.id, template: template.text, resume};
  });
  return examples.some(example => !example) ? null : examples;
}

// Presentation only: keep saved prose/placeholders, interpret headings and lists.
export function resumeTextParts(text) {
  return String(text).split(/(\{\{[A-Za-z_][A-Za-z0-9_]*\}\})/g).filter(Boolean)
    .map(text => ({text, placeholder: /^\{\{[A-Za-z_][A-Za-z0-9_]*\}\}$/.test(text)}));
}

export function populateResumeExample(template, candidate) {
  if (typeof template !== "string" || !template.includes("{{name}}") || !template.includes("{{address}}")
      || !candidate || ![candidate.name, candidate.address].every(value => typeof value === "string" && value.trim())) return null;
  const extra = candidate.values ?? {};
  if (typeof extra !== "object" || Array.isArray(extra) || Object.hasOwn(extra, "name") || Object.hasOwn(extra, "address")
      || Object.values(extra).some(value => typeof value !== "string" || !value.trim() || value.includes("{{"))) return null;
  const values = {...extra, name: candidate.name, address: candidate.address};
  const parts = resumeTextParts(template);
  if (parts.some(part => part.placeholder && !Object.hasOwn(values, part.text.slice(2, -2)))) return null;
  const used = new Set(parts.filter(part => part.placeholder).map(part => part.text.slice(2, -2)));
  if (Object.keys(extra).some(field => !used.has(field))) return null;
  return parts.map(part => part.placeholder ? values[part.text.slice(2, -2)] : part.text).join("");
}

// Small explicit presentation presets, never researcher sampling assignments.
export function candidateFieldPresets(candidate, population, field, pools = null) {
  if (!candidate || !population?.some(item => item.id === candidate.id)) return [];
  if (pools && field === "address") return (pools.addresses ?? []).map(value => ({label: value, changes: {address: value}}));
  if (pools && ["university", "high_school"].includes(field))
    return (pools.schools ?? []).map(value => ({label: value, changes: {values: {[field]: value}}}));
  if (pools && (field === "work_end" || /_(month|year)$/.test(field))) {
    const fields = Object.keys(candidate.values).filter(key => key === "work_end" || /_(month|year)$/.test(key));
    return (pools.dates ?? []).filter(preset => preset && typeof preset.label === "string" && preset.values
      && Object.keys(preset.values).length === fields.length && fields.every(key => typeof preset.values[key] === "string" && preset.values[key].trim()))
      .map(preset => ({label: preset.label, changes: {values: {...preset.values}}}));
  }
  if (field === "name" || field === "address") return DEMO_CANDIDATES.map(profile => ({
    label: profile[field], changes: {[field]: profile[field]},
  }));
  if (["university", "high_school"].includes(field) && Object.hasOwn(candidate.values, field))
    return [...new Set(population.map(item => item.values[field]))].map(value => ({label: value, changes: {values: {[field]: value}}}));
  if (Object.hasOwn(candidate.values, field) && /_(month|year)$/.test(field)) {
    const dates = Object.fromEntries(Object.entries(candidate.values).filter(([key]) => /_(month|year)$/.test(key)));
    if (Object.entries(dates).some(([key, value]) => !value || (key.endsWith("year") && !/^\d{4}$/.test(value)))) return [];
    const earlier = Object.fromEntries(Object.entries(dates).map(([key, value]) => [key,
      key.endsWith("year") && key !== "work_end_year" ? String(Number(value) - 1) : value]));
    return [{label: "Original dates", changes: {values: dates}}, {label: "Start one year earlier", changes: {values: earlier}}];
  }
  return [];
}

export function replaceCandidateFields(candidate, changes) {
  if (!candidate || !changes || Object.keys(changes).some(key => !["name", "address", "values"].includes(key))) return null;
  if (changes.values !== undefined && (!changes.values || typeof changes.values !== "object" || Array.isArray(changes.values))) return null;
  const result = {...candidate, ...changes, values: {...candidate.values, ...changes.values}};
  const resume = populateResumeExample(result.template, result);
  return resume === null ? null : {...result, resume};
}

export function experimentExample(paper, variant) {
  const demo = paper.experimentDemo;
  const population = populationExamples(variant);
  if (!population || !demo || typeof demo.prompt !== "string" || !demo.prompt.trim()
      || !Array.isArray(demo.examples)) return null;
  const matches = demo.examples.filter(example => example?.variantId === variant.id);
  if (matches.length !== 1) return null;
  const example = matches[0];
  const job = paper.records.find(record => record.id === paper.resumeDemo?.jobId);
  const expectedPrompt = variant.experimentPrompt ?? demo.prompt;
  if (!job || example.jobId !== job.id || example.jobPosting !== job.text || example.prompt !== expectedPrompt
      || example.generationPrompt !== variant.prompt || example.template !== variant.template
      || (variant.systemPrompt !== undefined && example.generationSystemPrompt !== variant.systemPrompt)
      || !Array.isArray(example.candidates) || example.candidates.length !== population.length
      || !Array.isArray(example.decisions) || example.decisions.length !== population.length) return null;
  for (const field of ["explanation", "requestId", "scenarioId", "experimentId", "modelConfigId", "model", "provider"])
    if (typeof example[field] !== "string" || !example[field].trim()) return null;
  for (const [index, candidate] of population.entries()) {
    const input = example.candidates[index];
    const decision = example.decisions[index];
    if (!input || !decision || ["id", "label", "name", "address"].some(field => input[field] !== candidate[field])
        || input.templateId !== population[index].templateId || input.resume !== population[index].resume
        || input.resume === null || decision.candidateId !== candidate.id
        || typeof decision.invite !== "boolean" || !Number.isFinite(decision.logprob) || decision.logprob > 0) return null;
  }
  return example;
}

export function finalOutputRows(paper, variantId) {
  const demo = resumeDemo(paper);
  if (!demo) return [];
  const variants = variantId === undefined ? demo.variants : demo.variants.filter(variant => variant.id === variantId);
  if (!variants.length) return [];
  const examples = variants.map(variant => experimentExample(paper, variant));
  if (examples.some(example => !example)) return [];
  return examples.flatMap((example, presetIndex) => example.decisions.map((decision, index) => ({
    preset: variants[presetIndex].label,
    candidate_name: example.candidates[index].name,
    decision: decision.invite ? 1 : 0, answer: decision.invite ? "Yes" : "No",
    logprob: decision.logprob, model: example.model, variant_id: example.variantId,
    candidate_id: decision.candidateId, template_id: example.candidates[index].templateId,
    scenario_id: example.scenarioId, request_id: example.requestId,
    experiment_id: example.experimentId, model_config_id: example.modelConfigId,
    provider: example.provider, source_ad_id: example.jobId,
    address: example.candidates[index].address, explanation: example.explanation,
  })));
}

export function resultCsv(rows) {
  const quote = value => {
    let text = String(value ?? "");
    if (typeof value !== "number" && /^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  return [RESULT_COLUMNS, ...rows.map(row => RESULT_COLUMNS.map(column => row[column]))]
    .map(row => row.map(quote).join(",")).join("\r\n") + "\r\n";
}

export function resumeBlocks(text) {
  const lines = String(text).replaceAll("\r\n", "\n").split("\n").map(line => line.trim());
  const blocks = [];
  let index = 0;
  while (index < lines.length && !lines[index]) index++;
  if (lines[index] === "{{name}}") {
    const contact = [];
    while (index < lines.length && /^\{\{[a-zA-Z0-9_]+\}\}$/.test(lines[index])) contact.push(lines[index++]);
    blocks.push({kind: "contact", lines: contact});
  }
  for (; index < lines.length; index++) {
    const line = lines[index];
    if (!line) continue;
    if (/^[-•]\s+/.test(line)) {
      const previous = blocks.at(-1);
      if (previous?.kind === "list" && lines[index - 1]) previous.items.push(line.replace(/^[-•]\s+/, ""));
      else blocks.push({kind: "list", items: [line.replace(/^[-•]\s+/, "")]});
    } else if (line.length <= 64 && /^[A-Z][A-Z\s&/()-]*$/.test(line)) {
      blocks.push({kind: "heading", text: line});
    } else blocks.push({kind: "paragraph", text: line});
  }
  return blocks;
}

// Private bundles are only requested on loopback; Pages uses reviewed public assets.
export async function loadBundle(fetcher, hostname, publicUrl, localUrl) {
  if (["localhost", "127.0.0.1", "[::1]"].includes(hostname)) {
    const local = await fetcher(localUrl, {cache: "no-cache"});
    if (local.ok) {
      const bundle = await local.json();
      if (!bundle.newspapers?.length) throw new Error("Empty local newspaper bundle");
      return bundle;
    }
    if (local.status !== 404) throw new Error("Cannot load local newspaper bundle");
  }
  const response = await fetcher(publicUrl, {cache: "no-cache"});
  if (!response.ok) throw new Error("Cannot load public newspaper bundle");
  const bundle = await response.json();
  if (!bundle.newspapers?.length) throw new Error("Empty public newspaper bundle");
  return bundle;
}
