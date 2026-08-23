import asyncio

import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Peritus/1.0)"}


class WebFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        hits = await _ddg_search(query, max_results)
        return [
            SourceCandidate(
                source_type=SourceType.WEB,
                url=hit["url"],
                title=hit["title"] or hit["url"],
                author=None,
                snippet=hit["snippet"],
                metadata={},
            )
            for hit in hits
        ]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers=_HEADERS
        ) as client:
            try:
                text, title = await _fetch_page(client, candidate.url)
            except Exception as exc:
                logger.warning("Web fetch failed for %r: %s", candidate.url, exc)
                return None
        if len(text) < 500:
            return None
        return RawSource(
            source_type=SourceType.WEB,
            url=candidate.url,
            title=title or candidate.title,
            author=None,
            text=text,
            metadata=candidate.metadata,
        )


# Parsing runs off the event loop.
#
# lxml + BeautifulSoup on an arbitrary web page is CPU-bound and unbounded — a
# bloated page is hundreds of milliseconds, and a build fetches dozens of them
# in concurrent waves. Left on the loop that starves everything sharing it,
# including the build worker's heartbeat, whose silence gets a perfectly healthy
# job reaped and retried (see BuildWorker._beat). httpx already yields; the parse
# has to be made to.


def _parse_ddg(html: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    hits: list[dict] = []
    for result in soup.select("div.result"):
        url_a = result.select_one("a.result__url")
        if url_a is None:
            continue
        href = url_a.get("href", "")
        if not isinstance(href, str) or not href.startswith("http") or "duckduckgo" in href:
            continue
        title_a = result.select_one("a.result__a")
        snippet_el = result.select_one(".result__snippet")
        hits.append({
            "url": href,
            "title": title_a.get_text(strip=True) if title_a else "",
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
        if len(hits) >= limit:
            break
    return hits


async def _ddg_search(query: str, limit: int) -> list[dict]:
    """DuckDuckGo HTML search. Returns [{url, title, snippet}] — snippets make
    candidates triageable without fetching the page."""
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.post(_SEARCH_URL, data={"q": query})
            resp.raise_for_status()
            return await asyncio.to_thread(_parse_ddg, resp.text, limit)
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []


def _parse_page(html: str, url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Prefer <article> or <main>, fall back to <body>
    container = soup.find("article") or soup.find("main") or soup.find("body")
    text = container.get_text(separator="\n", strip=True) if container else ""
    return text[:50_000], title


async def _fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    resp = await client.get(url)
    resp.raise_for_status()
    return await asyncio.to_thread(_parse_page, resp.text, url)
