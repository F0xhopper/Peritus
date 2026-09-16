"""Mistral OCR — parse a PDF to markdown text via the Mistral OCR REST API."""

import base64

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.http import shared_client

logger = get_logger(__name__)

_OCR_URL = "https://api.mistral.ai/v1/ocr"
_MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB hard limit


async def parse_pdf_url(url: str) -> str:
    """OCR a publicly accessible PDF by URL. Returns markdown text."""
    if not settings.MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY not set")
    client = shared_client(timeout=120, follow_redirects=False)
    resp = await client.post(
        _OCR_URL,
        headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
        json={
            "model": settings.MISTRAL_OCR_MODEL,
            "document": {"type": "document_url", "document_url": url},
        },
    )
    resp.raise_for_status()
    pages = resp.json().get("pages", [])
    return "\n\n".join(p.get("markdown", "") for p in pages)


async def parse_pdf_bytes(data: bytes) -> str:
    """OCR a PDF from raw bytes. Returns markdown text."""
    if not settings.MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY not set")
    if len(data) > _MAX_PDF_BYTES:
        data = data[:_MAX_PDF_BYTES]
    b64 = base64.b64encode(data).decode()
    client = shared_client(timeout=120, follow_redirects=False)
    resp = await client.post(
        _OCR_URL,
        headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
        json={
            "model": settings.MISTRAL_OCR_MODEL,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        },
    )
    resp.raise_for_status()
    pages = resp.json().get("pages", [])
    return "\n\n".join(p.get("markdown", "") for p in pages)
