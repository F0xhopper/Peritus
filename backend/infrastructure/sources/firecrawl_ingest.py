"""Firecrawl deep-crawl adapter for richer content extraction."""

from __future__ import annotations

from firecrawl import FirecrawlApp

from core.config import get_settings
from core.exceptions import SourceIngestionError
from core.logger import get_logger
from domain.entities import SourceDocument

logger = get_logger(__name__)


def _get_firecrawl_client() -> FirecrawlApp:
    settings = get_settings()
    if not settings.firecrawl_api_key:
        raise SourceIngestionError("FIRECRAWL_API_KEY not set.")
    return FirecrawlApp(api_key=settings.firecrawl_api_key)


async def crawl_url(url: str) -> SourceDocument | None:
    """
    Deep-crawl a URL with Firecrawl and return a SourceDocument.

    Returns None if Firecrawl key is missing or scrape fails.

    Args:
        url: The URL to crawl.
    """
    settings = get_settings()
    if not settings.firecrawl_api_key:
        logger.warning("firecrawl_key_missing_skipping", url=url)
        return None

    try:
        client = _get_firecrawl_client()
        result = client.scrape_url(
            url,
            params={"formats": ["markdown"], "onlyMainContent": True},
        )
        markdown = result.get("markdown", "") or ""
        if len(markdown.strip()) < 100:
            return None

        return SourceDocument(
            url=url,
            title=result.get("metadata", {}).get("title", url),
            content=markdown[:15_000],
            source_type="crawl",
            metadata=result.get("metadata", {}),
        )
    except Exception as exc:
        logger.warning("firecrawl_scrape_failed", url=url, error=str(exc))
        return None


async def enrich_sources(
    sources: list[SourceDocument],
    limit: int = 5,
) -> list[SourceDocument]:
    """
    Re-crawl the top sources with Firecrawl to get richer markdown content.

    Args:
        sources: Existing source documents (e.g. from Exa).
        limit: How many to re-crawl.

    Returns:
        Enriched list where Firecrawl content replaces original where available.
    """
    enriched: list[SourceDocument] = []
    for src in sources[:limit]:
        crawled = await crawl_url(src.url)
        enriched.append(crawled if crawled else src)
    # Append remaining sources unchanged
    enriched.extend(sources[limit:])
    return enriched
