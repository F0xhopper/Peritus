import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Peritus/1.0)"}


class WebFetcher:
    async def fetch(self, topic: str, max_results: int = 4) -> list[RawSource]:
        urls = await _ddg_search(topic, max_results)
        sources = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
            for url in urls:
                try:
                    text, title = await _fetch_page(client, url)
                    if len(text) < 200:
                        continue
                    sources.append(RawSource(
                        source_type=SourceType.WEB,
                        url=url,
                        title=title,
                        author=None,
                        text=text,
                        metadata={},
                    ))
                except Exception as exc:
                    logger.warning("Web fetch failed for %r: %s", url, exc)
        return sources


async def _ddg_search(query: str, limit: int) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.post(_SEARCH_URL, data={"q": query})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            urls = []
            for a in soup.select("a.result__url"):
                href = a.get("href", "")
                if href.startswith("http") and "duckduckgo" not in href:
                    urls.append(href)
                    if len(urls) >= limit:
                        break
            return urls
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []


async def _fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    resp = await client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Prefer <article> or <main>, fall back to <body>
    container = soup.find("article") or soup.find("main") or soup.find("body")
    text = container.get_text(separator="\n", strip=True) if container else ""
    return text[:50_000], title
