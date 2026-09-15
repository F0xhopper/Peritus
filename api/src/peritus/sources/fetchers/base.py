"""The fetcher contract, and how a fetcher says *why* a search came back empty."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Protocol

from peritus.sources.domain import RawSource, SourceCandidate


class Fetcher(Protocol):
    """Two-phase source fetcher.

    search() is cheap — API metadata and a snippet, no full downloads — so the
    builder can over-search and let triage decide which candidates are worth
    the cost of fetch(). fetch() returns None when the content turns out to be
    unusable (too short, dead link, wrong format).
    """

    async def search(self, query: str, max_results: int = 5) -> list[SourceCandidate]: ...

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None: ...


# ── search outcomes ──────────────────────────────────────────────────────────
#
# Fetchers log and return ``[]`` on failure, by design: a channel failing must
# never fail a build. The cost was that "Gutendex timed out" and "there are no
# public-domain books on this topic" reached the build log as the same event —
# `gutenberg: 0` — on the Thomism build (job 53), where Gutenberg *is* the
# primary-text channel. So a fetcher that swallows a failure now also notes it,
# through a context variable the builder installs around each search. The
# fetcher's return type does not change, and a fetcher called outside a build
# notes into nothing.

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_TIMEOUT = "timeout"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# Failures worth retrying: the channel may well answer a second time.
TRANSIENT_STATUSES: frozenset[str] = frozenset({STATUS_TIMEOUT, STATUS_RATE_LIMITED})
# Outcomes that say something about the topic rather than about the channel.
HEALTHY_STATUSES: frozenset[str] = frozenset({STATUS_OK, STATUS_EMPTY, STATUS_SKIPPED})

# Worst first, for combining several queries' outcomes into one.
_SEVERITY = (STATUS_RATE_LIMITED, STATUS_TIMEOUT, STATUS_ERROR, STATUS_SKIPPED, STATUS_EMPTY, STATUS_OK)


@dataclass
class SearchNote:
    """Failures a fetcher noted during one search call."""

    failures: list[tuple[str, str]] = field(default_factory=list)


_current_note: ContextVar[SearchNote | None] = ContextVar("peritus_search_note", default=None)


def note_search_failure(status: str, error: str) -> None:
    """Record that this search lost results to a failure, not to the topic."""
    note = _current_note.get()
    if note is not None:
        note.failures.append((status, error[:300]))


def begin_search_note() -> tuple[SearchNote, object]:
    note = SearchNote()
    return note, _current_note.set(note)


def end_search_note(token) -> None:
    _current_note.reset(token)  # type: ignore[arg-type]


def worst_status(statuses: list[str]) -> str:
    """The most informative of several outcomes: a failure outranks an empty."""
    for status in _SEVERITY:
        if status in statuses:
            return status
    return STATUS_EMPTY


@dataclass
class SearchOutcome:
    candidates: list[SourceCandidate]
    status: str
    error: str = ""
    elapsed: float = 0.0

    @property
    def transient(self) -> bool:
        return self.status in TRANSIENT_STATUSES
