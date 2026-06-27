from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_MAX_CHARS = 80_000


class ExaFetcher:
    async def fetch(self, topic: str, max_results: int = 8) -> list[RawSource]:
        if not settings.EXA_API_KEY:
            logger.warning("EXA_API_KEY not set — skipping Exa fetcher")
            return []

        try:
            from exa_py import Exa  # type: ignore
            client = Exa(api_key=settings.EXA_API_KEY)
            results = client.search_and_contents(
                topic,
                num_results=max_results,
                type="neural",
                text=True,
            )
            sources = []
            for r in results.results:
                text = getattr(r, "text", None) or ""
                if len(text) < 500:
                    continue
                sources.append(RawSource(
                    source_type=SourceType.EXA,
                    url=r.url or "",
                    title=r.title or r.url or "Untitled",
                    author=None,
                    text=text[:_MAX_CHARS],
                    metadata={"exa_id": r.id},
                ))
            return sources
        except Exception as exc:
            logger.warning("Exa fetch failed for %r: %s", topic, exc)
            return []
