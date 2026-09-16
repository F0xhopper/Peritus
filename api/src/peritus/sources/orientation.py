"""What the planner reads before it writes the syllabus.

The research plan used to be written from the topic string alone. For "Thomism"
that produced eight concepts that were all Aquinas's philosophy — nothing on the
theology, the history of the school or its modern debates — while Wikipedia's
article on the same topic is organised under exactly those headings. Coverage
only measures the planner's concepts and the loop only searches for them, so a
facet the planner forgot is a facet the build never looks for.

So before planning, the build reads how one or two reference overviews structure
the topic — their opening paragraphs and section outlines — and shows the
planner that as a checklist of the topic's facets (docs/plans/syllabus.md,
phase 1). The brief is still written once, before any search, and never
rewritten after: reading an overview is not the loop rewriting its own goal.

The pack is best effort. Either lookup failing, or matching nothing, leaves it
short; both failing leaves it empty and the plan is written as it was before.
It never fails a build. The pages are not injected into the corpus — the
fetchers find them on their own merits, and the screening ledger stays a record
of what search produced.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.infrastructure.wikimedia import WikimediaClient
from peritus.sources.canonical import title_key
from peritus.sources.hosts import host_and_path, split_site_suffix

logger = get_logger(__name__)

ORIENTATION_TIMEOUT_SECONDS = 8.0
LEAD_MAX_CHARS = 3_000
OUTLINE_MAX_HEADINGS = 60
_TITLE_MATCH_RATIO = 0.6

_REFERENCE_DOMAINS: tuple[str, ...] = ("plato.stanford.edu", "iep.utm.edu", "britannica.com")
_EXA_TEXT_CHARS = 4_000

# Sections that are apparatus, not the topic.
_BOILERPLATE_SECTIONS = frozenset(
    {
        "see also",
        "references",
        "notes",
        "external links",
        "further reading",
        "bibliography",
        "sources",
        "citations",
        "footnotes",
        "works cited",
        "notes and references",
        "primary sources",
        "secondary sources",
        "academic tools",
        "other internet resources",
        "related entries",
    }
)

# "== Heading ==" at depth 1, "=== Sub ===" at depth 2, from the extract API's
# `exsectionformat=wiki`.
_WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
# "1. Life", "2.3 The Five Ways": the table of contents SEP and IEP entries open with.
_NUMBERED_HEADING = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-Z][^\n]{2,90})$", re.MULTILINE
)


@dataclass
class Overview:
    """One reference overview, as the planner is shown it."""

    source: str
    title: str
    url: str
    lead: str = ""
    # (depth, heading), depth 1 or 2, in the page's order.
    headings: list[tuple[int, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [f'<overview source="{self.source}" title="{self.title}" url="{self.url}">']
        if self.lead:
            lines.append(f"Lead: {self.lead}")
        if self.headings:
            lines.append("Outline:")
            lines.extend(f"{'  ' * (depth - 1)}- {text}" for depth, text in self.headings)
        lines.append("</overview>")
        return "\n".join(lines)

    def record(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "headings": [text for _depth, text in self.headings],
        }


@dataclass
class OrientationPack:
    overviews: list[Overview] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.overviews

    def render(self) -> str:
        return "\n\n".join(o.render() for o in self.overviews)

    def record(self, note: str = "") -> dict[str, Any]:
        return {"overviews": [o.record() for o in self.overviews], "note": note}


# ── parsing ──────────────────────────────────────────────────────────────────


def _is_boilerplate(heading: str) -> bool:
    return heading.strip().strip(":").casefold() in _BOILERPLATE_SECTIONS


def parse_wiki_extract(text: str) -> tuple[str, list[tuple[int, str]]]:
    """The lead and the depth-1/2 outline of a Wikipedia extract in wiki section format.

    A boilerplate section's subsections go with it ("References" → "Citations").
    """
    text = text or ""
    first = _WIKI_HEADING.search(text)
    lead = _clip(text[: first.start()] if first else text, LEAD_MAX_CHARS)
    headings: list[tuple[int, str]] = []
    skipping_below: int | None = None
    for match in _WIKI_HEADING.finditer(text):
        depth = len(match.group(1)) - 1
        heading = match.group(2).strip()
        if skipping_below is not None and depth > skipping_below:
            continue
        skipping_below = None
        if _is_boilerplate(heading):
            skipping_below = depth
            continue
        if depth > 2 or not heading:
            continue
        headings.append((depth, heading))
        if len(headings) >= OUTLINE_MAX_HEADINGS:
            break
    return lead, headings


def parse_numbered_outline(text: str) -> tuple[str, list[tuple[int, str]]]:
    """The lead and outline of an entry that opens with a numbered table of contents."""
    text = text or ""
    headings: list[tuple[int, str]] = []
    seen: set[str] = set()
    first_start: int | None = None
    for match in _NUMBERED_HEADING.finditer(text):
        number, heading = match.group(1), match.group(2).strip()
        depth = number.count(".") + 1
        key = f"{number} {heading}".casefold()
        if depth > 2 or key in seen or _is_boilerplate(heading):
            continue
        if first_start is None:
            first_start = match.start()
        seen.add(key)
        headings.append((depth, heading))
        if len(headings) >= OUTLINE_MAX_HEADINGS:
            break
    lead = _clip(text[:first_start] if first_start is not None else text, LEAD_MAX_CHARS)
    return lead, headings


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def title_matches_topic(topic: str, title: str) -> bool:
    t, w = title_key(split_site_suffix(title)[0]), title_key(topic)
    if not t or not w:
        return False
    return t == w or difflib.SequenceMatcher(None, w, t).ratio() >= _TITLE_MATCH_RATIO


def select_hit(topic: str, hits: list[dict[str, str]]) -> dict[str, str] | None:
    """The first hit titled after the topic, else the first whose snippet names it.

    Title matches are looked for across every hit before any snippet is: an
    article on Thomas Aquinas mentions Thomism in its snippet, and must not be
    chosen over the article on Thomism that ranks below it.
    """
    for hit in hits:
        if title_matches_topic(topic, hit.get("title", "")):
            return hit
    needle = topic.casefold().strip()
    for hit in hits:
        if needle and needle in (hit.get("snippet") or "").casefold():
            return hit
    return None


# ── lookups ──────────────────────────────────────────────────────────────────


async def _wikipedia_overview(topic: str) -> Overview | None:
    async with WikimediaClient(timeout=ORIENTATION_TIMEOUT_SECONDS) as wiki:
        hit = select_hit(topic, await wiki.search_with_snippets(topic, 3))
        if hit is None:
            return None
        extract = await wiki.extract(hit["title"], section_format="wiki")
    lead, headings = parse_wiki_extract(extract)
    if not lead and not headings:
        return None
    url = f"https://en.wikipedia.org/wiki/{hit['title'].replace(' ', '_')}"
    return Overview("Wikipedia", hit["title"], url, lead, headings)


async def _reference_overview(topic: str) -> Overview | None:
    if not settings.EXA_API_KEY:
        return None
    from exa_py import Exa  # type: ignore

    client = Exa(api_key=settings.EXA_API_KEY)
    results = await asyncio.to_thread(
        client.search_and_contents,
        topic,
        num_results=3,
        include_domains=list(_REFERENCE_DOMAINS),
        text={"max_characters": _EXA_TEXT_CHARS},
    )
    for r in results.results:
        title = r.title or ""
        if not r.url or not title_matches_topic(topic, title):
            continue
        lead, headings = parse_numbered_outline(getattr(r, "text", None) or "")
        if not lead and not headings:
            continue
        return Overview(host_and_path(r.url)[0], split_site_suffix(title)[0], r.url, lead, headings)
    return None


async def _quietly(name: str, lookup) -> Overview | None:
    try:
        return await lookup
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Orientation lookup %s failed (%s: %s)", name, type(exc).__name__, exc)
        return None


async def build_orientation_pack(
    topic: str, timeout: float = ORIENTATION_TIMEOUT_SECONDS
) -> OrientationPack:
    """Both lookups in parallel under one deadline. Never raises."""
    tasks = [
        asyncio.ensure_future(_quietly("wikipedia", _wikipedia_overview(topic))),
        asyncio.ensure_future(_quietly("reference", _reference_overview(topic))),
    ]
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning(
            "Orientation: %d lookup(s) still running after %.0fs — planning without them",
            len(pending),
            timeout,
        )
    overviews = [
        overview
        for task in tasks
        if task in done and not task.cancelled() and (overview := task.result()) is not None
    ]
    return OrientationPack(overviews)
