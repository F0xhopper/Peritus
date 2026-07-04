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
