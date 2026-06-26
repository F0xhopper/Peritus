"""Reddit fetcher — finds posts via DuckDuckGo site search, scrapes old.reddit.com."""

import asyncio

import httpx
from bs4 import BeautifulSoup

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "Peritus/2.0 (educational; foxhopper16@gmail.com)"}
_MAX_CHARS = 50_000


class RedditFetcher:
    async def fetch(self, topic: str, max_results: int = 8) -> list[RawSource]:
        from peritus.sources.fetchers.web import _ddg_search

        try:
            urls = await _ddg_search(f"site:reddit.com {topic}", max_results)
        except Exception as exc:
            logger.warning("DDG Reddit search failed for %r: %s", topic, exc)
            return []

        if not urls:
            return []

        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS, follow_redirects=True
        ) as client:
            tasks = [_fetch_post(client, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        sources = [r for r in results if isinstance(r, RawSource)]
        return sources[:max_results]


async def _fetch_post(client: httpx.AsyncClient, url: str) -> RawSource | None:
    old_url = url.replace("www.reddit.com", "old.reddit.com")
    try:
        resp = await client.get(old_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("a.title")
        title = title_el.get_text(strip=True) if title_el else old_url

        # OP body (absent for pure link posts)
        usertext = soup.select_one(".usertext-body .md")
        op_text = usertext.get_text(separator="\n", strip=True) if usertext else ""

        # Top-level comments — the real content in most threads
        comment_blocks = soup.select(
            ".commentarea .sitetable .thing.comment > .entry .usertext .md"
        )
        comment_parts = [
            b.get_text(separator="\n", strip=True)
            for b in comment_blocks[:10]
            if len(b.get_text(strip=True)) > 100
        ]

        full_text = title
        if op_text:
            full_text += f"\n\n{op_text}"
        if comment_parts:
            full_text += "\n\n" + "\n\n---\n\n".join(comment_parts)

        if len(full_text) < 500:
            return None

        return RawSource(
            source_type=SourceType.REDDIT,
            url=url,
            title=title,
            author=None,
            text=full_text[:_MAX_CHARS],
            metadata={"subreddit": _extract_subreddit(url)},
        )
    except Exception as exc:
        logger.warning("old.reddit.com fetch failed for %r: %s", url, exc)
        return None


def _extract_subreddit(url: str) -> str | None:
    parts = url.split("/")
    try:
        idx = parts.index("r")
        return parts[idx + 1] if idx + 1 < len(parts) else None
    except ValueError:
        return None
