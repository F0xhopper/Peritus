"""Project Gutenberg fetcher — public domain books via the Gutendex JSON API."""

import re

import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_GUTENDEX = "https://gutendex.com/books/"
_HEADERS = {"User-Agent": "Peritus/2.0 (educational tool; foxhopper16@gmail.com)"}
_MAX_CHARS = 200_000

# Gutenberg texts have a standard boilerplate header/footer — strip them.
_START_RE = re.compile(
    r"\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)
_END_RE = re.compile(
    r"\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)


class GutenbergFetcher:
    async def fetch(self, topic: str, max_results: int = 3) -> list[RawSource]:
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as client:
            books = await _search(client, topic, max_results)
            sources: list[RawSource] = []
            for book in books:
                try:
                    text = await _download_text(client, book)
                    if len(text) < 500:
                        continue
                    author = (
                        ", ".join(a.get("name", "") for a in book.get("authors", []))
                        or None
                    )
                    sources.append(RawSource(
                        source_type=SourceType.GUTENBERG,
                        url=f"https://www.gutenberg.org/ebooks/{book['id']}",
                        title=book.get("title", "Unknown"),
                        author=author,
                        text=text[:_MAX_CHARS],
                        metadata={"gutenberg_id": book["id"]},
                    ))
                except Exception as exc:
                    logger.warning(
                        "Gutenberg fetch failed for book %s: %s", book.get("id"), exc
                    )
            return sources


async def _search(client: httpx.AsyncClient, topic: str, limit: int) -> list[dict]:
    resp = await client.get(_GUTENDEX, params={"search": topic, "languages": "en"})
    resp.raise_for_status()
    return resp.json().get("results", [])[:limit]


async def _download_text(client: httpx.AsyncClient, book: dict) -> str:
    formats = book.get("formats", {})
    url = (
        formats.get("text/plain; charset=utf-8")
        or formats.get("text/plain")
        or formats.get("text/html; charset=utf-8")
        or formats.get("text/html")
    )
    if not url:
        raise ValueError(f"No plain text format available for book {book.get('id')}")

    resp = await client.get(url, timeout=60)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type or url.endswith(".htm") or url.endswith(".html"):
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    else:
        text = resp.text

    return _strip_gutenberg_boilerplate(text)


def _strip_gutenberg_boilerplate(text: str) -> str:
    start = _START_RE.search(text)
    end = _END_RE.search(text)
    if start:
        text = text[start.end():]
    if end:
        text = text[: _END_RE.search(text).start()] if _END_RE.search(text) else text
    return text.strip()
