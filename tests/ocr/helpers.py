"""Invented source content and credential-free test doubles."""

import json

from llm_auditkit.inference import (
    InferenceConfig, InferenceResult, ModelConfig, RenderedPrompt,
)
from llm_auditkit.ocr.models import OCRBlock, OCRConfig, OCRPage, identity


def config(**kwargs):
    return OCRConfig(InferenceConfig([ModelConfig("extract", "test", "fake", {"temperature": 0})], 1), **kwargs)


def page(page_id=None, texts=("CLERK", "Send resume to Box 17.")):
    page_id = page_id or identity("page", "example")
    blocks = []
    for index, text in enumerate(texts):
        vertices = ((0, index * 10), (90, index * 10), (90, index * 10 + 9), (0, index * 10 + 9))
        blocks.append(OCRBlock(identity("block", [page_id, text, vertices]), text, vertices, 0.9))
    return OCRPage(page_id, 100, 1000, tuple(blocks), {"synthetic": True})


def response_for(blocks):
    return {
        "ads": [{"key": "ad", "text": "\n".join(block["text"] for block in blocks)}] if blocks else [],
        "blocks": [{"block_id": block["block_id"], "segments": [
            {"text": block["text"], "ad_key": "ad", "reason": ""},
        ]} for block in blocks],
    }


class Backend:
    def __init__(self, texts=("CLERK", "Send resume to Box 17.")):
        self.texts = texts
        self.sync_calls = 0
        self.async_calls = 0

    def recognize(self, image, page_id, config):
        self.sync_calls += 1
        return page(page_id, self.texts)

    async def recognize_async(self, image, page_id, config):
        self.async_calls += 1
        return page(page_id, self.texts)


class Adapter:
    def __init__(self, callback=None):
        self.callback = callback
        self.sync_calls = []
        self.async_calls = []

    def render_batch(self, requests, models):
        return [RenderedPrompt(request.request_id, request.prompt, request.system_prompt) for request in requests]

    def _results(self, requests):
        results = []
        for request in requests:
            blocks = json.loads(request.prompt.split("\n", 1)[1])["blocks"]
            content = json.dumps(response_for(blocks))
            result = InferenceResult(request.request_id, request.model_config_id, content, request.metadata.copy())
            if self.callback is not None:
                result = self.callback(request, result)
            results.append(result)
        return results

    def execute_batch(self, requests, models):
        self.sync_calls.append(list(requests))
        return self._results(requests)

    async def execute_batch_async(self, requests, models):
        self.async_calls.append(list(requests))
        return self._results(requests)
