"""ArXiv fetcher — searches papers and fetches full HTML text via ar5iv."""

import re

import arxiv  # type: ignore
import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_AR5IV = "https://ar5iv.labs.arxiv.org/html/"
_HEADERS = {"User-Agent": "Peritus/2.0 (educational tool; foxhopper16@gmail.com)"}
_MIN_FULL_TEXT = 3_000
_MAX_FULL_TEXT = 120_000


class ArxivFetcher:
    async def fetch(self, topic: str, max_results: int = 3) -> list[RawSource]:
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=topic,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            papers = list(client.results(search))
        except Exception as exc:
            logger.warning("ArXiv search failed for %r: %s", topic, exc)
            return []

        sources: list[RawSource] = []
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as http:
            for paper in papers:
                try:
                    arxiv_id = _extract_id(paper.entry_id)
                    full_text = await _fetch_ar5iv(http, arxiv_id)
                    if len(full_text) >= _MIN_FULL_TEXT:
                        text = full_text[:_MAX_FULL_TEXT]
                        has_full = True
                    else:
                        text = f"{paper.title}\n\n{paper.summary}"
                        has_full = False

                    sources.append(RawSource(
                        source_type=SourceType.ARXIV,
                        url=paper.entry_id,
                        title=paper.title,
                        author=", ".join(str(a) for a in paper.authors[:3]),
                        text=text,
                        metadata={
                            "arxiv_id": arxiv_id,
                            "published": str(paper.published),
                            "categories": paper.categories,
                            "full_text": has_full,
                        },
                    ))
                except Exception as exc:
                    logger.warning(
                        "ArXiv paper processing failed for %r: %s", paper.entry_id, exc
                    )
        return sources


def _extract_id(entry_id: str) -> str:
    """Extract bare ArXiv ID from a full URL like https://arxiv.org/abs/2001.01234v2."""
    match = re.search(r"abs/(.+?)(?:v\d+)?$", entry_id)
    return match.group(1) if match else entry_id.split("/")[-1]


async def _fetch_ar5iv(client: httpx.AsyncClient, arxiv_id: str) -> str:
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
