import asyncio
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from llm_auditkit.ocr import GoogleVisionOCRBackend, OCRException, SourceDocument
from llm_auditkit.ocr.models import identity
from llm_auditkit.ocr.sources import check_source, inspect_document, render_page
from llm_auditkit.ocr.store import validate_page
from llm_auditkit.ocr.vision import decode_annotation

from .helpers import config


def annotation():
    return {"full_text_annotation": {"text": "A Clerk\n", "pages": [{
        "width": 200, "height": 300, "blocks": [{
            "bounding_box": {"vertices": [{"x": 0, "y": 0}, {"x": 100, "y": 0},
                                            {"x": 100, "y": 20}, {"x": 0, "y": 20}]},
            "confidence": 0.95,
            "paragraphs": [{"words": [
                {"symbols": [{"text": "A", "property": {"detected_break": {"type": "SPACE"}}}]},
                {"symbols": [{"text": char} for char in "Clerk"]},
            ]}],
        }],
    }]}}


def test_vision_keeps_short_blocks_geometry_confidence_and_raw_response():
    raw = annotation()
    page_id = identity("page", "example")
    result = decode_annotation(raw, page_id)
    validate_page(result, page_id)
    assert result.blocks[0].text == "A Clerk"
    assert result.blocks[0].confidence == 0.95
    assert result.blocks[0].vertices[2] == (100, 20)
    assert result.raw_response is raw


@pytest.mark.parametrize("kind,expected", [("SPACE", "A B"), ("LINE_BREAK", "A\n B"), ("HYPHEN", "A-\n B")])
def test_detected_breaks_are_retained(kind, expected):
    raw = annotation()
    symbols = [{"text": "A", "property": {"detected_break": {"type": kind}}}, {"text": "B" if kind == "SPACE" else " B"}]
    raw["full_text_annotation"]["pages"][0]["blocks"][0]["paragraphs"][0]["words"] = [{"symbols": symbols}]
    assert decode_annotation(raw, "page").blocks[0].text == expected


def test_provider_errors_not_treated_as_blank_pages():
    with pytest.raises(OCRException, match="OCR error"):
        decode_annotation({"error": {"code": 3, "message": "invalid input"}}, "page")
    assert decode_annotation({}, "page").blocks == ()
    with pytest.raises(OCRException, match="without page"):
        decode_annotation({"full_text_annotation": {"text": "lost text"}}, "page")


@pytest.mark.parametrize("key", [None, "", " \t ", "synthetic-vision-key", " synthetic-vision-key "])
def test_api_key_or_adc_options_match_in_both_modes(monkeypatch, key):
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", key)
    # Other Google keys must not accidentally select key-based Vision auth.
    monkeypatch.setenv("GOOGLE_API_KEY", "unrelated-key")
    monkeypatch.setenv("GOOGLE_API_KEY_VERTEX", "unrelated-vertex-key")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/synthetic/adc.json")
    response = object()
    sync_client = SimpleNamespace(batch_annotate_images=Mock(return_value=response),
                                  transport=SimpleNamespace(close=Mock()))
    async_client = SimpleNamespace(batch_annotate_images=AsyncMock(return_value=response),
                                   transport=SimpleNamespace(close=AsyncMock()))
    sdk = SimpleNamespace(
        ImageAnnotatorClient=Mock(return_value=sync_client),
        ImageAnnotatorAsyncClient=Mock(return_value=async_client),
        AnnotateImageRequest=lambda **kwargs: kwargs,
        Feature=SimpleNamespace(Type=SimpleNamespace(DOCUMENT_TEXT_DETECTION="document-text")),
    )
    backend = GoogleVisionOCRBackend()
    monkeypatch.setattr(backend, "_sdk", lambda: sdk)
    decoded = object()
    monkeypatch.setattr(backend, "_decode_batch", Mock(return_value=decoded))
    for _ in range(2):
        assert backend.recognize(b"scan", "page", config(language_hints=("en",))) is decoded

    async def execute():
        for _ in range(2):
            assert await backend.recognize_async(b"scan", "page", config(language_hints=("en",))) is decoded
        await backend.close_async()

    asyncio.run(execute())
    backend.close()
    expected = {"client_options": {"api_key": key.strip()}} if key and key.strip() else {}
    sdk.ImageAnnotatorClient.assert_called_once_with(**expected)
    sdk.ImageAnnotatorAsyncClient.assert_called_once_with(**expected)
    request = {"image": {"content": b"scan"}, "features": [{"type_": "document-text"}],
               "image_context": {"language_hints": ["en"]}}
    for client in (sync_client, async_client):
        assert client.batch_annotate_images.call_count == 2
        client.batch_annotate_images.assert_called_with(requests=[request], timeout=120)
    sync_client.transport.close.assert_called_once()
    async_client.transport.close.assert_awaited_once()
    assert backend._client is backend._async_client is None


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_configured_api_key_failure_does_not_fall_back_to_adc(monkeypatch, mode, capsys):
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "synthetic-invalid-key")
    sdk = SimpleNamespace(
        ImageAnnotatorClient=Mock(side_effect=RuntimeError("rejected")),
        ImageAnnotatorAsyncClient=Mock(side_effect=RuntimeError("rejected")),
    )
    backend = GoogleVisionOCRBackend()
    monkeypatch.setattr(backend, "_sdk", lambda: sdk)
    with pytest.raises(RuntimeError, match="rejected"):
        if mode == "sync":
            backend.recognize(b"scan", "page", config())
        else:
            asyncio.run(backend.recognize_async(b"scan", "page", config()))
    constructor = sdk.ImageAnnotatorClient if mode == "sync" else sdk.ImageAnnotatorAsyncClient
    constructor.assert_called_once_with(client_options={"api_key": "synthetic-invalid-key"})
    captured = capsys.readouterr()
    assert "synthetic-invalid-key" not in captured.out + captured.err


def test_sync_async_sdk_paths_without_credentials_or_network():
    vision = pytest.importorskip("google.cloud.vision")
    from google.auth.credentials import AnonymousCredentials
    from google.api_core.gapic_v1.method import DEFAULT

    response = vision.BatchAnnotateImagesResponse(responses=[vision.AnnotateImageResponse(**annotation())])
    backend = GoogleVisionOCRBackend()
    backend._client = vision.ImageAnnotatorClient(credentials=AnonymousCredentials())
    rpc = Mock(return_value=response)
    transport = backend._client.transport
    transport._wrapped_methods[transport.batch_annotate_images] = rpc
    try:
        sync = backend.recognize(b"image", "page", config(language_hints=("en",)))
    finally:
        backend.close()

    async def execute():
        backend._async_client = vision.ImageAnnotatorAsyncClient(credentials=AnonymousCredentials())
        async_rpc = AsyncMock(return_value=response)
        transport = backend._async_client.transport
        transport._wrapped_methods[transport.batch_annotate_images] = async_rpc
        try:
            result = await backend.recognize_async(b"image", "page", config(language_hints=("en",)))
            return result, async_rpc
        finally:
            await backend.close_async()

    asynchronous, async_rpc = asyncio.run(execute())
    assert sync == asynchronous
    for call in (rpc.call_args, async_rpc.call_args):
        request = call.args[0].requests[0]
        assert request.image.content == b"image"
        assert list(request.image_context.language_hints) == ["en"]
        assert request.features[0].type_ == vision.Feature.Type.DOCUMENT_TEXT_DETECTION
        assert call.kwargs["timeout"] == 120
        assert call.kwargs["retry"] is DEFAULT


def test_png_source_identity_and_change_detection(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "scan.png"
    with Image.new("RGB", (20, 20), "white") as image:
        image.save(path)
    document = SourceDocument(path, {"year": 1950})
    plan = inspect_document(document, config())
    assert plan.page_count == 1
    assert render_page(plan, 1, config()) == path.read_bytes()
    moved = tmp_path / "different-name.png"
    moved.write_bytes(path.read_bytes())
    assert inspect_document(SourceDocument(moved, document.metadata), config()).source_id == plan.source_id
    path.write_bytes(b"changed")
    with pytest.raises(OCRException, match="changed"):
        check_source(plan)


def test_pdf_uses_each_requested_page_and_dpi(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"synthetic PDF")
    calls = []
    class Image:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def save(self, stream, format):
            stream.write(b"raster")
    def convert(path, **kwargs):
        calls.append(kwargs)
        return [Image()]
    tools = SimpleNamespace(pdfinfo_from_path=lambda *args, **kwargs: {"Pages": 3}, convert_from_path=convert)
    monkeypatch.setattr("llm_auditkit.ocr.sources._pdf_tools", lambda: tools)
    plan = inspect_document(SourceDocument(source), config())
    for number in range(1, plan.page_count + 1):
        assert render_page(plan, number, config()) == b"raster"
    assert [call["first_page"] for call in calls] == [1, 2, 3]
    assert [call["last_page"] for call in calls] == [1, 2, 3]
    assert all(call["dpi"] == 300 and call["thread_count"] == 1 for call in calls)


def test_real_local_multi_page_pdf_rendering_when_poppler_installed(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("pdf2image")
    if not shutil.which("pdftoppm") or not shutil.which("pdfinfo"):
        pytest.skip("optional system Poppler is not installed")
    source = tmp_path / "synthetic.pdf"
    with Image.new("RGB", (30, 30), "red") as first, Image.new("RGB", (30, 30), "blue") as second:
        first.save(source, format="PDF", save_all=True, append_images=[second], resolution=72)
    cfg = config(dpi=72)
    plan = inspect_document(SourceDocument(source), cfg)
    assert plan.page_count == 2
    assert render_page(plan, 1, cfg) != render_page(plan, 2, cfg)


@pytest.mark.parametrize("suffix", [".txt", ".tiff", ".csv"])
def test_unsupported_source_types(tmp_path, suffix):
    path = tmp_path / ("source" + suffix)
    path.write_bytes(b"data")
    with pytest.raises(OCRException, match="local PDF, PNG or JPEG"):
        inspect_document(SourceDocument(path), config())
