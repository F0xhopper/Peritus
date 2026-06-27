"""Reddit fetcher — discovers via DuckDuckGo, fetches content via Reddit JSON API."""

import asyncio

import httpx

from peritus.core.logging import get_logger
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_HEADERS = {
    "User-Agent": "Peritus/2.0 (educational; foxhopper16@gmail.com)",
    "Accept": "application/json",
}
_MAX_CHARS = 50_000


class RedditFetcher:
    async def fetch(self, topic: str, max_results: int = 8) -> list[RawSource]:
        from peritus.sources.fetchers.web import _ddg_search

        try:
            urls = await _ddg_search(f"site:reddit.com/r {topic}", max_results)
        except Exception as exc:
            logger.warning("DDG Reddit search failed for %r: %s", topic, exc)
            return []

        if not urls:
            return []

        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *[_fetch_post(client, url) for url in urls],
                return_exceptions=True,
            )

        sources = [r for r in results if isinstance(r, RawSource)]
        return sources[:max_results]


async def _fetch_post(client: httpx.AsyncClient, url: str) -> RawSource | None:
    # Build the Reddit JSON API URL from whatever URL format we received
    clean = url.rstrip("/").split("?")[0]
    clean = clean.replace("old.reddit.com", "www.reddit.com")
    json_url = f"{clean}.json?limit=15&depth=1&sort=top"

    try:
        resp = await client.get(json_url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Reddit JSON fetch failed for %r: %s", url, exc)
        return None

    # Reddit JSON: [post_listing, comment_listing]
    if not isinstance(data, list) or not data:
        return None

    post_children = data[0].get("data", {}).get("children", [])
    if not post_children:
        return None

    post = post_children[0].get("data", {})
    title = post.get("title", "")
    selftext = (post.get("selftext") or "").strip()

    full_text = title
    if selftext and selftext not in ("[deleted]", "[removed]"):
        full_text += f"\n\n{selftext}"

    if len(data) > 1:
        comment_children = data[1].get("data", {}).get("children", [])
        comment_parts = []
        for c in comment_children:
            if c.get("kind") != "t1":
                continue
            body = (c.get("data", {}).get("body") or "").strip()
            c_score = c.get("data", {}).get("score", 0)
            if body and body not in ("[deleted]", "[removed]") and len(body) > 100 and c_score >= 5:
                comment_parts.append(body)
            if len(comment_parts) >= 10:
                break
        if comment_parts:
            full_text += "\n\n" + "\n\n---\n\n".join(comment_parts)

    if len(full_text) < 500:
        return None

    return RawSource(
        source_type=SourceType.REDDIT,
        url=url,
        title=title,
        author=post.get("author"),
        text=full_text[:_MAX_CHARS],
        metadata={
            "subreddit": post.get("subreddit"),
            "score": post.get("score", 0),
        },
    )
