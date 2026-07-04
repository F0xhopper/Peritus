"""Thought-leader fetcher — Claude identifies authoritative voices, then finds their content."""

import asyncio
from typing import Any

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.domain import RawSource, SourceCandidate, SourceType

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MAX_CHARS = 50_000

_IDENTIFY_TOOL: dict[str, Any] = {
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
    async def search(self, query: str, max_results: int = 6) -> list[SourceCandidate]:
        leaders = await _identify_leaders(query)
        if not leaders:
            return []

        tasks = [_search_leader_content(leader, query) for leader in leaders[:4]]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[SourceCandidate] = []
        for batch in results_list:
            if isinstance(batch, BaseException):
                logger.warning("Leader content search failed: %s", batch)
                continue
            candidates.extend(batch)

        return candidates[:max_results]

    async def fetch(self, candidate: SourceCandidate) -> RawSource | None:
        name = candidate.metadata["leader"]
        if candidate.metadata.get("exa_id"):
            from peritus.sources.fetchers.exa import fetch_exa_contents
            text = await fetch_exa_contents(candidate.url)
            title = candidate.title
        else:
            from peritus.sources.fetchers.web import _fetch_page
            try:
                async with httpx.AsyncClient(
                    timeout=20, headers=_HEADERS, follow_redirects=True
                ) as client:
                    text, title = await _fetch_page(client, candidate.url)
            except Exception as exc:
                logger.warning("Web fetch for leader %r at %r failed: %s", name, candidate.url, exc)
                return None

        if len(text) < 500:
            return None
        if not _mentions_leader(name, title, text):
            logger.debug("Skipping hit that never mentions %r: %s", name, candidate.url)
            return None
        return RawSource(
            source_type=SourceType.THOUGHT_LEADER,
            url=candidate.url,
            title=title or name,
            author=name,
            text=text[:_MAX_CHARS],
            metadata=candidate.metadata,
        )


def _mentions_leader(name: str, title: str, text: str) -> bool:
    """Cheap pre-filter: a page that never mentions the person is a bad search hit.

    (Whether the content is *by* them rather than *about* them is judged later —
    the validator gets an expected-author hint from this fetcher's metadata.)
    """
    surname = name.strip().split()[-1] if name.strip() else ""
    if len(surname) < 3:
        return True  # too short to test meaningfully; let the validator decide
    haystack = f"{title}\n{text[:10_000]}".casefold()
    return surname.casefold() in haystack


async def _identify_leaders(topic: str) -> list[dict]:
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(  # type: ignore[call-overload]
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
                    ", ".join(ldr["name"] for ldr in leaders))
        return leaders
    except Exception as exc:
        logger.warning("Thought leader identification failed: %s", exc)
        return []


async def _search_leader_content(leader: dict, topic: str) -> list[SourceCandidate]:
    name = leader["name"]
    query = f'"{name}" {topic}'
    base_metadata = {
        "leader": name,
        "role": leader.get("role"),
        "known_for": leader.get("known_for"),
    }

    if settings.EXA_API_KEY:
        return await _search_via_exa(query, name, base_metadata)
    return await _search_via_web(query, name, base_metadata)


async def _search_via_exa(query: str, name: str, base_metadata: dict) -> list[SourceCandidate]:
    try:
        from exa_py import Exa  # type: ignore
        client = Exa(api_key=settings.EXA_API_KEY)
        results = await asyncio.to_thread(
            client.search_and_contents,
            query,
            num_results=2,
            type="neural",
            text={"max_characters": 600},
        )
        candidates = []
        for r in results.results:
            if not r.url:
                continue
            candidates.append(SourceCandidate(
                source_type=SourceType.THOUGHT_LEADER,
                url=r.url,
                title=r.title or name,
                author=name,
                snippet=getattr(r, "text", None) or "",
                metadata={**base_metadata, "exa_id": r.id},
            ))
        return candidates
    except Exception as exc:
        logger.warning("Exa search for leader %r failed: %s", name, exc)
        return []


async def _search_via_web(query: str, name: str, base_metadata: dict) -> list[SourceCandidate]:
    from peritus.sources.fetchers.web import _ddg_search

    try:
        hits = await _ddg_search(query, 2)
    except Exception as exc:
        logger.warning("DDG search for leader %r failed: %s", name, exc)
        return []

    return [
        SourceCandidate(
            source_type=SourceType.THOUGHT_LEADER,
            url=hit["url"],
            title=hit["title"] or name,
            author=name,
            snippet=hit["snippet"],
            metadata=dict(base_metadata),
        )
        for hit in hits
    ]
