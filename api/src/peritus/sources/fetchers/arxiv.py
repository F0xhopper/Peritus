"""ArXiv fetcher — searches papers (title + abstract), fetches full HTML text via ar5iv."""

import asyncio
import re

import arxiv  # type: ignore
import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import (
    Identifiers,
    RawSource,
    SourceCandidate,
    SourceType,
    resolved_identifiers,
)

logger = get_logger(__name__)

_AR5IV = "https://ar5iv.labs.arxiv.org/html/"

# Shared with the citation-snowballing step in the builder.
HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
MIN_FULL_TEXT = 3_000
MAX_FULL_TEXT = 120_000


class ArxivFetcher:
    async def search(self, query: str, max_results: int = 3) -> list[SourceCandidate]:
        try:
            papers = await asyncio.to_thread(
                lambda: list(arxiv.Client().results(
                    arxiv.Search(query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)
                ))
            )
        except Exception as exc:
            logger.warning("ArXiv search failed for %r: %s", query, exc)
            return []

        return [_to_candidate(paper) for paper in papers]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        # Through the shared resolver, which adds the PDF-OCR fallback: ar5iv
        # cannot render every paper, and a render failure used to cost the whole
        # body when the PDF was one request away.
        from peritus.sources.fulltext import FullTextHints, resolve_full_text

        resolved = await resolve_full_text(
            resolved_identifiers(candidate), FullTextHints.from_candidate(candidate)
        )
        full_text = resolved.text if resolved else ""

        abstract = candidate.metadata.get("summary") or candidate.snippet
        has_full = len(full_text) >= MIN_FULL_TEXT
        # Prepend title + abstract even to a full text, matching pubmed and
        # openalex. ar5iv renders the abstract inconsistently, and it is the
        # densest statement of the paper's claim — it belongs at the head of the
        # text, which is the part the validator preview always sees.
        text = (
            f"{candidate.title}\n\n{abstract}\n\n{full_text}"[:MAX_FULL_TEXT]
            if has_full
            else f"{candidate.title}\n\n{abstract}"
        )
        metadata = {k: v for k, v in candidate.metadata.items() if k != "summary"}
        metadata["full_text"] = has_full
        metadata.setdefault("abstract", abstract)
        metadata["full_text_method"] = (
            resolved.method if resolved is not None and has_full else "abstract"
        )
        return RawSource(
            source_type=SourceType.ARXIV,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata=metadata,
            identifiers=candidate.identifiers,
        )


def _to_candidate(paper) -> SourceCandidate:
    """One arXiv API result → a triage candidate carrying its identity.

    ``paper.doi`` is populated for preprints the authors later published
    elsewhere; capturing it is what lets the same work found through OpenAlex or
    through a DOI-only citation de-duplicate against this one.
    """
    arxiv_id = _extract_id(paper.entry_id)
    doi = getattr(paper, "doi", None)
    return SourceCandidate(
        source_type=SourceType.ARXIV,
        url=paper.entry_id,
        title=paper.title,
        author=", ".join(str(a) for a in paper.authors[:3]),
        snippet=paper.summary,
        metadata={
            "arxiv_id": arxiv_id,
            "doi": doi,
            "published": str(paper.published),
            "categories": paper.categories,
            "summary": paper.summary,
        },
        identifiers=Identifiers.build(arxiv_id=arxiv_id, doi=doi),
    )


def _extract_id(entry_id: str) -> str:
    """Extract bare ArXiv ID from a full URL like https://arxiv.org/abs/2001.01234v2."""
    match = re.search(r"abs/(.+?)(?:v\d+)?$", entry_id)
    return match.group(1) if match else entry_id.split("/")[-1]


def _ar5iv_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "figure", "cite"]):
        tag.decompose()
    article = soup.find("article") or soup.find("main") or soup.find("body")
    if not article:
        return ""
    return article.get_text(separator="\n", strip=True)


async def fetch_ar5iv(client: httpx.AsyncClient, arxiv_id: str) -> str:
    """Fetch the HTML full-text rendering of a paper from ar5iv."""
    try:
        resp = await client.get(f"{_AR5IV}{arxiv_id}", timeout=20)
        if resp.status_code != 200:
            return ""
        # Off the loop — a full paper rendering is large, and builds fetch these
        # in concurrent waves alongside a heartbeat that must keep its cadence.
        return await asyncio.to_thread(_ar5iv_to_text, resp.text)
    except Exception as exc:
        logger.debug("ar5iv fetch failed for %r: %s", arxiv_id, exc)
        return ""
