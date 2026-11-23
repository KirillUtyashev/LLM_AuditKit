// Entirely synthetic unit-test responses; never presented as a live model run.
import {DEMO_CANDIDATES, populationExamples} from "../../website/lib.mjs";

export function pairedVariant(variant) {
  const templates = [
    {id: `synthetic-template-${variant.id}-a`, text: variant.template},
    {id: `synthetic-template-${variant.id}-b`, text: `{{name}}\n{{address}}\n\nEXPERIENCE\nDifferent fictional employer for ${variant.label}\n- Different work history and duties`},
  ];
  return {...variant, templates, assignments: DEMO_CANDIDATES.slice(0, templates.length).map((candidate, index) => ({candidateId: candidate.id, templateId: templates[index].id}))};
}

export function syntheticExperiment(paper) {
  const job = paper.records.find(record => record.id === paper.resumeDemo.jobId);
  const prompt = "Evaluate these fictional applicants and explain each interview decision.";
  return {prompt, examples: paper.resumeDemo.variants.map(variant => ({
    variantId: variant.id, generationPrompt: variant.prompt, template: variant.template,
    jobId: job.id, jobPosting: job.text, prompt: variant.experimentPrompt ?? prompt,
    candidates: populationExamples(variant).map(({template, ...input}) => input),
    decisions: populationExamples(variant).map((candidate, index) => ({candidateId: candidate.id, invite: index === 0, logprob: -0.1})),
    explanation: `Synthetic explanation for ${variant.id}; <script>literal text only</script>.`,
    requestId: `synthetic-request-${variant.id}`, scenarioId: `synthetic-scenario-${variant.id}`,
    experimentId: "synthetic-test-experiment", modelConfigId: "synthetic-model-config",
    model: "synthetic-test-model", provider: "test",
  }))};
}

export function inlineVariants(prefix = "controls") {
  return [2, 4].flatMap(resumes => [2, 4].flatMap(jobSkills => ["entry-level", "experienced"].map(experience => {
    const id = `${prefix}-${resumes}-${jobSkills}-${experience}`;
    const variant = pairedVariant({id, label: id, prompt: `Full instructions for ${id}`,
      promptSummary: `Summary for ${id}`, settings: {resumes, jobSkills, experience},
      template: `{{name}}\n{{address}}\nBackground for ${id}`});
    if (resumes === 4) variant.templates.push(
      {id: `${id}-third`, text: `{{name}}\n{{address}}\nThird distinct background for ${id}`},
      {id: `${id}-fourth`, text: `{{name}}\n{{address}}\nFourth distinct background for ${id}`});
    variant.assignments = DEMO_CANDIDATES.slice(0, resumes).map((candidate, index) => ({candidateId: candidate.id, templateId: variant.templates[index].id}));
    return variant;
  })));
}

export function withControlledFields(variant) {
  const values = {university: "Fictional College", education_start_year: "1984", education_end_year: "1988",
    work_start_month: "June", work_start_year: "1988", work_end_month: "July", work_end_year: "1990"};
  const fields = Object.keys(values);
  const text = "\nEDUCATION\n{{university}}\n{{education_start_year}}–{{education_end_year}}\nWORK EXPERIENCE\n{{work_start_month}} {{work_start_year}}–{{work_end_month}} {{work_end_year}}";
  const templates = variant.templates.map(template => ({...template, text: template.text + text}));
  return {...variant, templates, template: templates[0].text, placeholderFields: ["name", "address", ...fields],
    assignments: variant.assignments.map((assignment, index) => ({...assignment,
      values: {...values, university: index ? "Other Fictional College" : values.university}}))};
}

export function withPopulationPools(variant) {
  const dates = Object.fromEntries(Object.entries(variant.assignments[0].values).filter(([key]) => /_(month|year)$/.test(key)));
  const earlier = Object.fromEntries(Object.entries(dates).map(([key, value]) => [key,
    key.endsWith("year") && key !== "work_end_year" ? String(Number(value) - 1) : value]));
  const addresses = ["10 Test Road", "20 Test Road", "30 Test Road", "40 Test Road"];
  return {...variant, assignments: variant.assignments.map((assignment, index) => ({...assignment, address: addresses[index]})),
    populationPools: {addresses, schools: ["Fictional College", "Other Fictional College"],
      dates: [{label: "Recorded dates A", values: dates}, {label: "Recorded dates B", values: earlier}]}};
}
