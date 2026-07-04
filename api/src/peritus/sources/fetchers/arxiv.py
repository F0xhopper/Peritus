"""ArXiv fetcher — searches papers (title + abstract), fetches full HTML text via ar5iv."""

import asyncio
import re

import arxiv  # type: ignore
import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

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

        return [
            SourceCandidate(
                source_type=SourceType.ARXIV,
                url=paper.entry_id,
                title=paper.title,
                author=", ".join(str(a) for a in paper.authors[:3]),
                snippet=paper.summary,
                metadata={
                    "arxiv_id": _extract_id(paper.entry_id),
                    "published": str(paper.published),
                    "categories": paper.categories,
                    "summary": paper.summary,
                },
            )
            for paper in papers
        ]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        arxiv_id = candidate.metadata["arxiv_id"]
        try:
            async with httpx.AsyncClient(
                timeout=30, headers=HEADERS, follow_redirects=True
            ) as http:
                full_text = await fetch_ar5iv(http, arxiv_id)
        except Exception as exc:
            logger.warning("ar5iv fetch failed for %r: %s", arxiv_id, exc)
            full_text = ""

        has_full = len(full_text) >= MIN_FULL_TEXT
        text = full_text[:MAX_FULL_TEXT] if has_full \
            else f"{candidate.title}\n\n{candidate.metadata.get('summary', candidate.snippet)}"
        metadata = {k: v for k, v in candidate.metadata.items() if k != "summary"}
        metadata["full_text"] = has_full
        return RawSource(
            source_type=SourceType.ARXIV,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata=metadata,
        )


def _extract_id(entry_id: str) -> str:
    """Extract bare ArXiv ID from a full URL like https://arxiv.org/abs/2001.01234v2."""
    match = re.search(r"abs/(.+?)(?:v\d+)?$", entry_id)
    return match.group(1) if match else entry_id.split("/")[-1]


async def fetch_ar5iv(client: httpx.AsyncClient, arxiv_id: str) -> str:
    """Fetch the HTML full-text rendering of a paper from ar5iv."""
    try:
        resp = await client.get(f"{_AR5IV}{arxiv_id}", timeout=20)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "figure", "cite"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if not article:
            return ""
        return article.get_text(separator="\n", strip=True)
    except Exception as exc:
        logger.debug("ar5iv fetch failed for %r: %s", arxiv_id, exc)
        return ""
