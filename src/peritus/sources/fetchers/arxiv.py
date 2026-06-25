import arxiv  # type: ignore

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)


class ArxivFetcher:
    async def fetch(self, topic: str, max_results: int = 3) -> list[RawSource]:
        sources = []
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=topic,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            for result in client.results(search):
                text = f"{result.title}\n\n{result.summary}"
                sources.append(RawSource(
                    source_type=SourceType.ARXIV,
                    url=result.entry_id,
                    title=result.title,
                    author=", ".join(str(a) for a in result.authors[:3]),
                    text=text,
                    metadata={
                        "arxiv_id": result.entry_id,
                        "published": str(result.published),
                        "categories": result.categories,
                    },
                ))
        except Exception as exc:
            logger.warning("ArXiv fetch failed for %r: %s", topic, exc)
        return sources
