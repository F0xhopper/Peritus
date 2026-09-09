import asyncio

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import Identifiers, RawSource, SourceCandidate, SourceType
from peritus.sources.identifiers import identifiers_from_url

logger = get_logger(__name__)

_MAX_CHARS = 80_000
_SNIPPET_CHARS = 600


class ExaFetcher:
    async def search(self, query: str, max_results: int = 8) -> list[SourceCandidate]:
        if not settings.EXA_API_KEY:
            logger.warning("EXA_API_KEY not set — skipping Exa fetcher")
            return []

        try:
            from exa_py import Exa  # type: ignore
            client = Exa(api_key=settings.EXA_API_KEY)
            # exa_py is a sync client — keep it off the event loop.
            results = await asyncio.to_thread(
                client.search_and_contents,
                query,
                num_results=max_results,
                type="neural",
                text={"max_characters": _SNIPPET_CHARS},
            )
            candidates = []
            for r in results.results:
                snippet = getattr(r, "text", None) or ""
                if not r.url:
                    continue
                # Exa lands on doi.org and arxiv.org constantly. Without this
                # the same paper found by exa and by openalex are two sources.
                doi, arxiv_id = identifiers_from_url(r.url)
                candidates.append(SourceCandidate(
                    source_type=SourceType.EXA,
                    url=r.url,
                    title=r.title or r.url,
                    author=None,
                    snippet=snippet,
                    metadata={"exa_id": r.id},
                    identifiers=Identifiers.build(doi=doi, arxiv_id=arxiv_id),
                ))
            return candidates
        except Exception as exc:
            logger.warning("Exa search failed for %r: %s", query, exc)
            return []

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        text = await fetch_exa_contents(candidate.url)
        if len(text) < 500:
            return None
        return RawSource(
            source_type=SourceType.EXA,
            url=candidate.url,
            title=candidate.title,
            author=candidate.author,
            text=text[:_MAX_CHARS],
            metadata=candidate.metadata,
            identifiers=candidate.identifiers,
        )


async def fetch_exa_contents(url: str) -> str:
    """Full-text retrieval for a URL Exa has already indexed. '' on failure."""
    if not settings.EXA_API_KEY:
        return ""
    try:
        from exa_py import Exa  # type: ignore
        client = Exa(api_key=settings.EXA_API_KEY)
        results = await asyncio.to_thread(client.get_contents, [url], text=True)
        for r in results.results:
            return getattr(r, "text", None) or ""
        return ""
    except Exception as exc:
        logger.warning("Exa contents fetch failed for %r: %s", url, exc)
        return ""
