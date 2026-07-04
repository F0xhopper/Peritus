"""Project Gutenberg fetcher — Claude identifies canonical books first, then fetches via Gutendex.

search() identifies books and resolves them to Gutendex records (cheap metadata);
the multi-hundred-KB text download happens in fetch(), only for triage winners.
"""

import difflib
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_GUTENDEX = "https://gutendex.com/books/"
_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MAX_CHARS = 200_000

_START_RE = re.compile(
    r"\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)
_END_RE = re.compile(
    r"\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)

_BOOK_TOOL: dict[str, Any] = {
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
    async def search(self, query: str, max_results: int = 4) -> list[SourceCandidate]:
        identified = await _identify_books(query)
        if not identified:
            logger.info("No public-domain books identified for %r — skipping Gutenberg", query)
            return []

        candidates: list[SourceCandidate] = []
        seen_ids: set[int] = set()
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as client:
            for book_info in identified:
                if len(candidates) >= max_results:
                    break
                gutendex_query = book_info.get("search_query") or book_info["title"]
                results = await _search_gutendex(client, gutendex_query, 5)
                if not results and book_info.get("author"):
                    results = await _search_gutendex(client, book_info["author"], 5)

                # Gutendex search is loose (an author query matches any of their
                # books) — only accept records whose title matches the book
                # Claude actually asked for.
                match = next(
                    (
                        r for r in results
                        if r["id"] not in seen_ids
                        and _title_matches(book_info["title"], r.get("title", ""))
                    ),
                    None,
                )
                if match is None:
                    if results:
                        logger.info(
                            "Gutenberg: no candidate matched %r — skipping",
                            book_info["title"],
                        )
                    continue

                seen_ids.add(match["id"])
                author = (
                    ", ".join(a.get("name", "") for a in match.get("authors", []))
                    or book_info.get("author")
                    or None
                )
                candidates.append(SourceCandidate(
                    source_type=SourceType.GUTENBERG,
                    url=f"https://www.gutenberg.org/ebooks/{match['id']}",
                    title=match.get("title", book_info["title"]),
                    author=author,
                    snippet=(
                        f"{match.get('title', book_info['title'])} by {author or 'unknown'}. "
                        f"Subjects: {'; '.join(match.get('subjects', [])[:5])}"
                    ),
                    metadata={
                        "gutenberg_id": match["id"],
                        "formats": match.get("formats", {}),
                    },
                ))
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        async with httpx.AsyncClient(
            timeout=30, headers=_HEADERS, follow_redirects=True
        ) as client:
            try:
                text = await _download_text(client, candidate.metadata["formats"])
            except Exception as exc:
                logger.warning(
                    "Gutenberg download failed for book %s: %s",
                    candidate.metadata.get("gutenberg_id"), exc,
                )
                return None
        if len(text) < 500:
            return None
        logger.info("Gutenberg: fetched %r by %s", candidate.title, candidate.author)
        return RawSource(
            source_type=SourceType.GUTENBERG,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text[:_MAX_CHARS],
            metadata={"gutenberg_id": candidate.metadata["gutenberg_id"]},
        )


async def _identify_books(topic: str) -> list[dict]:
    """One Haiku call — returns a list of {title, author, search_query} dicts."""
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
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


async def _search_gutendex(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    try:
        resp = await client.get(
            _GUTENDEX, params={"search": query, "languages": "en"}
        )
        resp.raise_for_status()
        return resp.json().get("results", [])[:limit]
    except Exception as exc:
        logger.warning("Gutendex search failed for %r: %s", query, exc)
        return []


async def _download_text(client: httpx.AsyncClient, formats: dict) -> str:
    url = (
        formats.get("text/plain; charset=utf-8")
        or formats.get("text/plain")
        or formats.get("text/html; charset=utf-8")
        or formats.get("text/html")
    )
    if not url:
        raise ValueError("No plain text format available")

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


_TITLE_STOPWORDS = frozenset({"the", "a", "an", "of", "and", "or", "on", "in", "to"})


def _title_matches(wanted: str, candidate: str) -> bool:
    """Fuzzy title comparison — tolerant of subtitles and edition suffixes."""
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()

    w, c = _norm(wanted), _norm(candidate)
    if not w or not c:
        return False
    if w in c or c in w:
        return True
    w_tokens = set(w.split()) - _TITLE_STOPWORDS
    c_tokens = set(c.split())
    if w_tokens and len(w_tokens & c_tokens) / len(w_tokens) >= 0.6:
        return True
    return difflib.SequenceMatcher(None, w, c).ratio() >= 0.6


def _strip_gutenberg_boilerplate(text: str) -> str:
    start = _START_RE.search(text)
    if start:
        text = text[start.end():]
    end = _END_RE.search(text)
    if end:
        text = text[: end.start()]
    return text.strip()
