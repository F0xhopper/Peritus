from typing import Protocol

from peritus.sources.domain import RawSource


class Fetcher(Protocol):
    async def fetch(self, topic: str, max_results: int = 5) -> list[RawSource]: ...
