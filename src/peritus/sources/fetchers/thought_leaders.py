"""Thought-leader fetcher — Claude identifies authoritative voices, then finds their content."""

import asyncio

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import RawSource, SourceType

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "Peritus/2.0 (educational; foxhopper16@gmail.com)"}
_MAX_CHARS = 50_000

_IDENTIFY_TOOL = {
    "name": "identify_thought_leaders",
    "description": "Identify the top thought leaders, authors, and practitioners for a topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "leaders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "description": "e.g. pioneer, author, researcher"},
                        "known_for": {"type": "string", "description": "Their most notable work or contribution"},
                    },
                    "required": ["name", "role", "known_for"],
                },
                "maxItems": 6,
            }
        },
        "required": ["leaders"],
    },
}


class ThoughtLeadersFetcher:
    async def fetch(self, topic: str, max_results: int = 6) -> list[RawSource]:
        leaders = await _identify_leaders(topic)
        if not leaders:
            return []

        tasks = [_fetch_leader_content(leader, topic) for leader in leaders[:4]]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        sources: list[RawSource] = []
        for batch in results_list:
            if isinstance(batch, Exception):
                logger.warning("Leader content fetch failed: %s", batch)
                continue
            sources.extend(batch)

        return sources[:max_results]


async def _identify_leaders(topic: str) -> list[dict]:
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(
            model=settings.FAST_MODEL,
            max_tokens=512,
            system=(
                "You identify the most authoritative thought leaders, authors, and practitioners "
                "for educational topics. Return real people with verifiable published work."
            ),
            tools=[_IDENTIFY_TOOL],
            tool_choice={"type": "tool", "name": "identify_thought_leaders"},
            messages=[{
                "role": "user",
                "content": f"Who are the 4–6 most important thought leaders, authors, or practitioners for: {topic}?",
            }],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        leaders = block.input.get("leaders", [])
        logger.info("Identified %d thought leaders for %r: %s", len(leaders), topic,
                    ", ".join(l["name"] for l in leaders))
        return leaders
    except Exception as exc:
        logger.warning("Thought leader identification failed: %s", exc)
        return []


async def _fetch_leader_content(leader: dict, topic: str) -> list[RawSource]:
    name = leader["name"]
    query = f'"{name}" {topic}'

    if settings.EXA_API_KEY:
        return await _fetch_via_exa(query, name, leader)
    return await _fetch_via_web(query, name, leader)


async def _fetch_via_exa(query: str, name: str, leader: dict) -> list[RawSource]:
    try:
        from exa_py import Exa  # type: ignore
        client = Exa(api_key=settings.EXA_API_KEY)
        results = client.search_and_contents(query, num_results=2, type="neural", text=True)
        sources = []
        for r in results.results:
            text = getattr(r, "text", None) or ""
            if len(text) < 500:
                continue
            sources.append(RawSource(
                source_type=SourceType.THOUGHT_LEADER,
                url=r.url or "",
                title=r.title or name,
                author=name,
                text=text[:_MAX_CHARS],
                metadata={"leader": name, "role": leader.get("role"), "known_for": leader.get("known_for")},
            ))
        return sources
    except Exception as exc:
        logger.warning("Exa search for leader %r failed: %s", name, exc)
        return []


async def _fetch_via_web(query: str, name: str, leader: dict) -> list[RawSource]:
    from peritus.sources.fetchers.web import _ddg_search, _fetch_page

    try:
        urls = await _ddg_search(query, 2)
    except Exception as exc:
        logger.warning("DDG search for leader %r failed: %s", name, exc)
        return []

    sources = []
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
        for url in urls:
            try:
                text, title = await _fetch_page(client, url)
                if len(text) < 500:
                    continue
                sources.append(RawSource(
                    source_type=SourceType.THOUGHT_LEADER,
                    url=url,
                    title=title,
                    author=name,
                    text=text[:_MAX_CHARS],
                    metadata={"leader": name, "role": leader.get("role"), "known_for": leader.get("known_for")},
                ))
            except Exception as exc:
                logger.warning("Web fetch for leader %r at %r failed: %s", name, url, exc)
    return sources
