import asyncio

import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.infrastructure.http import BROWSER_UA, shared_client
from peritus.sources.domain import Identifiers, RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.base import note_search_failure
from peritus.sources.fetchers.exa import classify_search_error
from peritus.sources.identifiers import identifiers_from_url

logger = get_logger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {"User-Agent": BROWSER_UA}


class WebFetcher:
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        hits = await _ddg_search(query, max_results)
        return [_to_candidate(hit) for hit in hits]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        client = shared_client(timeout=20, headers=_HEADERS, guarded=True)
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
            identifiers=candidate.identifiers,
        )


def _to_candidate(hit: dict) -> SourceCandidate:
    # A general web search reaches doi.org and arxiv.org routinely; reading the
    # identity out of the URL is free and is the only identity these hits have.
    doi, arxiv_id = identifiers_from_url(hit["url"])
    return SourceCandidate(
        source_type=SourceType.WEB,
        url=hit["url"],
        title=hit["title"] or hit["url"],
        author=None,
        snippet=hit["snippet"],
        metadata={},
        identifiers=Identifiers.build(doi=doi, arxiv_id=arxiv_id),
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
        hits.append(
            {
                "url": href,
                "title": title_a.get_text(strip=True) if title_a else "",
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
        if len(hits) >= limit:
            break
    return hits


async def _ddg_search(query: str, limit: int) -> list[dict]:
    """DuckDuckGo HTML search. Returns [{url, title, snippet}] — snippets make
    candidates triageable without fetching the page."""
    try:
        client = shared_client(timeout=15, headers=_HEADERS, follow_redirects=False)
        resp = await client.post(_SEARCH_URL, data={"q": query})
        resp.raise_for_status()
        return await asyncio.to_thread(_parse_ddg, resp.text, limit)
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        note_search_failure(*classify_search_error(exc, "DuckDuckGo"))
        return []


# A plain web page's default ceiling. The full-text resolver raises it for an
# open-access landing page, which is a whole paper rather than an article and is
# read on the same terms as one fetched from a publisher's PDF.
DEFAULT_MAX_CHARS = 50_000


def _parse_page(html: str, url: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Prefer <article> or <main>, fall back to <body>
    container = soup.find("article") or soup.find("main") or soup.find("body")
    text = container.get_text(separator="\n", strip=True) if container else ""
    return text[:max_chars], title


async def _fetch_page(
    client: httpx.AsyncClient, url: str, max_chars: int = DEFAULT_MAX_CHARS
) -> tuple[str, str]:
    resp = await client.get(url)
    resp.raise_for_status()
    return await asyncio.to_thread(_parse_page, resp.text, url, max_chars)


async def fetch_page_text(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Page text for a URL, with its own client. Raises on transport failure."""
    client = shared_client(timeout=20, headers=_HEADERS, guarded=True)
    text, _title = await _fetch_page(client, url, max_chars)
    return text
