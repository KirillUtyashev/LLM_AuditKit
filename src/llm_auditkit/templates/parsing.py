"""Association and domain parsing for normalized template-generation results."""

from __future__ import annotations

from collections.abc import Sequence

from llm_auditkit.inference import InferenceResult

from .exceptions import TemplateResponseParseError, TemplateResultAssociationError
from .identity import build_generation_fingerprint, build_template_request_id
from .models import TemplateGenerationConfig, TemplateOutputRecord
from .prompts import extract_placeholder_names, has_valid_placeholder_syntax


def parse_template_batch(
    results: Sequence[InferenceResult],
    expected_scenario_ids: Sequence[str],
    config: TemplateGenerationConfig,
) -> list[TemplateOutputRecord]:
    """Associate a complete batch by request ID and restore scenario order."""

    fingerprint = build_generation_fingerprint(config)
    expected_by_request = {
        build_template_request_id(scenario_id, fingerprint): scenario_id
        for scenario_id in expected_scenario_ids
    }
    if len(expected_by_request) != len(expected_scenario_ids):
        raise TemplateResultAssociationError(
            "expected scenario IDs must be unique within a template batch"
        )
    if len(results) != len(expected_scenario_ids):
        raise TemplateResultAssociationError(
            "template inference result cardinality does not match the submitted batch"
        )

    actual_by_request: dict[str, InferenceResult] = {}
    for result in results:
        if not isinstance(result, InferenceResult):
            raise TemplateResultAssociationError(
                "template inference results must be InferenceResult values"
            )
        if result.request_id in actual_by_request:
            raise TemplateResultAssociationError(
                f"duplicate template inference result ID {result.request_id!r}"
            )
        actual_by_request[result.request_id] = result

    if set(actual_by_request) != set(expected_by_request):
        raise TemplateResultAssociationError(
            "template inference result IDs do not match the submitted batch"
        )

    return [
        parse_template_result(
            actual_by_request[request_id],
            scenario_id,
            config,
        )
        for request_id, scenario_id in expected_by_request.items()
    ]


def parse_template_result(
    result: InferenceResult,
    scenario_id: str,
    config: TemplateGenerationConfig,
) -> TemplateOutputRecord:
    """Convert one safely associated normalized result into a stage record."""

    fingerprint = build_generation_fingerprint(config)
    expected_request_id = build_template_request_id(scenario_id, fingerprint)
    if result.request_id != expected_request_id:
        raise TemplateResultAssociationError(
            "template result request ID does not match its scenario"
        )
    if result.model_config_id != config.model_config_id:
        raise TemplateResultAssociationError(
            "template result model configuration does not match the generation plan"
        )
    if result.metadata.get("scenario_id") != scenario_id:
        raise TemplateResultAssociationError(
            "template result metadata scenario_id does not match its request"
        )
    if result.metadata.get("generation_fingerprint") != fingerprint:
        raise TemplateResultAssociationError(
            "template result metadata fingerprint does not match its request"
        )

    record_values = {
        "scenario_id": scenario_id,
        "request_id": result.request_id,
        "generation_fingerprint": fingerprint,
        "model_config_id": config.model_config_id,
    }
    if result.error is not None:
        return TemplateOutputRecord(
            **record_values,
            error_type=result.error.type,
            error_message=result.error.message,
        )

    try:
        templates = parse_template_contents(result, config)
    except TemplateResponseParseError as error:
        return TemplateOutputRecord(
            **record_values,
            error_type=type(error).__name__,
            error_message=str(error),
        )
    return TemplateOutputRecord(**record_values, templates=templates)


def parse_template_contents(
    result: InferenceResult,
    config: TemplateGenerationConfig,
) -> list[str]:
    """Validate ordered structured template strings from one successful result."""

    expected_fields = [
        f"template_{position}"
        for position in range(1, config.templates_per_scenario + 1)
    ]
    if result.structured_content is None:
        raise TemplateResponseParseError(
            "successful template result has no structured content"
        )
    if list(result.structured_content) != expected_fields:
        raise TemplateResponseParseError(
            "template result fields do not match the configured cardinality"
        )
    templates = []
    for field in expected_fields:
        value = result.structured_content[field]
        if not isinstance(value, str) or not value.strip():
            raise TemplateResponseParseError(
                f"template result field {field!r} must be a non-empty string"
            )
        templates.append(value.strip())
    validate_template_contents(templates, config.required_placeholders)
    return templates


def validate_template_contents(
    templates: Sequence[str],
    required_placeholders: Sequence[str],
) -> None:
    """Validate distinct content and the canonical placeholder contract."""

    if len(set(templates)) != len(templates):
        raise TemplateResponseParseError(
            "generated templates must be pairwise distinct"
        )
    required = set(required_placeholders)
    for position, template in enumerate(templates, start=1):
        if not has_valid_placeholder_syntax(template):
            raise TemplateResponseParseError(
                f"template_{position} contains invalid double-brace placeholder syntax"
            )
        found = set(extract_placeholder_names(template))
        missing = sorted(required.difference(found))
        unknown = sorted(found.difference(required))
        if missing:
            rendered = ", ".join(repr(name) for name in missing)
            raise TemplateResponseParseError(
                f"template_{position} is missing required placeholders: {rendered}"
            )
        if unknown:
            rendered = ", ".join(repr(name) for name in unknown)
            raise TemplateResponseParseError(
                f"template_{position} contains unknown placeholders: {rendered}"
            )
