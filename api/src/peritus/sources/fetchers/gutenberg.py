"""Project Gutenberg fetcher — Claude identifies canonical books, the catalogue finds them.

search() identifies books (one Haiku call) and resolves each to an ebook id —
through Project Gutenberg's own catalogue, held locally (see
infrastructure/gutenberg_catalogue.py), and only for a title the catalogue does
not match, through Gutendex. The multi-hundred-KB text download happens in
fetch(), only for triage winners, from the URL Gutenberg serves every text at.

Gutendex is one small volunteer-run service. It used to be the only route, under
a single 45 s budget that returned nothing on timeout — which is how the Thomism
build (job 53) got zero Gutenberg candidates. It is now a fallback, each call
has its own short timeout, and a timeout keeps the books already resolved.
"""

import asyncio
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.infrastructure.gutenberg_catalogue import load_catalogue, title_matches
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.base import (
    STATUS_ERROR,
    STATUS_TIMEOUT,
    note_search_failure,
)
from peritus.sources.sections import apply_sections

logger = get_logger(__name__)

_GUTENDEX = "https://gutendex.com/books/"
_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MAX_CHARS = 200_000
# Per Gutendex call. Discovery waits on every fetcher, so this bounds how long a
# fallback lookup may delay the build; a slow call costs that one book.
_GUTENDEX_TIMEOUT = 10.0

_START_RE = re.compile(
    r"\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE
)
_END_RE = re.compile(r"\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.+?\*{3}", re.IGNORECASE)

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

        catalogue = await load_catalogue()
        candidates: list[SourceCandidate] = []
        seen_ids: set[int] = set()
        unresolved: list[dict] = []

        for book_info in identified:
            if len(candidates) >= max_results:
                break
            books = (
                catalogue.resolve(book_info["title"], book_info.get("author"), 3)
                if catalogue is not None
                else []
            )
            book = next((b for b in books if b.id not in seen_ids), None)
            if book is None:
                unresolved.append(book_info)
                continue
            seen_ids.add(book.id)
            candidates.append(
                _candidate(
                    book.id,
                    book.display_title,
                    book.authors or book_info.get("author") or None,
                    book.subjects.split("; ")[:5],
                    formats={},
                )
            )

        if unresolved and len(candidates) < max_results:
            candidates += await self._resolve_through_gutendex(
                unresolved, seen_ids, max_results - len(candidates), query
            )
        return candidates

    async def _resolve_through_gutendex(
        self,
        identified: list[dict],
        seen_ids: set[int],
        limit: int,
        query: str,
    ) -> list[SourceCandidate]:
        """The fallback. Concurrent, each call on its own short timeout.

        One slow lookup costs its own book and nothing else: a timeout used to
        discard every book already resolved alongside it.
        """
        candidates: list[SourceCandidate] = []
        async with httpx.AsyncClient(
            timeout=_GUTENDEX_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            per_book = await asyncio.gather(*[_lookup_book(client, b) for b in identified])

        timeouts = 0
        for book_info, (results, timed_out) in zip(identified, per_book, strict=True):
            timeouts += timed_out
            if len(candidates) >= limit:
                break
            match = next(
                (
                    r
                    for r in results
                    if r["id"] not in seen_ids
                    and title_matches(book_info["title"], r.get("title", ""))
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
            candidates.append(
                _candidate(
                    match["id"],
                    match.get("title", book_info["title"]),
                    author,
                    match.get("subjects", [])[:5],
                    formats=match.get("formats", {}),
                )
            )

        if timeouts:
            logger.warning(
                "Gutenberg: %d of %d Gutendex lookup(s) timed out after %.0fs for %r",
                timeouts,
                len(identified),
                _GUTENDEX_TIMEOUT,
                query,
            )
            if not candidates:
                note_search_failure(
                    STATUS_TIMEOUT,
                    f"Gutendex timed out after {_GUTENDEX_TIMEOUT:.0f}s "
                    f"({timeouts} of {len(identified)} lookups)",
                )
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        book_id = candidate.metadata.get("gutenberg_id")
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            try:
                text = await _download_book(
                    client, book_id, candidate.metadata.get("formats") or {}
                )
            except Exception as exc:
                logger.warning("Gutenberg download failed for book %s: %s", book_id, exc)
                return None
        if len(text) < 500:
            return None
        # The plan's sections, when it named some, rather than the book's opening.
        text, selected = apply_sections(text, candidate.metadata, _MAX_CHARS)
        logger.info(
            "Gutenberg: fetched %r by %s (%d chars%s)",
            candidate.title,
            candidate.author,
            len(text),
            ", named sections" if selected.get("sections_matched") else "",
        )
        return RawSource(
            source_type=SourceType.GUTENBERG,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text,
            metadata={
                **{k: v for k, v in candidate.metadata.items() if k != "formats"},
                **selected,
                "gutenberg_id": book_id,
            },
        )


def _candidate(
    book_id: int,
    title: str,
    author: str | None,
    subjects: list[str],
    formats: dict,
) -> SourceCandidate:
    return SourceCandidate(
        source_type=SourceType.GUTENBERG,
        url=f"https://www.gutenberg.org/ebooks/{book_id}",
        title=title,
        author=author,
        snippet=f"{title} by {author or 'unknown'}. Subjects: {'; '.join(subjects)}",
        metadata={"gutenberg_id": book_id, "formats": formats},
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


async def _lookup_book(client: httpx.AsyncClient, book_info: dict) -> tuple[list[dict], bool]:
    """Gutendex records for one identified book: the title query, then the author.

    Gutendex search is loose — an author query matches every book they wrote —
    so the caller still has to title-match what comes back. Returns the records
    and whether a call timed out.
    """
    gutendex_query = book_info.get("search_query") or book_info["title"]
    results, timed_out = await _search_gutendex(client, gutendex_query, 5)
    if not results and not timed_out and book_info.get("author"):
        results, timed_out = await _search_gutendex(client, book_info["author"], 5)
    return results, timed_out


async def _search_gutendex(
    client: httpx.AsyncClient, query: str, limit: int
) -> tuple[list[dict], bool]:
    try:
        resp = await asyncio.wait_for(
            client.get(_GUTENDEX, params={"search": query, "languages": "en"}),
            timeout=_GUTENDEX_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])[:limit], False
    except (TimeoutError, httpx.TimeoutException):
        return [], True
    except Exception as exc:
        logger.warning("Gutendex search failed for %r: %s", query, exc)
        note_search_failure(STATUS_ERROR, f"Gutendex: {type(exc).__name__}: {exc}")
        return [], False


async def _download_book(client: httpx.AsyncClient, book_id: int | None, formats: dict) -> str:
    """The book's text: Gutenberg's predictable plain-text URL, then Gutendex's map."""
    if book_id is not None:
        try:
            resp = await client.get(
                f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt", timeout=60
            )
            if resp.status_code == 200 and resp.text.strip():
                return _strip_gutenberg_boilerplate(resp.text)
            logger.info(
                "Gutenberg: plain text for %s returned %d — trying its format map",
                book_id,
                resp.status_code,
            )
        except httpx.HTTPError as exc:
            logger.info("Gutenberg: plain text for %s failed (%s)", book_id, exc)
        if not formats:
            resp = await client.get(f"{_GUTENDEX}{book_id}", timeout=_GUTENDEX_TIMEOUT)
            resp.raise_for_status()
            formats = resp.json().get("formats", {}) or {}
    return await _download_text(client, formats)


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
        # Off the loop: this is a whole book, routinely multi-megabyte, and
        # parsing one inline blocks every other coroutine in the process —
        # including the build worker's heartbeat.
        text = await asyncio.to_thread(_html_to_text, resp.text)
    else:
        text = resp.text

    return _strip_gutenberg_boilerplate(text)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# Kept under its old name for the callers and tests that import it from here.
_title_matches = title_matches


def _strip_gutenberg_boilerplate(text: str) -> str:
    start = _START_RE.search(text)
    if start:
        text = text[start.end() :]
    end = _END_RE.search(text)
    if end:
        text = text[: end.start()]
    return text.strip()
