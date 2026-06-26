"""PDF fetcher — finds open-access academic PDFs via Semantic Scholar and OCRs them."""

import asyncio

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.pdf_parser import parse_pdf_url
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_SS_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_SS_FIELDS = "title,authors,year,openAccessPdf,abstract,externalIds"
_HEADERS = {"User-Agent": "Peritus/2.0 (educational tool; foxhopper16@gmail.com)"}
_MAX_CHARS = 200_000


class PdfFetcher:
    async def fetch(self, topic: str, max_results: int = 4) -> list[RawSource]:
        if not settings.MISTRAL_API_KEY:
            logger.warning("MISTRAL_API_KEY not set — skipping PDF fetcher")
            return []

        papers = await _search_semantic_scholar(topic, max_results)
        sources: list[RawSource] = []

        for paper in papers:
            pdf_info = paper.get("openAccessPdf") or {}
            pdf_url = pdf_info.get("url")
            if not pdf_url:
                continue
            try:
                text = await parse_pdf_url(pdf_url)
                if len(text) < 500:
                    continue
                authors = ", ".join(
                    a.get("name", "") for a in paper.get("authors", [])[:3]
                ) or None
                sources.append(RawSource(
                    source_type=SourceType.PDF,
                    url=pdf_url,
                    title=paper.get("title") or "Untitled",
                    author=authors,
                    text=text[:_MAX_CHARS],
                    metadata={
                        "semantic_scholar_id": paper.get("paperId"),
                        "year": paper.get("year"),
                    },
                ))
                logger.info("PDF ingested: %r (%d chars)", paper.get("title"), len(text))
            except Exception as exc:
                logger.warning("PDF fetch/OCR failed for %r: %s", pdf_url, exc)

        return sources


async def _search_semantic_scholar(topic: str, limit: int) -> list[dict]:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
                resp = await client.get(
                    _SS_URL,
                    params={"query": topic, "fields": _SS_FIELDS, "limit": limit * 2},
                )
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    logger.debug("Semantic Scholar rate-limited, retrying in %ds", wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                papers = resp.json().get("data", [])
                with_pdf = [
                    p for p in papers
                    if (p.get("openAccessPdf") or {}).get("url")
                ]
                if len(with_pdf) < limit and resp.json().get("next"):
                    # Not enough open-access results — fetch a second page
                    resp2 = await client.get(
                        _SS_URL,
                        params={
                            "query": topic,
                            "fields": _SS_FIELDS,
                            "limit": limit * 3,
                            "offset": limit * 2,
                        },
                    )
                    if resp2.status_code == 200:
                        extra = resp2.json().get("data", [])
                        with_pdf += [
                            p for p in extra
                            if (p.get("openAccessPdf") or {}).get("url")
                        ]
                return with_pdf[:limit]
        except Exception as exc:
            logger.warning("Semantic Scholar search failed for %r: %s", topic, exc)
            return []
    logger.warning("Semantic Scholar gave up after retries for %r", topic)
    return []
