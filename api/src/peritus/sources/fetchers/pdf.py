"""PDF fetcher — finds open-access academic PDFs via Semantic Scholar and OCRs them.

search() returns paper metadata + abstract only; the expensive Mistral OCR runs
in fetch(), and only for candidates that survive triage.
"""

import asyncio

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.http import RESEARCH_UA, shared_client
from peritus.infrastructure.pdf_parser import parse_pdf_url
from peritus.sources.domain import (
    Identifiers,
    RawSource,
    SourceCandidate,
    SourceType,
    resolved_identifiers,
)
from peritus.sources.fetchers.base import (
    STATUS_ERROR,
    STATUS_RATE_LIMITED,
    STATUS_TIMEOUT,
    note_search_failure,
)

logger = get_logger(__name__)

_SS_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_PDF_HEADERS = {"User-Agent": RESEARCH_UA}
_SS_FIELDS = "title,authors,year,openAccessPdf,abstract,externalIds"
_HEADERS = {"User-Agent": RESEARCH_UA}
_MAX_CHARS = 200_000


def semantic_scholar_headers() -> dict[str, str]:
    """Headers for any Semantic Scholar API call, with the key when there is one.

    Shared with snowballing: both hit the same API, and without a key both draw
    on the same rate-limited unauthenticated pool.
    """
    headers = dict(_HEADERS)
    if settings.S2_API_KEY:
        headers["x-api-key"] = settings.S2_API_KEY
    return headers


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
            # Semantic Scholar is already asked for externalIds (see _SS_FIELDS)
            # and used to throw them away, which meant the one fetcher that
            # knows a paper's DOI, arXiv id and PMCID contributed no identity at
            # all — and paid for OCR on papers Europe PMC serves free.
            ids = identifiers_from_external(paper.get("externalIds"))
            ids = ids.with_(s2_id=paper.get("paperId")) if paper.get("paperId") else ids
            candidates.append(
                SourceCandidate(
                    source_type=SourceType.PDF,
                    url=pdf_url,
                    title=paper.get("title") or "Untitled",
                    author=authors,
                    snippet=paper.get("abstract") or "",
                    metadata={
                        "semantic_scholar_id": paper.get("paperId"),
                        "year": paper.get("year"),
                        "abstract": paper.get("abstract") or "",
                        "oa_pdf_url": pdf_url,
                        "is_open_access": True,
                        **ids.to_dict(),
                    },
                    identifiers=ids,
                )
            )
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        # Identity first, OCR second. Semantic Scholar hands over a paper's DOI,
        # arXiv id and PMCID, and a large share of the open-access PDFs it finds
        # are also served free as ar5iv HTML or Europe PMC JATS — better text
        # than OCR produces, at no cost. Only when none of those exist does this
        # fetcher do the thing it is named for.
        from peritus.sources.fulltext import METHOD_OA_PDF, resolve_full_text

        resolved = await resolve_full_text(resolved_identifiers(candidate))
        if resolved is not None:
            text, method = resolved.text, resolved.method
        else:
            if not await _is_pdf_url(candidate.url):
                logger.debug("Skipping non-PDF URL: %s", candidate.url)
                return None
            text, method = await parse_pdf_url(candidate.url), METHOD_OA_PDF
        if len(text) < 500:
            return None

        abstract = candidate.metadata.get("abstract") or candidate.snippet
        # The abstract leads, as it does for every other scholarly fetcher, so
        # the head of the text — the part the validator preview always sees — is
        # the paper's own statement of its claim rather than a title page.
        body = f"{candidate.title}\n\n{abstract}\n\n{text}" if abstract else text
        logger.info("PDF ingested: %r (%d chars, %s)", candidate.title, len(text), method)
        metadata = {**candidate.metadata, "full_text": True, "full_text_method": method}
        return RawSource(
            source_type=SourceType.PDF,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=body[:_MAX_CHARS],
            metadata=metadata,
            identifiers=candidate.identifiers,
        )


def identifiers_from_external(external: dict | None) -> Identifiers:
    """Semantic Scholar's ``externalIds`` block → typed identifiers.

    Shared with snowballing, which reads the same block off the citation graph.
    """
    external = external or {}
    return Identifiers.build(
        doi=external.get("DOI"),
        arxiv_id=external.get("ArXiv"),
        pmid=external.get("PubMed"),
        pmcid=external.get("PubMedCentral"),
    )


async def _is_pdf_url(url: str) -> bool:
    """Return True only if the URL resolves to an actual PDF."""
    if url.startswith("https://doi.org/") or url.startswith("http://doi.org/"):
        return False
    if url.lower().endswith(".pdf"):
        return True
    try:
        client = shared_client(timeout=10, headers=_PDF_HEADERS, guarded=True)
        resp = await client.head(url)
        ct = resp.headers.get("content-type", "")
        return "pdf" in ct.lower()
    except Exception as exc:
        logger.debug("PDF content-type probe failed for %r: %s", url, exc)
        return False


async def _search_semantic_scholar(topic: str, limit: int) -> list[dict]:
    for attempt in range(3):
        try:
            client = shared_client(
                timeout=20, headers=semantic_scholar_headers(), follow_redirects=False
            )
            resp = await client.get(
                _SS_URL,
                params={"query": topic, "fields": _SS_FIELDS, "limit": limit * 2},
            )
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                # WARNING, and named: a pdf channel that returns nothing
                # because of this used to be invisible at DEBUG.
                logger.warning(
                    "pdf fetcher: Semantic Scholar rate-limited (429%s), retrying in %ds",
                    "" if settings.S2_API_KEY else ", no S2_API_KEY",
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            papers = resp.json().get("data", [])
            with_pdf = [p for p in papers if (p.get("openAccessPdf") or {}).get("url")]
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
                    with_pdf += [p for p in extra if (p.get("openAccessPdf") or {}).get("url")]
            return with_pdf[:limit]
        except httpx.TimeoutException as exc:
            logger.warning("Semantic Scholar search timed out for %r: %s", topic, exc)
            note_search_failure(STATUS_TIMEOUT, f"Semantic Scholar: {exc}")
            return []
        except Exception as exc:
            logger.warning("Semantic Scholar search failed for %r: %s", topic, exc)
            note_search_failure(STATUS_ERROR, f"Semantic Scholar: {type(exc).__name__}: {exc}")
            return []
    logger.warning("pdf fetcher: Semantic Scholar gave up after retries for %r", topic)
    note_search_failure(
        STATUS_RATE_LIMITED,
        "Semantic Scholar returned 429 after 3 attempts"
        + ("" if settings.S2_API_KEY else " (no S2_API_KEY)"),
    )
    return []
