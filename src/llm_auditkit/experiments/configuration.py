"""Strict YAML loading for user-facing experiment run configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from llm_auditkit.inference import InferenceConfig, ModelConfig

from .exceptions import ExperimentConfigurationError
from .models import (
    ExperimentConfig,
    ExperimentDatasetSchema,
    ExperimentRunConfig,
    Persona,
)
from .validation import validate_experiment_config


_TOP_LEVEL_KEYS = {
    "experiment_id",
    "dataset",
    "prompt",
    "output",
    "execution",
    "personas",
    "inference",
}
_DATASET_KEYS = {
    "path",
    "job_posting_column",
    "resume_columns",
    "context_columns",
}
_PROMPT_KEYS = {"template_path"}
_OUTPUT_KEYS = {"path"}
_EXECUTION_KEYS = {"mode", "batch_size", "save_after_each_batch"}
_PERSONA_KEYS = {"id", "name", "trait_template_path", "instruction_path"}
_INFERENCE_KEYS = {"models"}
_MODEL_KEYS = {"config_id", "provider", "model", "parameters"}


def load_experiment_run_config(path: str | Path) -> ExperimentRunConfig:
    """Load and validate a complete experiment run from a YAML file."""

    config_path = _config_path(path)
    raw_config = _load_yaml(config_path)
    root = _mapping(
        raw_config,
        "configuration",
        allowed=_TOP_LEVEL_KEYS,
        required=_TOP_LEVEL_KEYS,
    )
    dataset = _mapping(
        root["dataset"],
        "dataset",
        allowed=_DATASET_KEYS,
        required=_DATASET_KEYS - {"context_columns"},
    )
    prompt = _mapping(
        root["prompt"],
        "prompt",
        allowed=_PROMPT_KEYS,
        required=_PROMPT_KEYS,
    )
    output = _mapping(
        root["output"],
        "output",
        allowed=_OUTPUT_KEYS,
        required=_OUTPUT_KEYS,
    )
    execution = _mapping(
        root["execution"],
        "execution",
        allowed=_EXECUTION_KEYS,
        required=_EXECUTION_KEYS,
    )
    inference = _mapping(
        root["inference"],
        "inference",
        allowed=_INFERENCE_KEYS,
        required=_INFERENCE_KEYS,
    )

    dataset_path = _resolve_config_path(
        dataset["path"],
        config_path,
        "dataset.path",
    )
    output_path = _resolve_config_path(
        output["path"],
        config_path,
        "output.path",
    )
    if output_path.suffix.lower() != ".csv":
        raise ExperimentConfigurationError("output.path must reference a .csv file")
    if dataset_path == output_path:
        raise ExperimentConfigurationError(
            "dataset.path and output.path must resolve to different files"
        )
    if output_path == config_path:
        raise ExperimentConfigurationError(
            "output.path must not overwrite the experiment YAML file"
        )

    mode = execution["mode"]
    if not isinstance(mode, str) or mode not in {"sync", "async"}:
        raise ExperimentConfigurationError(
            "execution.mode must be exactly 'sync' or 'async'"
        )

    experiment_config = ExperimentConfig(
        experiment_id=root["experiment_id"],
        dataset_schema=ExperimentDatasetSchema(
            job_posting_column=dataset["job_posting_column"],
            resume_columns=dataset["resume_columns"],
            context_columns=dataset.get("context_columns", {}),
        ),
        prompt_template=_read_text_file(
            prompt["template_path"],
            config_path,
            "prompt.template_path",
        ),
        personas=_personas(root["personas"], config_path),
        inference=InferenceConfig(
            models=_models(inference["models"]),
            batch_size=execution["batch_size"],
        ),
        save_after_each_batch=execution["save_after_each_batch"],
    )
    validate_experiment_config(experiment_config)
    return ExperimentRunConfig(
        dataset_path=dataset_path,
        output_path=output_path,
        mode=mode,
        experiment_config=experiment_config,
    )


def _config_path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ExperimentConfigurationError(
            "experiment configuration path must be a non-empty string or Path"
        )
    config_path = Path(path).expanduser().resolve()
    if config_path.suffix.lower() not in {".yaml", ".yml"}:
        raise ExperimentConfigurationError(
            "experiment configuration path must end in .yaml or .yml"
        )
    if not config_path.is_file():
        raise ExperimentConfigurationError(
            f"experiment configuration file does not exist: {config_path}"
        )
    return config_path


def _load_yaml(config_path: Path) -> object:
    try:
        with config_path.open(encoding="utf-8") as config_file:
            return yaml.load(config_file, Loader=_UniqueKeySafeLoader)
    except (OSError, yaml.YAMLError) as error:
        raise ExperimentConfigurationError(
            f"could not load experiment YAML: {type(error).__name__}: {error}"
        ) from error


def _resolve_config_path(
    value: object,
    config_path: Path,
    field_name: str,
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentConfigurationError(
            f"{field_name} must be a non-empty path string"
        )
    resolved = Path(value).expanduser()
    if not resolved.is_absolute():
        resolved = config_path.parent / resolved
    return resolved.resolve()


def _personas(value: object, config_path: Path) -> list[Persona]:
    if not isinstance(value, list):
        raise ExperimentConfigurationError("personas must be a YAML sequence")
    personas: list[Persona] = []
    for position, raw_persona in enumerate(value):
        persona = _mapping(
            raw_persona,
            f"personas[{position}]",
            allowed=_PERSONA_KEYS,
            required=_PERSONA_KEYS,
        )
        personas.append(
            Persona(
                id=persona["id"],
                name=persona["name"],
                trait_template=_read_text_file(
                    persona["trait_template_path"],
                    config_path,
                    f"personas[{position}].trait_template_path",
                ),
                instruction=_read_text_file(
                    persona["instruction_path"],
                    config_path,
                    f"personas[{position}].instruction_path",
                ),
            )
        )
    return personas


def _read_text_file(value: object, config_path: Path, field_name: str) -> str:
    resolved = _resolve_config_path(value, config_path, field_name)
    if resolved.suffix.lower() != ".txt":
        raise ExperimentConfigurationError(f"{field_name} must reference a .txt file")
    if not resolved.is_file():
        raise ExperimentConfigurationError(
            f"{field_name} file does not exist: {resolved}"
        )
    try:
        return resolved.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ExperimentConfigurationError(
            f"could not read {field_name}: {type(error).__name__}: {error}"
        ) from error


def _models(value: object) -> list[ModelConfig]:
    if not isinstance(value, list):
        raise ExperimentConfigurationError(
            "inference.models must be a YAML sequence"
        )
    models: list[ModelConfig] = []
    for position, raw_model in enumerate(value):
        model = _mapping(
            raw_model,
            f"inference.models[{position}]",
            allowed=_MODEL_KEYS,
            required=_MODEL_KEYS - {"parameters"},
        )
        parameters = model.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ExperimentConfigurationError(
                f"inference.models[{position}].parameters must be a mapping"
            )
        models.append(
            ModelConfig(
                config_id=model["config_id"],
                provider=model["provider"],
                model=model["model"],
                parameters=parameters,
            )
        )
    return models


def _mapping(
    value: object,
    field_name: str,
    *,
    allowed: set[str],
    required: set[str],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ExperimentConfigurationError(f"{field_name} must be a YAML mapping")
    if not all(isinstance(key, str) for key in value):
        raise ExperimentConfigurationError(
            f"{field_name} keys must all be strings"
        )

    mapping = dict(value)
    unknown = set(mapping).difference(allowed)
    if unknown:
        names = ", ".join(repr(name) for name in sorted(unknown))
        raise ExperimentConfigurationError(
            f"{field_name} contains unknown fields: {names}"
        )
    missing = required.difference(mapping)
    if missing:
        names = ", ".join(repr(name) for name in sorted(missing))
        raise ExperimentConfigurationError(
            f"{field_name} is missing required fields: {names}"
        )
    return mapping


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
