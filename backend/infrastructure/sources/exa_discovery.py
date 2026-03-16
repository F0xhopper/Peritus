from __future__ import annotations

from typing import AsyncIterator

from exa_py import Exa

from core.config import get_settings
from core.exceptions import SourceIngestionError
from core.logger import get_logger
from domain.entities import SourceDocument

logger = get_logger(__name__)


def _get_exa_client() -> Exa:
    settings = get_settings()
    return Exa(api_key=settings.exa_api_key)


async def discover_sources(topic: str, max_results: int = 15) -> list[SourceDocument]:
    logger.info("exa_discover_sources", topic=topic, max_results=max_results)
    try:
        client = _get_exa_client()
        results = client.search_and_contents(
            f"{topic} comprehensive overview tutorial",
            num_results=max_results,
            type="neural",
            use_autoprompt=True,
            text=True,
            highlights=False,
        )
        docs: list[SourceDocument] = []
        for r in results.results:
            text = r.text or ""
            if len(text.strip()) < 100:
                continue
            docs.append(
                SourceDocument(
                    url=r.url,
                    title=r.title or r.url,
                    content=text[:12_000],
                    source_type="web",
                    metadata={"score": r.score, "published_date": r.published_date},
                )
            )
        logger.info("exa_sources_found", count=len(docs))
        return docs

    except Exception as exc:
        logger.error("exa_discovery_failed", error=str(exc))
        raise SourceIngestionError(f"Exa discovery failed: {exc}") from exc
