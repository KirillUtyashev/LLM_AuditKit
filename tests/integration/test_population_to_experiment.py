"""Offline handoff from template population through experiment checkpointing."""

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from edsl import Jobs, Model
from edsl.caching import Cache

from llm_auditkit.experiments import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentResultStore,
    ExperimentRunner,
    Persona,
)
from llm_auditkit.inference import (
    DictResponseFormat,
    EDSLAdapter,
    InferenceAdapter,
    InferenceConfig,
    InferenceOrchestrator,
    InferenceRequest,
    InferenceResult,
    ModelConfig,
    RenderedPrompt,
    TokenLogprob,
    edsl_adapter,
)
from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


def _rendered(request: InferenceRequest) -> RenderedPrompt:
    return RenderedPrompt(request.request_id, request.prompt, request.system_prompt)


def _offline_result(request: InferenceRequest) -> InferenceResult:
    # The transport returns labeled decision tokens, leaving their parsing to the runner.
    answers = {
        "warehouse": (("No", -0.25), ("Yes", -0.125)),
        "library": (("Yes", -0.5), ("No", -0.75)),
    }
    scenario_id = request.metadata["scenario_id"]
    (first, first_logprob), (second, second_logprob) = answers[scenario_id]
    decisions = {"Applicant 1": first, "Applicant 2": second}
    return InferenceResult(
        request_id=request.request_id,
        model_config_id=request.model_config_id,
        metadata=dict(request.metadata),
        rendered_prompt=_rendered(request),
        content=json.dumps(decisions, separators=(",", ":")),
        structured_content=decisions,
        token_logprobs=[
            TokenLogprob('{"Applicant 1":"', -0.01),
            TokenLogprob(first, first_logprob),
            TokenLogprob('","Applicant 2":"', -0.02),
            TokenLogprob(second, second_logprob),
            TokenLogprob('"}', -0.03),
        ],
    )


@pytest.fixture
def applicant_tables():
    templates = pd.DataFrame(
        {
            "scenario_id": ["warehouse", "library"],
            "advert": ["Hire a stock clerk.", "Hire an archivist."],
            "office_code": [18, 45],
            "letter_body": ["Stockroom letter: {{name}}", "Archive letter: {{name}}"],
            "cv_body": ["Warehouse CV\n{{name}}", "Library CV\n{{name}}"],
        }
    )
    replacements = pd.DataFrame(
        [
            ("library", "cv", "A-004", 2, "Mira Elm", 8),
            ("warehouse", "letter", "A-017", 2, "Jo Ash", 3),
            ("library", "letter", "A-009", 1, "Sam Oak", 7),
            ("warehouse", "cv", "A-025", 1, "Lee Fir", 4),
        ],
        columns=[
            "scenario_id", "template_id", "candidate_id", "candidate_order", "name", "score",
        ],
    )
    population_config = TemplatePopulationConfig(
        template_columns={"letter": "letter_body", "cv": "cv_body"},
        placeholder_columns={"name": "name"},
        job_posting_column="advert",
    )
    return templates, replacements, population_config


def _experiment(job_column: str, model: ModelConfig, batch_size: int) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="population-handoff",
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column=job_column,
            resume_columns=["resume_1", "resume_2"],
        ),
        prompt_template="{job_posting}\nApplicant 1: {resume_1}\nApplicant 2: {resume_2}",
        personas=[
            Persona("manager", "Manager", "Hiring manager", "Decide who to interview.")
        ],
        inference=InferenceConfig(models=[model], batch_size=batch_size),
    )


EXPECTED_PROMPTS = {
    "warehouse": (
        "Hire a stock clerk.\nApplicant 1: Warehouse CV\nLee Fir\n"
        "Applicant 2: Stockroom letter: Jo Ash"
    ),
    "library": (
        "Hire an archivist.\nApplicant 1: Archive letter: Sam Oak\n"
        "Applicant 2: Library CV\nMira Elm"
    ),
}


def test_populated_slots_reach_prompts_results_and_checkpoint(
    tmp_path: Path, applicant_tables,
) -> None:
    templates, replacements, population_config = applicant_tables
    populated = TemplatePopulator().populate(templates, replacements, population_config)
    model = ModelConfig("offline", "synthetic", "test-model", {"logprobs": True})
    config = _experiment(population_config.job_posting_column, model, batch_size=2)
    adapter = Mock(spec=InferenceAdapter)
    adapter.render_batch.side_effect = lambda requests, models: [
        _rendered(request) for request in requests
    ]
    # Reverse delivery to exercise association across scenarios in the same batch.
    adapter.execute_batch.side_effect = lambda requests, models: [
        _offline_result(request) for request in reversed(requests)
    ]
    checkpoint = tmp_path / "results.csv"
    runner = ExperimentRunner(
        InferenceOrchestrator(adapter), ExperimentResultStore(checkpoint)
    )

    preview = runner.preview(populated, config)
    adapter.execute_batch.assert_not_called()
    output = runner.run(populated, config)
    adapter.execute_batch.assert_called_once()
    requests, _ = adapter.execute_batch.call_args.args
    submitted = {request.metadata["scenario_id"]: request.prompt for request in requests}
    assert submitted == EXPECTED_PROMPTS
    for request in requests:
        assert isinstance(request.response_format, DictResponseFormat)
        assert [field.name for field in request.response_format.fields] == [
            "Applicant 1", "Applicant 2",
        ]
    assert {p.request_id: p.user_prompt for p in preview.prompts} == {
        request.request_id: EXPECTED_PROMPTS[request.metadata["scenario_id"]]
        for request in requests
    }

    persisted = pd.read_csv(checkpoint)
    fresh_runner = ExperimentRunner(
        InferenceOrchestrator(adapter), ExperimentResultStore(checkpoint)
    )
    resumed = fresh_runner.run(populated, config)
    adapter.execute_batch.assert_called_once()
    expected_candidates = {
        # Independent of the transport's slot-based replies.
        ("warehouse", "A-025"): ("Warehouse CV\nLee Fir", 0, -0.25),
        ("warehouse", "A-017"): ("Stockroom letter: Jo Ash", 1, -0.125),
        ("library", "A-009"): ("Archive letter: Sam Oak", 1, -0.5),
        ("library", "A-004"): ("Library CV\nMira Elm", 0, -0.75),
    }
    source = templates.set_index("scenario_id")
    for frame in (output, persisted, resumed):
        rows = frame.set_index("scenario_id")
        assert rows.index.is_unique
        assert rows["user_prompt"].to_dict() == EXPECTED_PROMPTS
        assert rows["candidate_count"].eq(2).all()
        assert rows[["error_type", "error_message"]].isna().all().all()
        pd.testing.assert_frame_equal(
            rows.loc[source.index, source.columns], source, check_dtype=False
        )
        for assignment in replacements.itertuples(index=False):
            row = rows.loc[assignment.scenario_id]
            slot = assignment.candidate_order
            candidate = f"candidate_{slot}"
            assert row[f"{candidate}_id"] == assignment.candidate_id
            assert row[f"{candidate}_template_id"] == assignment.template_id
            template_column = population_config.template_columns[assignment.template_id]
            assert row[f"{candidate}_template_column"] == template_column
            assert row[f"{candidate}_name"] == assignment.name
            assert row[f"{candidate}_score"] == assignment.score
            key = (assignment.scenario_id, assignment.candidate_id)
            resume, pick, logprob = expected_candidates[key]
            assert row[f"resume_{slot}"] == resume
            assert row[f"pick{slot}"] == pick
            assert json.loads(row["picks"])[slot - 1] == pick
            assert row[f"logprob{slot}"] == logprob


# The local EDSL test model accepts the runner's required logprobs flag for preview.
@pytest.mark.filterwarnings(
    r"ignore:Unknown parameter\(s\) for model 'test'.*logprobs:UserWarning"
)
def test_edsl_preview_preserves_literal_braces_in_applicant_slots(
    tmp_path: Path, offline_edsl,
) -> None:
    templates = pd.DataFrame([{
        "scenario_id": "literal-text",
        "Text": "Hire a copy editor.",
        "sample": r"{{name}} transcribes \{{notes\}}.",
        "profile": "{{name}} proofreads {{example}}.",
    }])
    replacements = pd.DataFrame(
        [
            ("literal-text", "transcript", "A-032", 2, "Mira Elm", None),
            ("literal-text", "proof", "A-017", 1, "Jo Ash", "{{ 2+2 }}"),
        ],
        columns=[
            "scenario_id", "template_id", "candidate_id", "candidate_order", "name", "example",
        ],
    )
    populated = TemplatePopulator().populate(
        templates, replacements,
        TemplatePopulationConfig(
            template_columns={"transcript": "sample", "proof": "profile"},
            placeholder_columns={"name": "name", "example": "example"},
        ),
    )
    first_resume = "Jo Ash proofreads {{ 2+2 }}."
    second_resume = "Mira Elm transcribes {{notes}}."
    scenario = populated.set_index("scenario_id").loc["literal-text"]
    assert (scenario["candidate_1_id"], scenario["resume_1"]) == ("A-017", first_resume)
    assert (scenario["candidate_2_id"], scenario["resume_2"]) == ("A-032", second_resume)

    config = ExperimentConfig(
        experiment_id="literal-preview",
        dataset_schema=ExperimentDatasetSchema("Text", ["resume_1", "resume_2"]),
        prompt_template="{job_posting}\nApplicant 1: {resume_1}\nApplicant 2: {resume_2}",
        personas=[
            Persona("manager", "Manager", "Hiring manager", "Evaluate both applicants.")
        ],
        inference=InferenceConfig(
            models=[ModelConfig("local-test", "test", "test", {"logprobs": True})],
            batch_size=1,
        ),
    )
    checkpoint = tmp_path / "preview.csv"
    runner = ExperimentRunner(
        InferenceOrchestrator(EDSLAdapter()), ExperimentResultStore(checkpoint)
    )
    preview = runner.preview(populated, config)

    (rendered,) = preview.prompts
    expected_question = (
        f"Hire a copy editor.\nApplicant 1: {first_resume}\nApplicant 2: {second_resume}"
    )
    question, separator, instructions = rendered.user_prompt.partition(
        "Please respond with a dictionary"
    )
    assert separator and "Applicant 1, Applicant 2" in instructions
    assert not checkpoint.exists()
    assert question == expected_question


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_native_batch_selects_the_populated_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline_edsl, applicant_tables, mode: str,
) -> None:
    templates, replacements, population_config = applicant_tables
    literal = "\r\nLiteral: {{ 2+2 }} / {#draft#}\rTranscribed A\x00B.\n"
    replacements.loc[replacements["candidate_id"] == "A-017", "name"] = "Jo Ash" + literal
    questions = dict(EXPECTED_PROMPTS, warehouse=EXPECTED_PROMPTS["warehouse"] + literal)
    populated = TemplatePopulator().populate(templates, replacements, population_config)
    config = _experiment(
        population_config.job_posting_column,
        ModelConfig("local-test", "test", "test", {"logprobs": True}),
        batch_size=2,
    )
    model = Model("test", service_name="test")
    received = []
    replies = {
        "Hire a stock clerk.": ("No", "Yes", -0.25, -0.125),
        "Hire an archivist.": ("Yes", "No", -0.5, -0.75),
    }

    async def respond(user_prompt, system_prompt, **kwargs):
        received.append(user_prompt)
        first, second, prob1, prob2 = replies[user_prompt.splitlines()[0]]
        tokens = ['{"Applicant 1":"', first, '","Applicant 2":"', second, '"}']
        # Only the provider is scripted. Each concurrent call has its own
        # response, which the native EDSL job and experiment parser consume.
        return {
            "message": [{"text": "".join(tokens)}],
            "usage": {"prompt_tokens": 1, "completion_tokens": len(tokens)},
            "choices": [{"logprobs": {
                "tokens": tokens, "token_logprobs": [-0.01, prob1, -0.02, prob2, -0.03],
            }}],
        }

    def scripted_model(name, *, service_name, logprobs):
        assert (name, service_name, logprobs) == ("test", "test", True)
        return model

    monkeypatch.setattr(model, "async_execute_model_call", respond)
    monkeypatch.setattr(edsl_adapter, "Model", scripted_model)
    native_run, native_run_async = Jobs.run, Jobs.run_async
    local_options = dict(
        use_api_proxy=False, disable_remote_cache=True,
        stop_on_exception=True,
    )

    def run_locally(job, **kwargs):
        return native_run(job, cache=Cache(), **local_options, **kwargs)

    async def run_locally_async(job, **kwargs):
        return await native_run_async(job, cache=Cache(), **local_options, **kwargs)

    monkeypatch.setattr(Jobs, "run", run_locally)
    monkeypatch.setattr(Jobs, "run_async", run_locally_async)
    runner = ExperimentRunner(
        InferenceOrchestrator(EDSLAdapter()), ExperimentResultStore(tmp_path / "results.csv")
    )
    preview = runner.preview(populated, config)
    preview_questions = {
        p.user_prompt.partition("Please respond with a dictionary")[0] for p in preview.prompts
    }
    assert preview_questions == set(questions.values())
    if mode == "sync":
        output = runner.run(populated, config)
    else:
        output = asyncio.run(runner.run_async(populated, config))
    rows = output.set_index("scenario_id")
    restored = ExperimentResultStore(tmp_path / "results.csv").initialize(populated, config)
    restored = restored.set_index("scenario_id")

    assert rows.index.is_unique and set(rows.index) == set(questions)
    assert rows[["error_type", "error_message"]].isna().all().all()
    assert len(received) == len(questions)
    expected_decisions = {
        "warehouse": [("A-025", 0, -0.25), ("A-017", 1, -0.125)],
        "library": [("A-009", 1, -0.5), ("A-004", 0, -0.75)],
    }
    for scenario_id, question in questions.items():
        row = rows.loc[scenario_id]
        assert row["user_prompt"] in received
        assert restored.at[scenario_id, "user_prompt"] == row["user_prompt"]
        assert row["user_prompt"].startswith(question)
        assert "Applicant 1, Applicant 2" in row["user_prompt"][len(question):]
        for slot, decision in enumerate(expected_decisions[scenario_id], start=1):
            observed = (row[f"candidate_{slot}_id"], row[f"pick{slot}"], row[f"logprob{slot}"])
            assert observed == decision
