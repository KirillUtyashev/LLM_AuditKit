"""Lazy Google Vision integration; no SDK-specific objects escape this module."""

from __future__ import annotations

from .models import OCRBlock, OCRConfig, OCRException, OCRPage, identity


class GoogleVisionOCRBackend:
    """Use Application Default Credentials and the SDK's transport retries."""

    def __init__(self) -> None:
        self._client = None
        self._async_client = None

    @staticmethod
    def _sdk():
        try:
            from google.cloud import vision
            return vision
        except ImportError as error:
            raise OCRException('install OCR dependencies with pip install "llm-auditkit[ocr]"') from error

    def recognize(self, image: bytes, page_id: str, config: OCRConfig) -> OCRPage:
        if self._client is None:
            self._client = self._sdk().ImageAnnotatorClient()
        response = self._client.document_text_detection(
            image={"content": image}, image_context={"language_hints": list(config.language_hints)},
            timeout=config.timeout,
        )
        return self._decode(response, page_id)

    async def recognize_async(self, image: bytes, page_id: str, config: OCRConfig) -> OCRPage:
        if self._async_client is None:
            self._async_client = self._sdk().ImageAnnotatorAsyncClient()
        response = await self._async_client.document_text_detection(
            image={"content": image}, image_context={"language_hints": list(config.language_hints)},
            timeout=config.timeout,
        )
        return self._decode(response, page_id)

    @staticmethod
    def _decode(response, page_id: str) -> OCRPage:
        from google.protobuf.json_format import MessageToDict
        raw = MessageToDict(response._pb, preserving_proto_field_name=True)
        return decode_annotation(raw, page_id)

    def close(self) -> None:
        if self._client is not None:
            self._client.transport.close()
            self._client = None

    async def close_async(self) -> None:
        if self._async_client is not None:
            await self._async_client.transport.close()
            self._async_client = None


def decode_annotation(raw: dict, page_id: str) -> OCRPage:
    """Normalize all textual blocks, preserving the untouched provider response."""
    if raw.get("error", {}).get("code") or raw.get("error", {}).get("message"):
        raise OCRException("Google Vision returned an OCR error; no text accepted")
    annotation = raw.get("full_text_annotation", {})
    if not annotation and raw.get("text_annotations"):
        raise OCRException("OCR returned text annotations without document blocks")
    pages = annotation.get("pages", [])
    if len(pages) > 1:
        raise OCRException("single raster request unexpectedly returned multiple pages")
    if not pages:
        if annotation.get("text", "").strip():
            raise OCRException("OCR returned text without page/block geometry")
        return OCRPage(page_id, 0, 0, (), raw)
    page = pages[0]
    blocks = []
    for block in page.get("blocks", []):
        paragraphs = []
        for paragraph in block.get("paragraphs", []):
            words = []
            for word in paragraph.get("words", []):
                parts = []
                for symbol in word.get("symbols", []):
                    text = symbol.get("text", "")
                    detected = symbol.get("property", {}).get("detected_break", {})
                    break_type = detected.get("type")
                    separator = {"SPACE": " ", "SURE_SPACE": " ", "EOL_SURE_SPACE": "\n",
                                 "LINE_BREAK": "\n", "HYPHEN": "-\n"}.get(break_type, "")
                    if break_type == "HYPHEN" and text.endswith("-"):
                        separator = "\n"
                    parts.append(separator + text if detected.get("is_prefix") else text + separator)
                words.append("".join(parts))
            # Missing break annotations still need a boundary between OCR words.
            paragraphs.append("".join(
                text + (" " if index < len(words) - 1 and text and not text[-1].isspace() else "")
                for index, text in enumerate(words)
            ).rstrip())
        text = "\n".join(paragraphs).strip()
        if not text:
            continue
        vertices = tuple((vertex.get("x", 0), vertex.get("y", 0))
                         for vertex in block.get("bounding_box", {}).get("vertices", []))
        block_id = identity("block", [page_id, text, vertices])
        blocks.append(OCRBlock(block_id, text, vertices, block.get("confidence", 0.0)))
    if annotation.get("text", "").strip() and not blocks:
        raise OCRException("OCR returned full text but no usable text blocks")
    return OCRPage(page_id, page.get("width", 0), page.get("height", 0), tuple(blocks), raw)
