"""Thought-leader fetcher — the field's voices, and writing *by* them.

The channel exists to put a tradition's figures into the corpus in their own
voice. On a live Thomism build it returned the Stanford Encyclopedia's entry on
Maritain and the Internet Encyclopedia's entry on Aquinas — both correctly
classified tertiary, neither what the channel is for — because a neural search
for "Jacques Maritain Thomism" ranks the entry about him first
(docs/plans/syllabus.md, 3.C). So:

- the people come from the research plan's ``figures`` when it named some, the
  same definition of primary the validator judges by; a second, blind model
  call names them only when the plan did not;
- each person is searched twice: ``{name} {topic}`` with the encyclopedias and
  summary services excluded, and ``{name}`` restricted to personal sites;
- a hit on one of those hosts, or titled as an entry about a person, is dropped
  before triage.
"""

import asyncio
from typing import Any

import httpx

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.anthropic_client import get_anthropic_client
from peritus.sources.dedup import normalise_url
from peritus.sources.domain import RawSource, SourceCandidate, SourceType
from peritus.sources.fetchers.base import note_search_failure
from peritus.sources.fetchers.exa import classify_search_error
from peritus.sources.hosts import ABOUT_HOSTS, is_about_page

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "Peritus/2.0 (research corpus builder)"}
_MAX_CHARS = 50_000
# Results per person, per search.
_RESULTS_PER_SEARCH = 3
_MAX_PEOPLE = 6

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
                        "role": {
                            "type": "string",
                            "description": "e.g. pioneer, author, researcher",
                        },
                        "known_for": {
                            "type": "string",
                            "description": "Their most notable work or contribution",
                        },
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
    def __init__(self, figures: list[dict] | None = None, topic: str = "") -> None:
        """``figures`` are the research plan's; with them, the channel searches for
        those people instead of identifying people afresh."""
        self._figures = [f for f in figures or [] if str(f.get("name") or "").strip()]
        self._topic = topic

    async def search(self, query: str, max_results: int = 6) -> list[SourceCandidate]:
        if self._figures:
            people = [
                {"name": f["name"], "role": "figure", "known_for": f.get("why") or ""}
                for f in self._figures
            ]
            topic = self._topic or query
        else:
            people = await _identify_leaders(query)
            topic = query
        if not people:
            return []
        return (await self.search_people(people, topic))[:max_results]

    @staticmethod
    async def search_people(people: list[dict], topic: str) -> list[SourceCandidate]:
        """Writing by each person, about-pages dropped, interleaved person by person.

        Interleaved so a cap on the results keeps some of every person's rather
        than all of the first one's. Never raises.
        """
        tasks = [_search_leader_content(person, topic) for person in people[:_MAX_PEOPLE]]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        batches: list[list[SourceCandidate]] = []
        for batch in results_list:
            if isinstance(batch, BaseException):
                logger.warning("Leader content search failed: %s", batch)
                continue
            batches.append([c for c in batch if not is_about_page(c.title, c.url)])
        return _interleave(batches)

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
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Who are the 4–6 most important thought leaders, authors, "
                        f"or practitioners for: {topic}?"
                    ),
                }
            ],
        )
        block = next(b for b in resp.content if getattr(b, "type", None) == "tool_use")
        leaders = block.input.get("leaders", [])
        logger.info(
            "Identified %d thought leaders for %r: %s",
            len(leaders),
            topic,
            ", ".join(ldr["name"] for ldr in leaders),
        )
        return leaders
    except Exception as exc:
        logger.warning("Thought leader identification failed: %s", exc)
        note_search_failure(*classify_search_error(exc, "leader identification"))
        return []


async def _search_leader_content(leader: dict, topic: str) -> list[SourceCandidate]:
    name = leader["name"]
    base_metadata = {
        "leader": name,
        "role": leader.get("role"),
        "known_for": leader.get("known_for") or leader.get("why"),
    }

    if settings.EXA_API_KEY:
        return await exa_people_searches(name, topic, base_metadata)
    return await _search_via_web(f'"{name}" {topic}', name, base_metadata)


def people_search_calls(name: str, topic: str) -> list[tuple[str, dict]]:
    """The Exa searches for one person: ``(query, keyword arguments)``.

    The topic search excludes the hosts whose pages are about people; the
    personal-site search is where a living figure's own essays and lecture
    transcripts are.
    """
    common = {"num_results": _RESULTS_PER_SEARCH, "type": "neural", "text": {"max_characters": 600}}
    return [
        (f"{name} {topic}", {**common, "exclude_domains": list(ABOUT_HOSTS)}),
        (name, {**common, "category": "personal site"}),
    ]


async def exa_people_searches(name: str, topic: str, base_metadata: dict) -> list[SourceCandidate]:
    from exa_py import Exa  # type: ignore

    """Both searches for one person, concurrently, their results interleaved.

    Interleaved rather than stacked, so the personal-site hits are not all behind
    the topic hits when the channel's results are capped.
    """
    client = Exa(api_key=settings.EXA_API_KEY)
    calls = people_search_calls(name, topic)
    responses = await asyncio.gather(
        *[
            asyncio.to_thread(client.search_and_contents, query, **kwargs)
            for query, kwargs in calls
        ],
        return_exceptions=True,
    )
    per_search: list[list[SourceCandidate]] = []
    for (query, _kwargs), response in zip(calls, responses, strict=True):
        if isinstance(response, BaseException):
            # The personal-site category is not accepted everywhere; one search
            # failing costs its results, never the other search's.
            logger.warning("Exa search for leader %r (%s) failed: %s", name, query, response)
            continue
        per_search.append(
            [
                SourceCandidate(
                    source_type=SourceType.THOUGHT_LEADER,
                    url=r.url,
                    title=r.title or name,
                    author=name,
                    snippet=getattr(r, "text", None) or "",
                    metadata={**base_metadata, "exa_id": r.id},
                )
                for r in response.results
                if r.url
            ]
        )
    return _interleave(per_search)


def _interleave(batches: list[list[SourceCandidate]]) -> list[SourceCandidate]:
    """First of each batch, then second of each, …; a URL seen once is not repeated."""
    out: list[SourceCandidate] = []
    seen: set[str] = set()
    for rank in range(max((len(b) for b in batches), default=0)):
        for batch in batches:
            if rank < len(batch) and (key := normalise_url(batch[rank].url)) not in seen:
                seen.add(key)
                out.append(batch[rank])
    return out


async def _search_via_web(query: str, name: str, base_metadata: dict) -> list[SourceCandidate]:
    from peritus.sources.fetchers.web import _ddg_search

    try:
        hits = await _ddg_search(query, _RESULTS_PER_SEARCH)
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
