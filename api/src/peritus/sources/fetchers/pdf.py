"""PDF fetcher — finds open-access academic PDFs via Semantic Scholar and OCRs them.

search() returns paper metadata + abstract only; the expensive Mistral OCR runs
in fetch(), and only for candidates that survive triage.
"""

import asyncio

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.pdf_parser import parse_pdf_url
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_SS_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_PDF_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_SS_FIELDS = "title,authors,year,openAccessPdf,abstract,externalIds"
_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MAX_CHARS = 200_000


class PdfFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        if not settings.MISTRAL_API_KEY:
            logger.warning("MISTRAL_API_KEY not set — skipping PDF fetcher")
            return []

        papers = await _search_semantic_scholar(query, max_results)
        candidates = []
        for paper in papers:
            pdf_url = (paper.get("openAccessPdf") or {}).get("url")
            if not pdf_url:
                continue
            authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:3]) or None
            candidates.append(SourceCandidate(
                source_type=SourceType.PDF,
                url=pdf_url,
                title=paper.get("title") or "Untitled",
                author=authors,
                snippet=paper.get("abstract") or "",
                metadata={
                    "semantic_scholar_id": paper.get("paperId"),
                    "year": paper.get("year"),
                },
            ))
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        if not await _is_pdf_url(candidate.url):
            logger.debug("Skipping non-PDF URL: %s", candidate.url)
            return None
        text = await parse_pdf_url(candidate.url)
        if len(text) < 500:
            return None
        logger.info("PDF ingested: %r (%d chars)", candidate.title, len(text))
        return RawSource(
            source_type=SourceType.PDF,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text[:_MAX_CHARS],
            metadata=candidate.metadata,
        )


async def _is_pdf_url(url: str) -> bool:
    """Return True only if the URL resolves to an actual PDF."""
    if url.startswith("https://doi.org/") or url.startswith("http://doi.org/"):
        return False
    if url.lower().endswith(".pdf"):
        return True
    try:
        async with httpx.AsyncClient(
            timeout=10, headers=_PDF_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.head(url)
            ct = resp.headers.get("content-type", "")
            return "pdf" in ct.lower()
    except Exception:
        return False


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
