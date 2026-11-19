// Entirely synthetic unit-test responses; never presented as a live model run.
import {DEMO_CANDIDATES, populationExamples} from "../../website/lib.mjs";

export function pairedVariant(variant) {
  const templates = [
    {id: `synthetic-template-${variant.id}-a`, text: variant.template},
    {id: `synthetic-template-${variant.id}-b`, text: `{{name}}\n{{address}}\n\nEXPERIENCE\nDifferent fictional employer for ${variant.label}\n- Different work history and duties`},
  ];
  return {...variant, templates, assignments: DEMO_CANDIDATES.map((candidate, index) => ({candidateId: candidate.id, templateId: templates[index].id}))};
}

export function syntheticExperiment(paper) {
  const job = paper.records.find(record => record.id === paper.resumeDemo.jobId);
  const prompt = "Evaluate these fictional applicants and explain each interview decision.";
  return {prompt, examples: paper.resumeDemo.variants.map(variant => ({
    variantId: variant.id, generationPrompt: variant.prompt, template: variant.template,
    jobId: job.id, jobPosting: job.text, prompt,
    candidates: populationExamples(variant).map(({template, ...input}) => input),
    decisions: DEMO_CANDIDATES.map((candidate, index) => ({candidateId: candidate.id, invite: index === 0, logprob: -0.1})),
    explanation: `Synthetic explanation for ${variant.id}; <script>literal text only</script>.`,
    requestId: `synthetic-request-${variant.id}`, scenarioId: `synthetic-scenario-${variant.id}`,
    experimentId: "synthetic-test-experiment", modelConfigId: "synthetic-model-config",
    model: "synthetic-test-model", provider: "test",
  }))};
}
