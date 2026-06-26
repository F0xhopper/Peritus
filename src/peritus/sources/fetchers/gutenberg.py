"""Project Gutenberg fetcher — Claude identifies canonical books first, then fetches via Gutendex."""

import re

import httpx
from bs4 import BeautifulSoup

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_GUTENDEX = "https://gutendex.com/books/"
_HEADERS = {"User-Agent": "Peritus/2.0 (educational tool; foxhopper16@gmail.com)"}
_MAX_CHARS = 200_000

_START_RE = re.compile(
    r"\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)
_END_RE = re.compile(
    r"\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)

_BOOK_TOOL = {
    "name": "identify_canonical_books",
    "description": (
        "Identify canonical books and primary texts for a topic that are available in "
        "Project Gutenberg (public domain, published before 1927)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "books": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Exact book title."},
                        "author": {"type": "string", "description": "Author's full name."},
                        "search_query": {
                            "type": "string",
                            "description": (
                                "Best Gutenberg search string — use the author's last name "
                                "or the most distinctive words of the title."
                            ),
                        },
                    },
                    "required": ["title", "author", "search_query"],
                },
                "maxItems": 6,
            }
        },
        "required": ["books"],
    },
}


class GutenbergFetcher:
    async def fetch(self, topic: str, max_results: int = 4) -> list[RawSource]:
        identified = await _identify_books(topic)
        if not identified:
            logger.info("No public-domain books identified for %r — skipping Gutenberg", topic)
            return []

        sources: list[RawSource] = []
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as client:
            for book_info in identified:
                if len(sources) >= max_results:
                    break
                query = book_info.get("search_query") or book_info["title"]
                candidates = await _search(client, query, 3)
                if not candidates and book_info.get("author"):
                    candidates = await _search(client, book_info["author"], 3)

                for candidate in candidates[:2]:
                    try:
                        text = await _download_text(client, candidate)
                        if len(text) < 500:
                            continue
                        author = (
                            ", ".join(a.get("name", "") for a in candidate.get("authors", []))
                            or book_info.get("author")
                            or None
                        )
                        sources.append(RawSource(
                            source_type=SourceType.GUTENBERG,
                            url=f"https://www.gutenberg.org/ebooks/{candidate['id']}",
                            title=candidate.get("title", book_info["title"]),
                            author=author,
                            text=text[:_MAX_CHARS],
                            metadata={"gutenberg_id": candidate["id"]},
                        ))
                        logger.info(
                            "Gutenberg: fetched %r by %s",
                            candidate.get("title"), author,
                        )
                        break
                    except Exception as exc:
                        logger.warning(
                            "Gutenberg download failed for book %s: %s",
                            candidate.get("id"), exc,
                        )

        return sources[:max_results]


async def _identify_books(topic: str) -> list[dict]:
    """One Haiku call — returns a list of {title, author, search_query} dicts."""
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=400,
            system=(
                "Identify the most important canonical books and primary texts for the given "
                "topic that are available as public domain works (pre-1927). Focus on foundational "
                "primary sources: original treatises, classic philosophical texts, seminal works. "
                "If there are no relevant public-domain books for this topic, return an empty list."
            ),
            tools=[_BOOK_TOOL],
            tool_choice={"type": "tool", "name": "identify_canonical_books"},
            messages=[{"role": "user", "content": f"Topic: {topic}"}],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        books = block.input.get("books", [])
        if books:
            logger.info(
                "Gutenberg book identification for %r: %s",
                topic,
                "; ".join(f"{b['title']} ({b['author']})" for b in books),
            )
        return books
    except Exception as exc:
        logger.warning("Gutenberg book identification failed for %r: %s", topic, exc)
        return []


async def _search(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    try:
        resp = await client.get(
            _GUTENDEX, params={"search": query, "languages": "en"}
        )
        resp.raise_for_status()
        return resp.json().get("results", [])[:limit]
    except Exception as exc:
        logger.warning("Gutendex search failed for %r: %s", query, exc)
        return []


async def _download_text(client: httpx.AsyncClient, book: dict) -> str:
    formats = book.get("formats", {})
    url = (
        formats.get("text/plain; charset=utf-8")
        or formats.get("text/plain")
        or formats.get("text/html; charset=utf-8")
        or formats.get("text/html")
    )
    if not url:
        raise ValueError(f"No plain text format for book {book.get('id')}")

    resp = await client.get(url, timeout=60)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type or url.endswith((".htm", ".html")):
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
        match = _END_RE.search(text)
        if match:
            text = text[: match.start()]
    return text.strip()
