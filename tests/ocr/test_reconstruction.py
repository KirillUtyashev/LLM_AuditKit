import copy
import json
from dataclasses import asdict, replace

import pytest

from llm_auditkit.ocr.models import OCRException
from llm_auditkit.ocr.reconstruction import build_request, parse_response, reconstruction_fingerprint
from llm_auditkit.ocr.store import validate_page

from .helpers import config, page, response_for


def test_preserves_short_headings_and_merges_blocks():
    source = page()
    parsed = parse_response(json.dumps(response_for([asdict(block) for block in source.blocks])), source)
    assert parsed[0]["raw_text"] == "CLERK\nSend resume to Box 17."
    assert [span["block_id"] for span in parsed[0]["source_spans"]] == [block.block_id for block in source.blocks]


def test_splits_block_and_keeps_exclusions_and_exact_offsets():
    source = page(texts=("CLERK. Cook needed. News.",))
    value = {
        "ads": [{"key": "cook", "text": "Cook needed."}, {"key": "clerk", "text": "CLERK."}],
        "blocks": [{"block_id": source.blocks[0].block_id, "segments": [
            {"text": "CLERK. ", "ad_key": "clerk", "reason": ""},
            {"text": "Cook needed. ", "ad_key": "cook", "reason": ""},
            {"text": "News.", "ad_key": None, "reason": "unrelated news"},
        ]}],
    }
    parsed = parse_response(json.dumps(value), source)
    assert [ad["Text"] for ad in parsed] == ["CLERK.", "Cook needed."]
    assert parsed[1]["source_spans"][0] == {"block_id": source.blocks[0].block_id, "start": 7, "end": 20}
    value["ads"].reverse()
    assert parse_response(json.dumps(value), source) == parsed


def test_zero_ads_requires_complete_excluded_text():
    source = page(texts=("Weather forecast",))
    value = {"ads": [], "blocks": [{"block_id": source.blocks[0].block_id, "segments": [
        {"text": source.blocks[0].text, "ad_key": None, "reason": "weather report"},
    ]}]}
    assert parse_response(json.dumps(value), source) == []


def test_equivalent_adjacent_segmentation_preserves_ad_identity_and_raw_text():
    source = page(texts=("CLERK needed.",))
    value = response_for([asdict(block) for block in source.blocks])
    original = parse_response(json.dumps(value), source)
    value["blocks"][0]["segments"] = [
        {"text": "CLERK", "ad_key": "ad", "reason": ""},
        {"text": " needed.", "ad_key": "ad", "reason": ""},
    ]
    assert parse_response(json.dumps(value), source) == original


@pytest.mark.parametrize("cleaned", ["CLERK Send resume to Box 18.", "COOK Send resume to Box 17.",
                                     "CLERK Send resume to Box 17. No experience needed."])
def test_cleanup_cannot_invent_content_or_change_contacts(cleaned):
    source = page()
    value = response_for([asdict(block) for block in source.blocks])
    value["ads"][0]["text"] = cleaned
    with pytest.raises(OCRException, match="letters/digits"):
        parse_response(json.dumps(value), source)


def test_cleanup_can_join_broken_words_and_fix_punctuation():
    source = page(texts=("CLERK: Send re-\nsume to Box 17",))
    value = response_for([asdict(block) for block in source.blocks])
    value["ads"][0]["text"] = "Clerk: Send resume to Box 17."
    assert parse_response(json.dumps(value), source)[0]["Text"] == value["ads"][0]["text"]


@pytest.mark.parametrize("mutation", [
    lambda value: value["blocks"].pop(),
    lambda value: value["blocks"].append(copy.deepcopy(value["blocks"][0])),
    lambda value: value["blocks"][0].update(block_id="unknown"),
    lambda value: value["blocks"][0]["segments"][0].update(text="modified"),
    lambda value: value["blocks"][0]["segments"][0].update(ad_key="unknown"),
    lambda value: value["blocks"][0]["segments"][0].update(ad_key=[]),
    lambda value: value["blocks"][0]["segments"][0].update(ad_key=None, reason=""),
    lambda value: value["blocks"][0]["segments"].clear(),
    lambda value: value["ads"].append({"key": "orphan", "text": "invented ad"}),
    lambda value: value["ads"].append(copy.deepcopy(value["ads"][0])),
    lambda value: value["ads"][0].update(text=" "),
    lambda value: value.update(extra=True),
])
def test_rejects_lost_duplicated_invented_or_untraceable_source(mutation):
    source = page()
    value = response_for([asdict(block) for block in source.blocks])
    mutation(value)
    with pytest.raises(OCRException):
        parse_response(json.dumps(value), source)


@pytest.mark.parametrize("value", [None, "```json\n{}\n```", "[]", '{"ads":[],"ads":[],"blocks":[]}', '{"ads":NaN,"blocks":[]}'])
def test_strict_json(value):
    with pytest.raises(OCRException):
        parse_response(value, page())


def test_whole_page_request_covers_all_100_blocks_not_fixed_four_chunks():
    source = page(texts=tuple(f"Short heading {index}" for index in range(100)))
    request = build_request(source, {"year": 1950}, config(), "fingerprint")
    blocks = json.loads(request.prompt.split("\n", 1)[1])["blocks"]
    assert len(blocks) == 100
    assert blocks[-1]["text"] == "Short heading 99"
    assert "1950" in request.prompt


def test_prompt_limit_fails_instead_of_truncating():
    with pytest.raises(OCRException, match="no text was truncated"):
        build_request(page(), {}, config(max_page_characters=20), "fingerprint")


def test_fingerprint_ignores_execution_settings_not_model_or_sources():
    original = config()
    fingerprint = reconstruction_fingerprint(original, ["source-a", "source-b"])
    modified = copy.deepcopy(original)
    modified.inference.batch_size = 10
    modified = replace(modified, save_after_each_batch=False)
    assert reconstruction_fingerprint(modified, ["source-b", "source-a"]) == fingerprint
    modified.inference.models[0].parameters["temperature"] = 1
    assert reconstruction_fingerprint(modified, ["source-a", "source-b"]) != fingerprint


@pytest.mark.parametrize("mutation", [
    lambda source: replace(source, width=0),
    lambda source: replace(source, page_id="wrong"),
    lambda source: replace(source, blocks=source.blocks + source.blocks),
    lambda source: replace(source, blocks=(replace(source.blocks[0], block_id="wrong"),)),
    lambda source: replace(source, blocks=(replace(source.blocks[0], confidence=float("nan")),)),
    lambda source: replace(source, blocks=(replace(source.blocks[0], vertices=()),)),
])
def test_provider_records_are_validated(mutation):
    source = page()
    with pytest.raises(OCRException):
        validate_page(mutation(source), source.page_id)
