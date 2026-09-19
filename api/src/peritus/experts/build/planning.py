"""Stage 0: the research brief, and everything that shapes or checks it.

One Claude call per build produces the plan, and the plan decides what the whole
corpus will be: which fetchers run, what they search for, which concepts the
corpus must cover, and which specific works it must obtain. Nothing downstream
can recover from a bad plan, which is why the tool schema below is as strict as
it is and why every field comes back through a normaliser rather than being
trusted as returned.

The normalisers are not validation for its own sake. A model that returns
fourteen facets, or the same concept under three of them, or a "work" with no
title, produces a build that spends real money fetching the wrong things.
"""

from typing import Any

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from peritus.core.config import settings
from peritus.core.logging import get_logger
from peritus.experts.build.constants import (
    _FETCHER_NAMES,
    _MAX_QUERIES_PER_FETCHER,
)
from peritus.infrastructure.anthropic_client import get_anthropic_client, tool_input
from peritus.sources.canonical import WORK_KINDS, title_key
from peritus.sources.orientation import OrientationPack, build_orientation_pack
from peritus.sources.subject import (
    SUBJECT_CANON,
    SUBJECT_KINDS,
    SUBJECT_PRACTICE,
    SUBJECT_RESEARCH_FRONT,
    normalise_subject_kind,
)

logger = get_logger(__name__)


_FETCHER_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": _MAX_QUERIES_PER_FETCHER,
            "description": "1–3 search queries, together spanning different facets of the topic.",
        },
        "weight": {
            "type": "number",
            "description": (
                "Budget weight, 0–2. 0 = this source type would add noise for this "
                "topic and must be skipped; 1 = normal; 2 = this source type is "
                "especially valuable here."
            ),
        },
    },
    "required": ["queries", "weight"],
}


_WORK_PROPERTIES: dict[str, Any] = {
    "title": {"type": "string", "description": "The title as scholarship or the field cites it."},
    "author": {"type": "string"},
    "kind": {
        "type": "string",
        "enum": list(WORK_KINDS),
        "description": (
            "text = a primary text (a treatise, scripture, a classic, a founding "
            "document); book = a monograph; paper = a journal article or preprint; "
            "standard = a specification, guideline, statute or official document."
        ),
    },
    "public_domain": {
        "type": "boolean",
        "description": (
            "True only if an English text of it is in the public domain (published "
            "roughly 95+ years ago, or released openly) — it decides whether Project "
            "Gutenberg and the Internet Archive are searched for it."
        ),
    },
    "sections": {
        "type": "string",
        "description": (
            "For a long work, the numbered parts that matter, in the work's own "
            "numbering: 'qq. 90–97', 'Book II, chapters 1–10', 'sections 3–5', "
            "'Lectures 4–6'. Empty if the work is short or matters whole."
        ),
    },
    "open_text": {
        "type": "boolean",
        "description": (
            "True if an authorised full English text is freely online although the "
            "work is not public domain: an open-access edition, the publisher's free "
            "text, the author's own site. False for an ordinary in-copyright book."
        ),
    },
}


# A work the planner names in place of one that cannot be had: same fields, no
# substitute of its own.
_SUBSTITUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _WORK_PROPERTIES,
    "required": ["title", "kind", "public_domain"],
    "description": (
        "Only for a work that is neither public_domain nor open_text: a work with a "
        "free English text that teaches the same thing, looked for if this one "
        "cannot be had."
    ),
}


_WORK_SCHEMA_PROPERTIES: dict[str, Any] = {**_WORK_PROPERTIES, "substitute": _SUBSTITUTE_SCHEMA}


# Facets and concepts: docs/plans/syllabus.md, phase 2.
_MAX_FACETS = 5


_MAX_CONCEPTS_PER_FACET = 4


# Figures: phase 3.A.
_MAX_FIGURES = 6


def _plan_tool(max_concepts: int) -> ToolParam:
    return {
        "name": "create_research_plan",
        "description": (
            "Create a research plan: targeted queries and a budget weight per source "
            "fetcher, the facets and key concepts the corpus must cover, the figures "
            "whose own writing is primary, and must-have canonical works."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "orientation_note": {
                    "type": "string",
                    "description": (
                        "Only if an overview you were shown is about something adjacent "
                        "rather than this topic: say which, and that you relied on it "
                        "less. Otherwise empty."
                    ),
                },
                "fetcher_plans": {
                    "type": "object",
                    "description": (
                        "A plan for each fetcher, with queries tuned to what that source "
                        "type does best and a weight steering how much of the source budget "
                        "it deserves for this topic."
                    ),
                    "properties": dict.fromkeys(_FETCHER_NAMES, _FETCHER_PLAN_SCHEMA),
                },
                "facets": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": _MAX_FACETS,
                    "description": (
                        "The topic's major facets, each with the concepts under it an "
                        f"expert must be able to teach: 2–{_MAX_FACETS} facets, "
                        f"2–{_MAX_CONCEPTS_PER_FACET} concepts each, at most "
                        f"{max_concepts} concepts in all. The corpus is checked against "
                        "every concept and gaps are re-searched facet by facet. The count "
                        "scales with the topic's actual breadth — see the system prompt."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "concepts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": _MAX_CONCEPTS_PER_FACET,
                            },
                        },
                        "required": ["name", "concepts"],
                    },
                },
                "key_concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": max_concepts,
                    "description": (
                        "Legacy flat list of the concepts. Leave empty when facets are given."
                    ),
                },
                "subject_kind": {
                    "type": "string",
                    "enum": list(SUBJECT_KINDS),
                    "description": (
                        f"What kind of subject this is. {SUBJECT_CANON} = the texts are "
                        "the subject: a thinker, a school, a scripture, a literature, a "
                        "period of history read through its documents — old texts are "
                        f"the point. {SUBJECT_PRACTICE} = a craft or how-to field (a "
                        "trade, a hobby, a cuisine, husbandry, a sport, clinical or "
                        "professional practice) — what is authoritative is what "
                        "practitioners do now: extension services, professional "
                        "bodies, standard handbooks, recent reviews. "
                        f"{SUBJECT_RESEARCH_FRONT} = a fast-moving scientific or "
                        "technical field whose recent literature is the field. When a "
                        "topic is both, pick the one its questions will be: 'how do I' "
                        f"is {SUBJECT_PRACTICE}, 'what did he argue' is {SUBJECT_CANON}."
                    ),
                },
                "primary_source_definition": {
                    "type": "string",
                    "description": (
                        "One or two sentences: what counts as a PRIMARY source for this "
                        "topic, as opposed to analysis of it. For a thinker or school: their "
                        "own writings (and, for a tradition, its major figures' own works). For "
                        "a science: original research reports, datasets, trials. For a craft: "
                        "practitioners' first-hand accounts and technical standards. For "
                        "history: documents from the period. Used to classify every source."
                    ),
                },
                "figures": {
                    "type": "array",
                    "maxItems": _MAX_FIGURES,
                    "description": (
                        "People whose own writing is primary for this topic by your "
                        "definition. For each, one work of theirs with a freely available "
                        "English text: public domain, open access, or published by them "
                        "online (a blog, a lecture transcript, a preprint). Set obtainable "
                        "false and leave work out when nothing of theirs is freely "
                        "available — name them anyway."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "why": {
                                "type": "string",
                                "description": "One line: why their own voice matters here.",
                            },
                            "work": {
                                "type": "object",
                                "properties": _WORK_PROPERTIES,
                                "required": ["title", "kind", "public_domain"],
                            },
                            "obtainable": {"type": "boolean"},
                        },
                        "required": ["name", "why", "obtainable"],
                    },
                },
                "must_have_works": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": _WORK_SCHEMA_PROPERTIES,
                        "required": ["title", "kind", "public_domain"],
                    },
                    "maxItems": 4,
                    "description": (
                        "Named canonical works (books, papers, essays, standards) an expert "
                        "corpus on this topic as a whole should contain, if any exist."
                    ),
                },
                "concept_primary_texts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "The key concept, copied verbatim from facets.",
                            },
                            **_WORK_SCHEMA_PROPERTIES,
                        },
                        "required": ["concept", "title", "kind", "public_domain"],
                    },
                    "maxItems": 16,
                    "description": (
                        "For each key concept, the one or two primary texts (as defined in "
                        "primary_source_definition) where that concept is actually set out — "
                        "with the sections that set it out when the text is long. Name a "
                        "text only if you are confident it exists and teaches the concept; "
                        "leave a concept out rather than guess."
                    ),
                },
            },
            "required": [
                "fetcher_plans",
                "facets",
                "subject_kind",
                "primary_source_definition",
            ],
        },
    }


_ORIENTATION_PROMPT = (
    "You may be shown how one or two reference overviews structure this topic — their "
    "opening paragraphs and section outlines. Use them as a checklist of the topic's "
    "facets, not as the syllabus: every major facet they treat should be represented in "
    "your concepts unless it is clearly outside what an expert on this topic must teach, "
    "and you should add what they omit. Take the field's own terms and names from them "
    "for your queries. If an overview is about something adjacent rather than this "
    "topic, say so in orientation_note and rely on it less."
)


def _plan_system(max_concepts: int) -> str:
    return (
        _PLAN_SYSTEM + "\n\n" + _ORIENTATION_PROMPT + "\n\n"
        f"Group the concepts under facets — the topic's major areas (for a tradition: its "
        "doctrines, its history and schools, its modern debates; for a science: its "
        "theory, its methods, its applications). The concept count must scale with how "
        "much ground the topic actually covers — this is a judgment call, not a quota. A "
        "narrow or single-threaded topic (one thinker, one event, one narrow technique) "
        "genuinely has fewer concepts worth naming as separate teaching points; padding it "
        "out means inventing overlapping or trivial ones. A broad field (a whole "
        f"discipline, a wide practice, a tradition) earns more, up to {max_concepts}. "
        "Default to the number the topic actually supports, not the maximum allowed.\n\n"
        "Name the figures whose own writing is primary by your definition, and one work of "
        "each that can be had freely in English. A corpus that defines a tradition's "
        "commentators as primary and contains none of them in their own voice has not "
        "found the tradition. For a canonical work still in copyright, mark public_domain "
        "and open_text honestly and name a substitute with a free English text: name both, "
        "never silently swap one for the other."
    )


_PLAN_SYSTEM = (
    "You are planning the research for building a grounded AI expert. The sources this "
    "plan discovers are the ONLY material the expert will ever know, so plan for breadth "
    "(every major facet of the topic gets searched) and depth (primary and advanced "
    "material, not just introductions). Tune queries to each source type: arxiv gets "
    "STEM preprints (physics, math, CS), openalex gets peer-reviewed scholarship in "
    "ANY discipline — it is the academic channel for humanities, social science, law, "
    "economics, psychology, education, business and everything else arxiv and pubmed "
    "don't reach — pubmed gets biomedical and clinical literature, gutenberg gets "
    "classic public-domain primary texts, pdf gets open-access published papers, "
    "thought_leaders finds the field's leading practitioners and their own writing, "
    "reddit gets practitioner discussion, youtube gets lectures and talks, wikipedia "
    "gets encyclopedic overviews, exa and web get high-quality articles and essays. "
    "Give weight 0 to source types that would add noise for this topic (e.g. gutenberg "
    "for modern technology, arxiv for a non-academic craft, pubmed for anything "
    "non-biomedical) and weight 2 to the ones that carry it. Every topic has some "
    "scholarly literature — a craft has ergonomics and materials-science studies, a "
    "cuisine has food chemistry and anthropology — so before zeroing openalex, ask "
    "what the adjacent research field is and query that.\n\n"
    "A corpus that only contains material ABOUT its subject answers second-hand. So say "
    "what counts as primary for this topic, name the works canonical for the topic as a "
    "whole (must_have_works), and for each key concept name the primary text that "
    "actually sets it out (concept_primary_texts). Works are looked for by title and cut "
    "to the sections you name, so name them precisely: the title as the field cites it, "
    "the author, and — for a long work — the numbered parts in the work's own numbering. "
    "Mark public_domain honestly; it decides whether Project Gutenberg and the Internet "
    "Archive are searched. The corpus is in English, so name works as English editions "
    "cite them. For a long work named in must_have_works, leave sections empty unless "
    "one part matters most for the topic as a whole — the concept entries say which "
    "parts each concept needs.\n\n"
    "Say what kind of subject this is (subject_kind), because it decides what "
    "authoritative means. What can be fetched whole and free is public-domain books "
    "(a century old and more) and open-access research papers. For a canon that is "
    "the right corpus. For a practice it is not: a nineteenth-century manual and two "
    "narrow research papers cannot tell a reader how the craft is done today, so for "
    "a practice plan queries that reach current practitioner guidance — extension "
    "services, professional and trade bodies, standard handbooks, recent reviews — "
    "and keep old manuals for the history. For a research front, weight the recent "
    "literature and its reviews."
)


def plan_user_message(topic: str, orientation: OrientationPack | None) -> str:
    """The planner's input: the topic, then whatever the orientation pack read."""
    if orientation is None or orientation.empty:
        return f"Topic: {topic}"
    return f"Topic: {topic}\n\n{orientation.render()}"


async def _plan_research(topic: str, max_concepts: int = 8) -> dict:
    """One call on the strong model — the brief shapes the whole corpus.

    The planner reads a reference overview or two first (sources/orientation.py)
    and is shown how they structure the topic. That lookup never fails the plan:
    without it, the plan is written from the topic alone, as it always was.

    Always returns a normalised plan: every fetcher has non-empty queries and a
    clamped weight, even when the model call fails (fallback = raw topic, weight 1).
    """
    orientation = await build_orientation_pack(topic)
    if orientation.empty:
        logger.info("Orientation for %r: nothing read — planning from the topic alone", topic)
    else:
        logger.info(
            "Orientation for %r: read %s",
            topic,
            "; ".join(
                f"{o.source} {o.title!r} ({len(o.headings)} headings)"
                for o in orientation.overviews
            ),
        )

    raw_plan: dict = {}
    try:
        client = get_anthropic_client()
        resp = await client.messages.create(
            model=settings.PLAN_MODEL,
            max_tokens=4000,
            system=_plan_system(max_concepts),
            tools=[_plan_tool(max_concepts)],
            tool_choice=ToolChoiceToolParam(type="tool", name="create_research_plan"),
            messages=[MessageParam(role="user", content=plan_user_message(topic, orientation))],
        )
        raw_plan = tool_input(resp) or {}
    except Exception as exc:
        logger.warning(
            "Research planning failed (%s: %s) — falling back to raw topic. The build "
            "continues DEGRADED: no key concepts, one query per fetcher instead of "
            "several, and no coverage gap-fill.",
            type(exc).__name__,
            exc,
            exc_info=True,
        )

    plan = _normalise_plan(raw_plan, topic, max_concepts)
    plan["orientation"] = orientation.record(plan.pop("orientation_note", ""))
    logger.info(
        "Research plan for %r: kind=%s facets=[%s] weights={%s} must_have=[%s] figures=[%s]",
        topic,
        plan["subject_kind"],
        "; ".join(f"{f['name']}: {', '.join(f['concepts'])}" for f in plan["facets"]),
        ", ".join(f"{n}:{p['weight']:g}" for n, p in plan["fetcher_plans"].items()),
        "; ".join(w["title"] for w in plan["must_have_works"]),
        ", ".join(f["name"] for f in plan["figures"]),
    )
    if not plan["key_concepts"]:
        # Reachable without an exception too — a model can return a well-formed
        # plan with an empty concept list. Either way every downstream stage that
        # takes key_concepts (triage, validation, gap-fill) is now working blind,
        # and until this line said so the only evidence was an empty list buried
        # in the plan_ready event.
        logger.warning(
            "Research plan for %r has NO key concepts — triage, validation and "
            "gap-fill will all run without a syllabus to score against",
            topic,
        )
    return plan


def _normalise_plan(raw_plan: dict, topic: str, max_concepts: int = 8) -> dict:
    """Coerce a model-produced plan into a safe, complete shape.

    ``facets`` is the syllabus's two levels; ``key_concepts`` is the same
    concepts flattened in facet order, which is what every downstream reader
    (triage, validation, coverage, feedback, both clients) keeps reading.
    """
    fetcher_plans: dict[str, dict] = {}
    raw_fetcher_plans = raw_plan.get("fetcher_plans") or {}
    for name in _FETCHER_NAMES:
        raw = raw_fetcher_plans.get(name) or {}
        queries: list[str] = []
        for q in raw.get("queries") or []:
            if (
                isinstance(q, str)
                and q.strip()
                and q.strip().casefold() not in {d.casefold() for d in queries}
            ):
                queries.append(q.strip())
        try:
            weight = float(raw.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        fetcher_plans[name] = {
            "queries": queries[:_MAX_QUERIES_PER_FETCHER] or [topic],
            "weight": min(max(weight, 0.0), 2.0),
        }

    facets = _normalise_facets(raw_plan, topic, max_concepts)
    key_concepts = [c for facet in facets for c in facet["concepts"]]

    must_have_works = [
        work
        for raw in raw_plan.get("must_have_works") or []
        if isinstance(raw, dict) and (work := _normalise_work(raw)) is not None
    ]

    canonical_concepts = {c.casefold(): c for c in key_concepts}
    concept_texts = []
    for raw in raw_plan.get("concept_primary_texts") or []:
        if not isinstance(raw, dict):
            continue
        work = _normalise_work(raw)
        concept = canonical_concepts.get(str(raw.get("concept") or "").strip().casefold())
        if work is None or concept is None:
            continue
        concept_texts.append({"concept": concept, **work})

    definition = raw_plan.get("primary_source_definition")
    note = raw_plan.get("orientation_note")
    return {
        "fetcher_plans": fetcher_plans,
        # Canon for anything missing or unknown — today's behaviour, so a failed
        # plan or an old one changes nothing downstream (sources/subject.py).
        "subject_kind": normalise_subject_kind(raw_plan.get("subject_kind")),
        "facets": facets,
        "key_concepts": key_concepts,
        "primary_source_definition": definition.strip() if isinstance(definition, str) else "",
        "must_have_works": must_have_works[:4],
        # At most two per concept: a third text for one concept is budget another
        # concept's primary text does not get.
        "concept_primary_texts": _at_most_per_concept(concept_texts, 2)[:16],
        "figures": _normalise_figures(raw_plan.get("figures")),
        "orientation_note": note.strip() if isinstance(note, str) else "",
    }


def _clean_concepts(raw: Any) -> list[str]:
    return (
        [c.strip() for c in raw or [] if isinstance(c, str) and c.strip()]
        if isinstance(raw, list)
        else []
    )


def _normalise_facets(raw_plan: dict, topic: str, max_concepts: int) -> list[dict]:
    """Facets with their concepts, de-duplicated across facets and capped.

    A model that ignores ``facets`` and returns only ``key_concepts`` gets one
    facet named after the topic, and a concept listed in ``key_concepts`` but in
    no facet joins a facet of its own rather than vanishing. The cap trims from
    the largest facet first, so trimming never empties a facet.
    """
    seen: set[str] = set()
    facets: list[dict] = []

    def _take(concepts: list[str]) -> list[str]:
        kept = []
        for concept in concepts:
            if concept.casefold() not in seen:
                seen.add(concept.casefold())
                kept.append(concept)
        return kept

    for raw in raw_plan.get("facets") or [] if isinstance(raw_plan.get("facets"), list) else []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        concepts = _take(_clean_concepts(raw.get("concepts"))[:_MAX_CONCEPTS_PER_FACET])
        if concepts:
            facets.append(
                {
                    "name": name.strip()
                    if isinstance(name, str) and name.strip()
                    else f"Facet {len(facets) + 1}",
                    "concepts": concepts,
                }
            )
        if len(facets) >= _MAX_FACETS:
            break

    orphans = _take(_clean_concepts(raw_plan.get("key_concepts")))
    if orphans:
        facets.append({"name": topic if not facets else "Other", "concepts": orphans})

    limit = max(1, max_concepts)
    while sum(len(f["concepts"]) for f in facets) > limit:
        largest = max(range(len(facets)), key=lambda i: (len(facets[i]["concepts"]), i))
        if len(facets[largest]["concepts"]) > 1:
            facets[largest]["concepts"].pop()
        else:
            facets.pop()
    return facets


def _normalise_figures(raw: Any) -> list[dict]:
    """Up to six named figures, each with one obtainable work or none."""
    figures: list[dict] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip().casefold() in seen:
            continue
        seen.add(name.strip().casefold())
        why = entry.get("why")
        work = _normalise_work(entry["work"]) if isinstance(entry.get("work"), dict) else None
        obtainable = entry.get("obtainable") is True and work is not None
        if work is not None:
            work.pop("substitute", None)
            work["author"] = work["author"] or name.strip()
        figures.append(
            {
                "name": name.strip(),
                "why": why.strip() if isinstance(why, str) else "",
                "work": work if obtainable else None,
                "obtainable": obtainable,
            }
        )
        if len(figures) >= _MAX_FIGURES:
            break
    return figures


def _normalise_work(work: dict, allow_substitute: bool = True) -> dict | None:
    title = work.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    author = work.get("author")
    kind = work.get("kind")
    sections = work.get("sections")
    normalised: dict[str, Any] = {
        "title": title.strip(),
        "author": author.strip() if isinstance(author, str) else "",
        "kind": kind if kind in WORK_KINDS else "book",
        "public_domain": work.get("public_domain") is True,
        "sections": sections.strip() if isinstance(sections, str) else "",
        "open_text": work.get("open_text") is True,
    }
    substitute = work.get("substitute")
    if allow_substitute and isinstance(substitute, dict):
        normalised_substitute = _normalise_work(substitute, allow_substitute=False)
        if normalised_substitute is not None and title_key(
            normalised_substitute["title"]
        ) != title_key(normalised["title"]):
            normalised["substitute"] = normalised_substitute
    return normalised


def _at_most_per_concept(texts: list[dict], limit: int) -> list[dict]:
    counts: dict[str, int] = {}
    kept = []
    for text in texts:
        counts[text["concept"]] = counts.get(text["concept"], 0) + 1
        if counts[text["concept"]] <= limit:
            kept.append(text)
    return kept


def _route_must_have_works(plan: dict) -> None:
    """Add exact-title queries for named works to the fetchers that answer them.

    Works are looked for by the canonical resolver (sources/canonical.py), which
    searches the Gutenberg catalogue, the Internet Archive and Exa by title and
    records whether it found the whole work. What is left for the planned search:

    - **papers** also go to OpenAlex, the scholarly channel, as a title query;
    - **without an Exa key** the resolver's Exa routes cannot run, so every work
      goes to the web fetcher as a quoted title, as before.

    Each extra query gets at least one result slot in the fan-out, so a must-have
    work costs little budget but is actively looked for.
    """
    works = plan["must_have_works"]
    if not works:
        return

    def _add(target: str, selected: list[dict]) -> None:
        queries = [f'"{w["title"]}" {w.get("author", "")}'.strip() for w in selected]
        if not queries:
            return
        fetcher_plan = plan["fetcher_plans"][target]
        existing = {q.casefold() for q in fetcher_plan["queries"]}
        fetcher_plan["queries"] += [q for q in queries if q.casefold() not in existing]
        fetcher_plan["weight"] = max(fetcher_plan["weight"], 1.0)

    if not settings.EXA_API_KEY:
        _add("web", works)
    _add("openalex", [w for w in works if w.get("kind") == "paper"])
