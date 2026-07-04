import re

import httpx

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_API_URL = "https://en.wikipedia.org/w/api.php"
_MAX_CHARS = 80_000

_HEADERS = {
    "User-Agent": "Peritus/2.0 (research corpus builder)"
}

_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(_API_URL, params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "srprop": "snippet",
                "format": "json",
            })
            resp.raise_for_status()
            data = resp.json()
        candidates = []
        for item in data.get("query", {}).get("search", []):
            title = item["title"]
            candidates.append(SourceCandidate(
                source_type=SourceType.WIKIPEDIA,
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                title=title,
                author=None,
                snippet=_TAG_RE.sub("", item.get("snippet", "")),
                metadata={"wiki_title": title},
            ))
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        title = candidate.metadata["wiki_title"]
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(_API_URL, params={
                "action": "query",
                "titles": title,
                "prop": "extracts",
                "explaintext": True,
                "exsectionformat": "plain",
                "format": "json",
            })
            resp.raise_for_status()
            data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        text = page.get("extract", "")
        if len(text) < 500:
            return None
        return RawSource(
            source_type=SourceType.WIKIPEDIA,
            url=candidate.url,
            title=title,
            author=None,
            text=text[:_MAX_CHARS],
            metadata=candidate.metadata,
        )
