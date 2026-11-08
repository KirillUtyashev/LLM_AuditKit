"""Strict YAML configuration and common preflight validation."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from llm_auditkit.inference import InferenceConfig, InferenceConfigurationError, ModelConfig
from llm_auditkit.inference.validation import validate_inference_config

from .models import OCRConfig, OCRException, OCRRunConfig, SourceDocument, canonical_json


def validate_config(config: OCRConfig) -> None:
    if not isinstance(config, OCRConfig):
        raise OCRException("config must be an OCRConfig")
    try:
        validate_inference_config(config.inference)
    except InferenceConfigurationError as error:
        raise OCRException(f"invalid shared inference configuration: {error}") from error
    if len(config.inference.models) != 1:
        raise OCRException("OCR requires exactly one model configuration per run")
    for name in ("dpi", "max_page_characters"):
        value = getattr(config, name)
        if type(value) is not int or value <= 0:
            raise OCRException(f"{name} must be a positive integer")
    if type(config.timeout) not in (int, float) or not math.isfinite(config.timeout) or config.timeout <= 0:
        raise OCRException("timeout must be a finite positive number")
    if type(config.save_after_each_batch) is not bool:
        raise OCRException("save_after_each_batch must be a boolean")
    if not isinstance(config.language_hints, (tuple, list)) or any(
        not isinstance(hint, str) or not hint.strip() for hint in config.language_hints
    ):
        raise OCRException("language_hints must contain nonempty strings")


def validate_metadata(metadata: object) -> None:
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not key.strip() for key in metadata
    ):
        raise OCRException("source metadata must be a mapping with nonempty string keys")
    if any(type(value) not in (str, int, float, bool, type(None)) for value in metadata.values()):
        raise OCRException("source metadata values must be JSON scalars (quote dates)")
    try:
        canonical_json(metadata)
    except (ValueError, TypeError) as error:
        raise OCRException("source metadata must contain finite JSON scalars") from error


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise OCRException("YAML mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _mapping(value: object, name: str, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise OCRException(f"invalid or missing keys in {name}")
    return value


def _path(value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise OCRException("paths must be nonempty strings")
    return (base / value).resolve()


def load_ocr_run_config(path: str | Path) -> OCRRunConfig:
    """Resolve paths relative to YAML; reject typos and duplicate keys."""
    config_path = Path(path).resolve()
    try:
        root = yaml.load(config_path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
        root = _mapping(root, "configuration", {"documents", "output", "execution", "inference"}, {"ocr"})
        if not isinstance(root["documents"], list) or not root["documents"]:
            raise OCRException("documents must be a nonempty list")
        documents = []
        for item in root["documents"]:
            item = _mapping(item, "document", {"path"}, {"metadata"})
            metadata = item.get("metadata", {})
            validate_metadata(metadata)
            documents.append(SourceDocument(_path(item["path"], config_path.parent), metadata))
        output = _mapping(root["output"], "output", {"path", "checkpoint_directory"})
        execution = _mapping(root["execution"], "execution", {"mode", "batch_size"}, {"save_after_each_batch"})
        if execution["mode"] not in ("sync", "async"):
            raise OCRException("execution.mode must be sync or async")
        inference = _mapping(root["inference"], "inference", {"model"})
        model = _mapping(inference["model"], "inference.model", {"config_id", "provider", "model"}, {"parameters"})
        settings = _mapping(root.get("ocr", {}), "ocr", set(), {"dpi", "language_hints", "timeout", "max_page_characters"})
        config = OCRConfig(
            inference=InferenceConfig([ModelConfig(**model)], execution["batch_size"]),
            save_after_each_batch=execution.get("save_after_each_batch", True), **settings,
        )
        validate_config(config)
        output_path = _path(output["path"], config_path.parent)
        checkpoint = _path(output["checkpoint_directory"], config_path.parent)
        protected = [config_path, *(doc.path for doc in documents)]
        validate_paths(output_path, checkpoint, protected)
        return OCRRunConfig(tuple(documents), config, output_path, checkpoint, execution["mode"])
    except OCRException:
        raise
    except (OSError, yaml.YAMLError, TypeError, ValueError) as error:
        raise OCRException(f"cannot load OCR configuration: {type(error).__name__}") from error


def validate_paths(output: Path, checkpoint: Path, protected: list[Path]) -> None:
    if output.suffix.lower() != ".csv":
        raise OCRException("output path must end in .csv")
    if output == checkpoint or checkpoint in output.parents:
        raise OCRException("output CSV must be outside the checkpoint directory")
    for path in protected:
        same_file = output.exists() and path.exists() and output.samefile(path)
        if same_file or path == output or path == checkpoint or checkpoint in path.parents:
            raise OCRException("output/checkpoint paths must not overwrite or contain inputs/configuration")
