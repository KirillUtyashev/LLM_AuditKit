"""Synthetic newspaper through native Python stages and public R preparation.

Only Vision RPCs and model transport are scripted. Handoffs use production
exports/loaders; no fixture-only schema translation sits between stages.
"""

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest
import yaml

from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource
from llm_auditkit.experiments import (
    ExperimentConfig, ExperimentDatasetSchema, ExperimentResultStore, ExperimentRunner, Persona,
)
from llm_auditkit.inference import EDSLAdapter, InferenceConfig, InferenceOrchestrator, ModelConfig
from llm_auditkit.inference import edsl_adapter
from llm_auditkit.ocr import GoogleVisionOCRBackend, NewspaperOCRPipeline, OCRConfig, OCRStore, SourceDocument
from llm_auditkit.templates import TemplateDatasetSchema, TemplateGenerationConfig, TemplateGenerator, TemplateStore
from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


ROOT = Path(__file__).resolve().parents[2]
POSTINGS = [f"OFFICE CLERK SN{number:04d}. File records. Apply to Box {number:04d}."
            for number in range(1, 17)]


def _model(config_id, **parameters):
    return InferenceConfig([ModelConfig(config_id, "test", "test", parameters)], batch_size=5)


def _ocr_response(vision, text):
    return vision.BatchAnnotateImagesResponse(responses=[{
        "full_text_annotation": {"text": text, "pages": [{
            "width": 600, "height": 800, "blocks": [{
                "bounding_box": {"vertices": [{"x": 10, "y": 10}, {"x": 590, "y": 10},
                                                {"x": 590, "y": 100}, {"x": 10, "y": 100}]},
                "confidence": 0.99,
                "paragraphs": [{"words": [{"symbols": [{"text": char} for char in word]}
                                            for word in text.split(" ")]}],
            }],
        }]},
    }])


@pytest.fixture
def full_pipeline(tmp_path, monkeypatch, offline_edsl):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    vision = pytest.importorskip("google.cloud.vision")
    pytest.importorskip("pdf2image")
    if not shutil.which("pdfinfo") or not shutil.which("pdftoppm"):
        pytest.skip("optional system Poppler is required")
    from google.auth.credentials import AnonymousCredentials
    from edsl import Cache, Jobs
    from edsl.coop import Coop

    source = tmp_path / "synthetic-newspaper.pdf"
    pages = []
    for text in POSTINGS:
        image = Image.new("RGB", (600, 800), "white")
        ImageDraw.Draw(image).text((10, 10), text, fill="black")
        pages.append(image)
    try:
        pages[0].save(source, format="PDF", save_all=True, append_images=pages[1:], resolution=72)
    finally:
        for image in pages:
            image.close()

    monkeypatch.setattr(Coop, "fetch_prices", lambda *args, **kwargs: {})
    monkeypatch.setattr(Coop, "edsl_settings", property(lambda self: {}))
    execution = {"cache": Cache(), "mode": "sync"}
    calls = []
    factory = edsl_adapter.Model

    def create_model(*args, **kwargs):
        model = factory(*args, **kwargs)
        async def provider(user_prompt, system_prompt, **kwargs):
            if "TEMPLATE_SMOKE" in system_prompt:
                stage = "templates"
                answer = {f"template_{slot}": f"Layout {slot}. Applicant: {{{{name}}}}. Fixture group: {{{{group}}}}."
                          for slot in range(1, 4)}
                text, tokens, probabilities = json.dumps(answer), [], []
            elif "EXPERIMENT_SMOKE" in system_prompt:
                stage = "experiments"
                number = int(re.search(r"SN(\d+)", user_prompt)[1])
                groups = [int(value) for value in re.findall(r"Fixture group: ([01])", user_prompt)]
                assert len(groups) == 3
                tokens, probabilities = ["{"], [0.0]
                for slot, group in enumerate(groups, 1):
                    selected = (number % 4 != 0) if group else (number % 4 == 1)
                    decision = "Yes" if selected else "No"
                    confidence = (0.995 if number % 3 else 0.9) if selected else 0.98
                    tokens.extend([f'"Applicant {slot}":"', decision, '", ' if slot < 3 else '"}'])
                    probabilities.extend([0.0, math.log(confidence), 0.0])
                text = "".join(tokens)
            else:
                stage = "reconstruction"
                payload = json.JSONDecoder().raw_decode(user_prompt[user_prompt.index('{"blocks"'):])[0]
                blocks = payload["blocks"]
                text = json.dumps({
                    "ads": [{"key": "ad", "text": "\n".join(block["text"] for block in blocks)}],
                    "blocks": [{"block_id": block["block_id"], "segments": [
                        {"text": block["text"], "ad_key": "ad", "reason": ""},
                    ]} for block in blocks],
                })
                tokens, probabilities = [], []
            calls.append((execution["mode"], stage))
            response = {"message": [{"text": text}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            if tokens:
                response["choices"] = [{"logprobs": {"tokens": tokens, "token_logprobs": probabilities}}]
            return response
        monkeypatch.setattr(model, "async_execute_model_call", provider)
        return model

    monkeypatch.setattr(edsl_adapter, "Model", create_model)
    native_run, native_async = Jobs.run, Jobs.run_async
    def options(kwargs):
        return {"cache": execution["cache"], "use_api_proxy": False, "disable_remote_cache": True,
                "check_api_keys": False, "progress_bar": False, **kwargs}
    monkeypatch.setattr(Jobs, "run", lambda job, **kwargs: native_run(job, **options(kwargs)))
    async def run_async(job, **kwargs):
        return await native_async(job, **options(kwargs))
    monkeypatch.setattr(Jobs, "run_async", run_async)

    outputs = {}
    for mode in ("sync", "async"):
        execution.update(mode=mode, cache=Cache())
        directory = tmp_path / mode
        backend = GoogleVisionOCRBackend()
        ocr_calls = []
        def recognize(request, **kwargs):
            assert request.requests[0].image.content.startswith(b"\x89PNG")
            text = POSTINGS[len(ocr_calls)]
            ocr_calls.append(text)
            return _ocr_response(vision, text)
        if mode == "sync":
            backend._client = vision.ImageAnnotatorClient(credentials=AnonymousCredentials())
            transport = backend._client.transport
            transport._wrapped_methods[transport.batch_annotate_images] = Mock(side_effect=recognize)

        pipeline = NewspaperOCRPipeline(backend, InferenceOrchestrator(EDSLAdapter()),
                                        OCRStore(directory / "ocr-cache", directory / "jobs.csv"))
        documents = [SourceDocument(source, {"city": "SyntheticCity", "year": 2010})]
        ocr_config = OCRConfig(_model("ocr"), dpi=72)
        if mode == "sync":
            try:
                jobs = pipeline.run(documents, ocr_config)
                pipeline.run(documents, ocr_config)
            finally:
                backend.close()
        else:
            async def acquire():
                backend._async_client = vision.ImageAnnotatorAsyncClient(credentials=AnonymousCredentials())
                transport = backend._async_client.transport
                async def rpc(request, **kwargs):
                    return recognize(request, **kwargs)
                transport._wrapped_methods[transport.batch_annotate_images] = AsyncMock(side_effect=rpc)
                try:
                    output = await pipeline.run_async(documents, ocr_config)
                    await pipeline.run_async(documents, ocr_config)
                    return output
                finally:
                    await backend.close_async()
            jobs = asyncio.run(acquire())
        assert jobs.Text.tolist() == ocr_calls == POSTINGS

        dataset = DatasetLoader(DatasetSchema(["Text"], ["Text"])).load(LocalDatasetSource(directory / "jobs.csv"))
        assert {"request_id", "model_config_id"}.isdisjoint(dataset.columns)
        assert dataset.ocr_request_id.tolist() == jobs.ocr_request_id.tolist()
        for name in ("city", "year"):
            dataset[name] = dataset.metadata_json.map(lambda value: json.loads(value)[name])
        generation = TemplateGenerationConfig(
            templates_per_scenario=3, dataset_schema=TemplateDatasetSchema("Text"),
            prompt_template="For {job_posting}, create {templates_per_scenario} layouts using {required_placeholders}.",
            required_placeholders=["name", "group"], system_prompt_template="TEMPLATE_SMOKE",
            inference=_model("templates"), model_config_id="templates",
        )
        generator = TemplateGenerator(InferenceOrchestrator(EDSLAdapter()), TemplateStore(directory / "templates.csv"))
        generate = lambda: (generator.generate(dataset, generation) if mode == "sync"
                            else asyncio.run(generator.generate_async(dataset, generation)))
        templates = generate()
        assert templates.template_generation_error_type.isna().all()
        before = len(calls)
        generate()
        assert len(calls) == before
        replacements = []
        for record in templates.to_dict(orient="records"):
            serial = int(re.search(r"SN(\d+)", record["Text"])[1])
            for variant in range(1, 4):
                treatment = int(variant == 2)  # researcher-defined fixture indicator, not inferred
                replacements.append({
                    "scenario_id": record["scenario_id"], "template_id": f"layout-{variant}",
                    "candidate_id": f"fixture:SN{serial:04d}:profile-{variant}",
                    "candidate_order": (variant + serial) % 3 + 1,
                    "name": f"Synthetic person SN{serial:04d}-{variant}", "group": str(treatment),
                    "treatment": treatment,
                })
        populated = TemplatePopulator().populate(templates, pd.DataFrame(replacements).iloc[::-1],
            TemplatePopulationConfig({f"layout-{slot}": f"template_{slot}" for slot in range(1, 4)},
                                     {"name": "name", "group": "group"}))
        experiment = ExperimentConfig(
            experiment_id="offline-full-pipeline-v1", dataset_schema=ExperimentDatasetSchema("Text", [f"resume_{slot}" for slot in range(1, 4)]),
            prompt_template="{job_posting}\nApplicant 1: {resume_1}\nApplicant 2: {resume_2}\nApplicant 3: {resume_3}",
            personas=[Persona("fixture-reviewer", "Fixture", "Synthetic hiring manager", "EXPERIMENT_SMOKE")],
            inference=_model("review", logprobs=True),
        )
        result_store = ExperimentResultStore(directory / "experiments.csv")
        runner = ExperimentRunner(InferenceOrchestrator(EDSLAdapter()), result_store)
        execute = lambda: (runner.run(populated, experiment) if mode == "sync"
                           else asyncio.run(runner.run_async(populated, experiment)))
        save = result_store.save
        def interrupt_after_checkpoint(frame):
            save(frame)
            raise OSError("synthetic interruption after first batch checkpoint")
        with monkeypatch.context() as interruption:
            interruption.setattr(result_store, "save", interrupt_after_checkpoint)
            with pytest.raises(OSError, match="synthetic interruption"):
                execute()
        assert len(pd.read_csv(result_store.output_path)) == 5
        native = execute()
        assert native.error_type.isna().all(), native[["error_type", "error_message"]].to_dict("records")
        before = len(calls)
        execute()
        assert len(calls) == before
        assert native.candidate_count.eq(3).all() and len(native) == 16
        for record in native.to_dict(orient="records"):
            number = int(re.search(r"SN(\d+)", record["Text"])[1])
            for slot in range(1, 4):
                group = record[f"candidate_{slot}_treatment"]
                expected = (number % 4 != 0) if group else (number % 4 == 1)
                assert record[f"pick{slot}"] == int(expected)
                assert record[f"candidate_{slot}_name"] in record[f"resume_{slot}"]
        assert native.ocr_request_id.tolist() == jobs.ocr_request_id.tolist()
        assert native.ocr_model_config_id.eq("ocr").all()
        assert native.model_config_id.eq("review").all()
        outputs[mode] = (native, directory)
    pd.testing.assert_frame_equal(outputs["sync"][0], outputs["async"][0])
    assert len(calls) == len(POSTINGS) * 3 * 2
    return outputs


def test_offline_newspaper_through_experiment_and_resume(full_pipeline):
    native, _ = full_pipeline["sync"]
    assert native.scenario_id.is_unique
    assert "result_status" not in native and "candidate_1_pick" not in native
    assert native.error_type.isna().all()


def _r_command(script, configuration):
    return subprocess.run(
        ["Rscript", str(ROOT / "scripts" / script), "--config", str(configuration)],
        cwd=ROOT, text=True, capture_output=True, timeout=60,
    )


@pytest.mark.skipif(os.environ.get("LLM_AUDITKIT_RUN_R_INTEGRATION") != "1",
                    reason="opt in after restoring renv: LLM_AUDITKIT_RUN_R_INTEGRATION=1")
def test_offline_full_chain_to_inspected_regression_and_png(full_pipeline):
    if not shutil.which("Rscript"):
        pytest.skip("Rscript is not installed")
    prepared_tables = []
    for mode, (native, directory) in full_pipeline.items():
        preparation = {
            "input_paths": [str(directory / "experiments.csv")],
            "input_format": "auditkit",
            "output_path": str(directory / "regression-ready.csv"),
            "audit_id": "researcher_assigned_offline_smoke_audit",
            "top_share": 0.25, "probability_threshold": 0.99,
            "ranking_group_variables": ["city", "year"],
            "scenario_covariates": [], "candidate_covariates": ["treatment"],
        }
        config_path = directory / "prepare.yaml"
        config_path.write_text(yaml.safe_dump(preparation))
        prepared_run = _r_command("prepare_regression_data.R", config_path)
        assert prepared_run.returncode == 0, prepared_run.stderr
        prepared = pd.read_csv(directory / "regression-ready.csv")

        # Explicit inspection gate: these oracles belong to this synthetic
        # researcher fixture. A live run requires actual researcher inspection.
        assert len(prepared) == 48
        assert set(prepared.audit_id) == {preparation["audit_id"]}
        assert set(prepared.candidate_id) == {
            value for slot in range(1, 4) for value in native[f"candidate_{slot}_id"]
        }
        assert prepared.pick.sum() == 20
        assert prepared.pick_top.sum() == 12
        assert prepared.pick_threshold.sum() == 14
        assert not any("prompt" in column or "resume" in column for column in prepared)
        for row in prepared.itertuples():
            source = native.loc[native.scenario_id == row.scenario_id].iloc[0]
            slot = next(slot for slot in range(1, 4) if source[f"candidate_{slot}_id"] == row.candidate_id)
            assert row.pick == source[f"pick{slot}"]
            assert row.log_probability == pytest.approx(source[f"logprob{slot}"])
            assert row.treatment == source[f"candidate_{slot}_treatment"]

        regression = {
            "data_path": str(directory / "regression-ready.csv"),
            "dataset_id": "offline_smoke_inspected_slice", "model_id": "fixture_treatment_fe",
            "outcome_variable": "pick", "explanatory_variables": ["treatment"],
            "control_variables": [], "fixed_effects": ["scenario_id"],
            "cluster_variables": ["scenario_id"], "estimation_group_variables": ["city", "year"],
            "output_directory": str(directory / "regression"),
        }
        regression_path = directory / "regress.yaml"
        regression_path.write_text(yaml.safe_dump(regression))
        fitted = _r_command("run_regression.R", regression_path)
        assert fitted.returncode == 0, fitted.stderr
        results_path = directory / "regression" / "regression_results.csv"
        coefficients = pd.read_csv(results_path)
        assert len(coefficients) == 3
        assert set(coefficients.term) == {"treatment"}
        assert coefficients.estimate.tolist() == pytest.approx([0.5] * 3)
        assert coefficients.n_used.eq(48).all()
        assert set(coefficients.confidence_level) == {0.9, 0.95, 0.99}
        render = {
            "results_paths": [str(results_path)], "output_path": str(directory / "regression.png"),
            "term": "treatment", "outcome_variable": "pick", "confidence_level": 0.95,
            "period_variable": "year", "period_order": [2010], "x_label": "Synthetic year",
            "y_label": "Fixture treatment coefficient", "width": 6, "height": 4, "dpi": 100,
            "y_limits": [-0.1, 1.0], "y_break_interval": 0.2,
        }
        shown = coefficients.loc[coefficients.confidence_level == render["confidence_level"]]
        assert shown.conf_low.ge(render["y_limits"][0]).all()
        assert shown.conf_high.le(render["y_limits"][1]).all()
        render_path = directory / "render.yaml"
        render_path.write_text(yaml.safe_dump(render))
        rendered = _r_command("render_regression_plot.R", render_path)
        assert rendered.returncode == 0, rendered.stderr
        from PIL import Image
        with Image.open(directory / "regression.png") as image:
            assert image.size == (600, 400)
        prepared_tables.append(prepared.drop(columns=["source_file"]))
        print(f"Verified {mode} offline artifacts: {directory}")
    pd.testing.assert_frame_equal(*prepared_tables)
