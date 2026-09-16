"""Project Gutenberg's own catalogue, held locally, so identifying a book is not a
network call to a volunteer-run search service.

Gutenberg discovery used to resolve every identified title through Gutendex
under one 45-second budget and return an empty list on timeout. Gutendex timed
out for the Thomism build (job 53) and for a probe the same day, and the build
reported it as ``gutenberg: 0`` — indistinguishable from "there are no
public-domain books on this topic", on the kind of topic Gutenberg exists for.

Project Gutenberg publishes the whole catalogue as one CSV (about 75,000
English texts, ~21 MB) and serves plain text at a predictable URL. So the CSV is
downloaded once a week per worker, loaded into memory as a token index, and a
``(title, author)`` pair resolves to ebook ids locally. Gutendex stays as the
fallback for a title the catalogue does not match.

Nothing here raises to a caller: an unavailable catalogue is ``None``, and the
fetcher falls back to what it did before.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import io
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.http import RESEARCH_UA

logger = get_logger(__name__)

CATALOGUE_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
_FILE_NAME = "pg_catalog.csv"
_MAX_AGE_SECONDS = 7 * 24 * 3600
_DOWNLOAD_TIMEOUT = 90.0
# After a failed download, don't try again for this long: a build must not pay
# a 90-second timeout per fetcher call while gutenberg.org is down.
_RETRY_AFTER_FAILURE_SECONDS = 600.0
_HEADERS = {"User-Agent": RESEARCH_UA}

_TITLE_STOPWORDS = frozenset({"the", "a", "an", "of", "and", "or", "on", "in", "to"})
_NORM_RE = re.compile(r"[^a-z0-9 ]")


def _norm(text: str) -> str:
    return " ".join(_NORM_RE.sub(" ", text.lower()).split())


def title_matches(wanted: str, candidate: str) -> bool:
    """Fuzzy title comparison — tolerant of subtitles and edition suffixes."""
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


@dataclass(frozen=True)
class CatalogueBook:
    id: int
    title: str
    authors: str
    subjects: str = ""

    @property
    def text_url(self) -> str:
        """Plain text, at the URL Gutenberg serves every ebook's text from."""
        return f"https://www.gutenberg.org/cache/epub/{self.id}/pg{self.id}.txt"

    @property
    def url(self) -> str:
        return f"https://www.gutenberg.org/ebooks/{self.id}"

    @property
    def display_title(self) -> str:
        # Catalogue titles put the subtitle on a second line.
        return " — ".join(part.strip() for part in self.title.splitlines() if part.strip())


class GutenbergCatalogue:
    """English texts, indexed by normalised title token."""

    def __init__(self, books: list[CatalogueBook]) -> None:
        self._books = books
        self._index: dict[str, list[int]] = defaultdict(list)
        for position, book in enumerate(books):
            for token in set(_norm(book.title).split()) - _TITLE_STOPWORDS:
                self._index[token].append(position)
        self._vocabulary = list(self._index)

    def __len__(self) -> int:
        return len(self._books)

    @classmethod
    def from_csv_text(cls, text: str) -> GutenbergCatalogue:
        books: list[CatalogueBook] = []
        for row in csv.DictReader(io.StringIO(text)):
            if (row.get("Type") or "").strip() != "Text":
                continue
            languages = {lang.strip() for lang in (row.get("Language") or "").split(";")}
            if "en" not in languages:
                continue
            try:
                book_id = int(row.get("Text#") or "")
            except ValueError:
                continue
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            books.append(
                CatalogueBook(
                    id=book_id,
                    title=title,
                    authors=(row.get("Authors") or "").strip(),
                    subjects=(row.get("Subjects") or "").strip(),
                )
            )
        return cls(books)

    def resolve(self, title: str, author: str | None = None, limit: int = 3) -> list[CatalogueBook]:
        """Books whose title matches ``title``, best first.

        A token of the wanted title that the catalogue has never seen is widened
        to its closest spellings ("Theologiae" finds "Theologica"), because the
        planner writes titles the way scholarship spells them and Gutenberg
        catalogues the edition it holds.

        When an author is given and any match carries that author's surname,
        matches without it are discarded — an author query in the catalogue
        otherwise matches every commentary with the work's name in its title.
        """
        wanted_tokens = set(_norm(title).split()) - _TITLE_STOPWORDS
        if not wanted_tokens:
            return []

        hits: dict[int, int] = defaultdict(int)
        for token in wanted_tokens:
            spellings = (
                [token]
                if token in self._index
                else difflib.get_close_matches(token, self._vocabulary, n=3, cutoff=0.8)
            )
            positions: set[int] = set()
            for spelling in spellings:
                positions.update(self._index.get(spelling, ()))
            for position in positions:
                hits[position] += 1

        needed = max(1, round(len(wanted_tokens) * 0.6))
        matches = [self._books[position] for position, count in hits.items() if count >= needed]
        matches = [
            book
            for book in matches
            if title_matches(title, book.title.splitlines()[0])
            or hits_fraction(wanted_tokens, book.title) >= 0.6
        ]

        surname = _surname(author)
        if surname:
            by_author = [b for b in matches if surname in _norm(b.authors).split()]
            if by_author:
                matches = by_author

        wanted_norm = _norm(title)
        matches.sort(
            key=lambda b: (
                -difflib.SequenceMatcher(None, wanted_norm, _norm(b.title.splitlines()[0])).ratio(),
                b.id,
            )
        )
        return matches[:limit]


def hits_fraction(wanted_tokens: set[str], title: str) -> float:
    """Share of the wanted tokens present in a title, allowing close spellings."""
    title_tokens = set(_norm(title).split())
    found = 0
    for token in wanted_tokens:
        if token in title_tokens or difflib.get_close_matches(token, title_tokens, n=1, cutoff=0.8):
            found += 1
    return found / len(wanted_tokens) if wanted_tokens else 0.0


def _surname(author: str | None) -> str | None:
    """The token of an author name most likely to appear in a catalogue entry.

    Catalogue authors are "Aquinas, Thomas, Saint, 1225?-1274", so for "Thomas
    Aquinas" the useful token is the last one; for "Aquinas" it is the only one.
    """
    tokens = [t for t in _norm(author or "").split() if len(t) > 2 and t not in {"saint", "st"}]
    return tokens[-1] if tokens else None


# ── the process-wide copy ────────────────────────────────────────────────────

_catalogue: GutenbergCatalogue | None = None
_loaded_at: float = 0.0
_failed_at: float = 0.0
_lock = asyncio.Lock()


def catalogue_dir() -> Path:
    configured = settings.GUTENBERG_CATALOGUE_DIR
    if configured:
        return Path(configured)
    return Path(os.path.expanduser("~")) / ".cache" / "peritus"


async def load_catalogue() -> GutenbergCatalogue | None:
    """The catalogue, downloading it when absent or older than a week.

    ``None`` when it cannot be had — no network, a failed download within the
    last ten minutes, an unreadable file. Callers fall back to Gutendex.
    """
    global _catalogue, _loaded_at, _failed_at

    if not settings.GUTENBERG_CATALOGUE_ENABLED:
        return None
    now = time.monotonic()
    if _catalogue is not None and now - _loaded_at < _MAX_AGE_SECONDS:
        return _catalogue
    if _failed_at and now - _failed_at < _RETRY_AFTER_FAILURE_SECONDS:
        return _catalogue

    async with _lock:
        now = time.monotonic()
        if _catalogue is not None and now - _loaded_at < _MAX_AGE_SECONDS:
            return _catalogue
        try:
            path = catalogue_dir() / _FILE_NAME
            if not _is_fresh(path):
                await _download(path)
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            loaded = await asyncio.to_thread(GutenbergCatalogue.from_csv_text, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _failed_at = time.monotonic()
            logger.warning(
                "Gutenberg catalogue unavailable (%s: %s) — falling back to Gutendex",
                type(exc).__name__,
                exc,
            )
            return _catalogue
        if not len(loaded):
            _failed_at = time.monotonic()
            logger.warning("Gutenberg catalogue parsed to zero English texts — ignoring it")
            return _catalogue
        _catalogue, _loaded_at, _failed_at = loaded, time.monotonic(), 0.0
        logger.info("Gutenberg catalogue loaded: %d English texts", len(loaded))
        return _catalogue


def _is_fresh(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime < _MAX_AGE_SECONDS
    except OSError:
        return False


async def _download(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".csv.part")
    async with (
        httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client,
        client.stream("GET", CATALOGUE_URL) as resp,
    ):
        resp.raise_for_status()
        with partial.open("wb") as handle:
            async for chunk in resp.aiter_bytes():
                handle.write(chunk)
    partial.replace(path)
