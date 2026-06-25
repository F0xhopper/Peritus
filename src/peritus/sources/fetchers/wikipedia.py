import httpx

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_CONTENT_URL = "https://en.wikipedia.org/w/api.php"


_HEADERS = {
    "User-Agent": "Peritus/2.0 (https://github.com/F0xhopper/cognita-mcp; foxhopper16@gmail.com)"
}


class WikipediaFetcher:
    async def fetch(self, topic: str, max_results: int = 4) -> list[RawSource]:
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            titles = await _search(client, topic, max_results)
            sources = []
            for title in titles:
                try:
                    text = await _fetch_article(client, title)
                    if len(text) < 200:
                        continue
                    sources.append(RawSource(
                        source_type=SourceType.WIKIPEDIA,
                        url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        title=title,
                        author=None,
                        text=text,
                        metadata={"wiki_title": title},
                    ))
                except Exception as exc:
                    logger.warning("Wikipedia fetch failed for %r: %s", title, exc)
            return sources


async def _search(client: httpx.AsyncClient, topic: str, limit: int) -> list[str]:
    resp = await client.get(_SEARCH_URL, params={
        "action": "query",
        "list": "search",
        "srsearch": topic,
        "srlimit": limit,
        "format": "json",
    })
    resp.raise_for_status()
    data = resp.json()
    return [item["title"] for item in data.get("query", {}).get("search", [])]


async def _fetch_article(client: httpx.AsyncClient, title: str) -> str:
    resp = await client.get(_CONTENT_URL, params={
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
    return page.get("extract", "")
