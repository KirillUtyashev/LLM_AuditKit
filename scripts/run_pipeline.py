"""Compose existing stages, stopping between explicitly selected review phases."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import yaml
from dotenv import load_dotenv

from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource
from llm_auditkit.experiments import ExperimentRunConfig, load_experiment_run_config
from llm_auditkit.experiments.cli import main as experiment_main
from llm_auditkit.inference import EDSLAdapter, InferenceOrchestrator
from llm_auditkit.ocr import load_ocr_run_config
from llm_auditkit.ocr.cli import main as ocr_main
from llm_auditkit.templates import (
    TemplateGenerationRunConfig, TemplateGenerator, TemplateStore, load_template_generation_run_config,
)
from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


ROOT = Path(__file__).resolve().parents[1]
PHASES = ("ocr", "templates", "population", "experiments", "analysis")


class PipelineError(ValueError):
    """Invalid workflow wiring or an unsuccessful phase; later phases never run."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise PipelineError("YAML mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _yaml(path):
    with path.open(encoding="utf-8") as stream:
        result = yaml.load(stream, Loader=_UniqueLoader)
    if not isinstance(result, dict):
        raise PipelineError("Each configuration must be a YAML mapping")
    return result


def _mapping(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise PipelineError("Pipeline configuration has missing or unknown keys")
    return value


def _strings(value):
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(item, str) or not item.strip()
        for key, item in value.items()
    ):
        raise PipelineError("Column mappings must contain nonblank string keys and values")
    return value


def _path(value, config_path):
    if not isinstance(value, str) or not value.strip():
        raise PipelineError("Configuration paths must be nonblank strings")
    return (config_path.parent / Path(value).expanduser()).resolve()


@dataclass
class PipelineConfig:
    templates: TemplateGenerationRunConfig
    experiments: ExperimentRunConfig
    template_path: Path
    experiment_path: Path
    ocr_path: Path | None
    replacements_path: Path
    population_path: Path
    population: TemplatePopulationConfig
    metadata_columns: dict[str, str]
    preparation_path: Path
    estimation_path: Path
    rendering_path: Path
    prepared_path: Path
    results_path: Path
    figure_path: Path


def load_config(path: str | Path) -> PipelineConfig:
    """Validate configuration wiring without loading data or calling providers."""
    path = Path(path).expanduser().resolve()
    root = _mapping(_yaml(path), {"templates", "population", "experiments", "regression"},
                    {"ocr", "metadata_columns"})
    population = _mapping(root["population"],
                          {"replacements_path", "output_path", "template_columns", "placeholder_columns"})
    regression = _mapping(root["regression"], {"preparation", "estimation", "rendering"})
    template_path, experiment_path = (_path(root[key], path) for key in ("templates", "experiments"))
    templates = load_template_generation_run_config(template_path)
    experiments = load_experiment_run_config(experiment_path)
    ocr_path = _path(root["ocr"], path) if "ocr" in root else None
    ocr = load_ocr_run_config(ocr_path) if ocr_path else None
    replacements_path = _path(population["replacements_path"], path)
    population_path = _path(population["output_path"], path)
    columns = _strings(population["template_columns"])
    placeholders = _strings(population["placeholder_columns"])
    count = templates.generation_config.templates_per_scenario
    if len(columns) != count or set(columns.values()) != {f"template_{i}" for i in range(1, count + 1)}:
        raise PipelineError("population.template_columns must match generated template_1 through template_N")
    if set(placeholders) != set(templates.generation_config.required_placeholders):
        raise PipelineError("Population placeholder mappings must match template generation's required placeholders")
    if experiments.experiment_config.dataset_schema.resume_columns != [f"resume_{i}" for i in range(1, count + 1)]:
        raise PipelineError("Experiment resume_columns must follow population's numeric slot order")
    job_column = templates.generation_config.dataset_schema.job_posting_column
    if experiments.experiment_config.dataset_schema.job_posting_column != job_column:
        raise PipelineError("Template generation and experiments must use the same job-posting column")
    if len(experiments.experiment_config.personas) != 1 or len(experiments.experiment_config.inference.models) != 1:
        raise PipelineError("This runner requires one persona and model configuration; it never partitions audits")
    if population_path.suffix.lower() != ".csv" or population_path != experiments.dataset_path:
        raise PipelineError("Population output must be a CSV matching the experiment dataset path")
    if ocr and templates.dataset_path != ocr.output_path:
        raise PipelineError("OCR output must match the template-generation dataset path")
    metadata_columns = _strings(root.get("metadata_columns", {}))
    if {"scenario_id", "metadata_json"} & metadata_columns.keys():
        raise PipelineError("Metadata extraction cannot overwrite identities or its source column")

    preparation_path, estimation_path, rendering_path = (
        _path(regression[key], path) for key in ("preparation", "estimation", "rendering")
    )
    preparation, estimation, rendering = map(_yaml, (preparation_path, estimation_path, rendering_path))
    if preparation.get("input_format") != "auditkit":
        raise PipelineError("Regression preparation must set input_format: auditkit")
    inputs = preparation.get("input_paths")
    if not isinstance(inputs, list) or [_path(item, preparation_path) for item in inputs] != [experiments.output_path]:
        raise PipelineError("Regression preparation must read exactly this experiment's output CSV")
    prepared_path = _path(preparation.get("output_path"), preparation_path)
    if _path(estimation.get("data_path"), estimation_path) != prepared_path:
        raise PipelineError("Estimation data_path must match preparation output_path")
    results_path = _path(estimation.get("output_directory"), estimation_path) / "regression_results.csv"
    results = rendering.get("results_paths")
    if not isinstance(results, list) or [_path(item, rendering_path) for item in results] != [results_path]:
        raise PipelineError("Rendering must read exactly this estimation's regression_results.csv")
    figure_path = _path(rendering.get("output_path"), rendering_path)

    # Protect all source/config/prompt files, including aliases resolved through
    # symlinks. Only intentional stage-output -> stage-input links may coincide.
    protected = {path, template_path, experiment_path, preparation_path, estimation_path,
                 rendering_path, replacements_path}
    for config_path in (template_path, experiment_path):
        raw = _yaml(config_path)
        for value in raw["prompt"].values():
            if value is not None:
                protected.add(_path(value, config_path))
        for persona in raw.get("personas", []):
            for key in ("trait_template_path", "instruction_path"):
                protected.add(_path(persona[key], config_path))
    if ocr:
        protected.add(ocr_path)
        protected.update(document.path.resolve() for document in ocr.documents)
    else:
        protected.add(templates.dataset_path)
    outputs = [templates.output_path, population_path, experiments.output_path,
               prepared_path, results_path, figure_path, *([ocr.output_path] if ocr else [])]
    if len(set(outputs)) != len(outputs) or any(
        output == source or (source.is_dir() and output.is_relative_to(source))
        for output in outputs for source in protected
    ):
        raise PipelineError("Outputs must be distinct and must not overwrite source, replacement, config or prompt files")
    return PipelineConfig(
        templates, experiments, template_path, experiment_path, ocr_path, replacements_path,
        population_path, TemplatePopulationConfig(columns, placeholders, job_column),
        metadata_columns, preparation_path, estimation_path, rendering_path,
        prepared_path, results_path, figure_path,
    )


def _load_dataset(path, required):
    return DatasetLoader(DatasetSchema(list(dict.fromkeys(required)))).load(LocalDatasetSource(path))


def _templates(config):
    run = config.templates
    schema = run.generation_config.dataset_schema
    required = [schema.job_posting_column, *schema.context_columns.values(), "city", "year"]
    extracted = set(config.metadata_columns)
    dataset = _load_dataset(run.dataset_path, [c for c in required if c not in extracted] +
                            (["metadata_json"] if extracted else []))
    if extracted & set(dataset.columns):
        raise PipelineError("metadata_columns must not overwrite existing dataset columns")
    if extracted:
        metadata = dataset.metadata_json.map(json.loads)
        for column, key in config.metadata_columns.items():
            if any(not isinstance(item, dict) or key not in item for item in metadata):
                raise PipelineError("A configured metadata key is absent from a source row")
            dataset[column] = metadata.map(lambda item: item[key])
    generator = TemplateGenerator(InferenceOrchestrator(EDSLAdapter()), TemplateStore(run.output_path))
    output = (generator.generate(dataset, run.generation_config) if run.mode == "sync"
              else asyncio.run(generator.generate_async(dataset, run.generation_config)))
    if output.template_generation_error_type.notna().any():
        raise PipelineError("Template generation has failed rows; inspect checkpoints and rerun this phase")
    print(f"Review templates and create/verify candidate replacements: {run.output_path}")


def _atomic_csv(dataset, path):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            dataset.to_csv(stream, index=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _populate(config):
    population = config.population
    templates = _load_dataset(config.templates.output_path,
                              [population.job_posting_column, *population.template_columns.values(), "city", "year"])
    # Replacement rows deliberately repeat scenario IDs; do not run the
    # one-row-per-scenario DatasetLoader validator over this assignment table.
    replacements = LocalDatasetSource(config.replacements_path).load().replace("", pd.NA)
    if "candidate_order" not in replacements or not replacements.candidate_order.map(
        lambda value: isinstance(value, (str, int)) and str(value).isdigit()
    ).all():
        raise PipelineError("Replacement candidate_order must contain integer slots")
    replacements["candidate_order"] = replacements.candidate_order.astype("int64")
    populated = TemplatePopulator().populate(templates, replacements, population)
    _atomic_csv(populated, config.population_path)
    print(f"Review populated resumes, candidate IDs, ordering and covariates: {config.population_path}")


def _r_command(script, config_path):
    if not shutil.which("Rscript"):
        raise PipelineError("Rscript is required; restore the repository's renv environment first")
    subprocess.run(["Rscript", str(ROOT / "scripts" / script), "--config", str(config_path)],
                   cwd=ROOT, check=True)


def run_phase(config: PipelineConfig, phase: str) -> None:
    """Run one explicitly selected phase; never cross its inspection boundary."""
    if phase not in PHASES:
        raise PipelineError("Unknown pipeline phase")
    if phase == "ocr":
        if config.ocr_path is None:
            raise PipelineError("No OCR config supplied; start from the templates phase for an existing dataset")
        if ocr_main(["--config", str(config.ocr_path)]) != 0:
            raise PipelineError("OCR failed; its CSV may be partial")
        print("Inspect extracted ads against the source scans before the templates phase.")
    elif phase == "templates":
        _templates(config)
    elif phase == "population":
        _populate(config)
    elif phase == "experiments":
        # Detect a missing R runtime before this phase spends model tokens.
        if not shutil.which("Rscript"):
            raise PipelineError("Rscript is required before running the experiments phase")
        if experiment_main(["--config", str(config.experiment_path)]) != 0:
            raise PipelineError("Experiment execution failed; preparation was not started")
        _r_command("prepare_regression_data.R", config.preparation_path)
        print(f"Inspect and, if needed, slice regression-ready data before analysis: {config.prepared_path}")
    else:
        _r_command("run_regression.R", config.estimation_path)
        _r_command("render_regression_plot.R", config.rendering_path)
        print(f"Regression results: {config.results_path}\nFigure: {config.figure_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run an explicit pipeline phase, then stop for inspection.")
    parser.add_argument("--config", required=True, help="pipeline YAML referencing existing stage configurations")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--phase", choices=PHASES)
    mode.add_argument("--check", action="store_true", help="validate config wiring without data loading or inference")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.check:
            print("Pipeline configuration wiring is valid; data and full R validation occur in their phases.")
            return 0
        load_dotenv(override=False)
        run_phase(config, args.phase)
    except Exception as error:
        # Stage CLI commands retain their own diagnostics. Do not echo arbitrary
        # provider exception strings, which can contain credentials or prompts.
        detail = str(error) if isinstance(error, PipelineError) else type(error).__name__
        print(f"Pipeline stopped: {detail}. No subsequent phase was started.", file=sys.stderr)
        return 1
    print("Phase finished. Inspect its artifacts before explicitly starting the next phase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
