"""The expert's map: its syllabus, its concepts and its sources as one payload.

docs/plans/expert-brain.md. The web draws four kinds of thing — the expert at
the centre, its **syllabus** (key concepts grouped by facet) as a fixed ring, the
**concepts** more than one source discusses as a cloud, and its **sources** on
an outer orbit — plus the **gaps**: texts the plan named that the build never
found. Claims are not in it; they are sentences, and they arrive one concept at
a time from :func:`build_concept_detail`.

Pure functions over rows the repository has already read, so every rule here —
which concepts are shown, how a thin corpus is topped up, what a planless expert
gets — is testable without a database.

**Coverage is live.** Counts come from :func:`compute_coverage` over the kept
sources as they are now, not from ``build_summary``, which describes the corpus
the build finished with and goes stale the moment a source is added or removed.
What cannot be recomputed from the database — whether a concept's named text was
found, which needs the fetch metadata the build had — is read from the summary.
"""

from __future__ import annotations

from typing import Any

from peritus.experts.coverage import CoverageTarget, compute_coverage
from peritus.experts.domain import Expert
from peritus.sources.domain import (
    DEPTH_TREATS,
    DEPTHS,
    NAMED_NONE,
    RawSource,
    SourceType,
    ValidatedSource,
)

#: A concept is in the cloud when at least this many kept sources discuss it.
#: One source's vocabulary is not the field's; two is the smallest agreement.
SHARED_MIN_SOURCES = 2
#: A cloud with fewer shared concepts than this is topped up with the busiest
#: single-source ones, drawn faintest. Beekeeping has twenty shared concepts,
#: which is a ring with nothing in it.
TOP_UP_TO = 60
#: The most concepts drawn by default. The paint budget in the plan is set at
#: 250 nodes; past it the cloud is dots again.
DEFAULT_MAX_CONCEPTS = 250
#: The most concepts drawn with a sector expanded.
EXPANDED_MAX_CONCEPTS = 600

GAP_NAMED_TEXT = "named_text"
GAP_MUST_HAVE = "must_have"


def build_map(
    expert: Expert,
    plan: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    concepts: list[dict[str, Any]] | None,
    links: list[dict[str, Any]],
    claims: int,
    target: CoverageTarget,
    expand: int | None = None,
) -> dict[str, Any]:
    """The whole ``GET /experts/{slug}/map`` body.

    ``concepts`` is None while the graph is still being extracted: the syllabus
    and the sources are already true, so they are returned, with ``computed:
    false`` and an empty cloud.
    """
    key_concepts = list(expert.key_concepts or [])
    index_of = {concept: i for i, concept in enumerate(key_concepts)}
    plan = plan or {}

    syllabus = _syllabus(expert, plan, key_concepts, index_of, sources, target)
    map_sources = [_map_source(s, index_of) for s in sources]

    computed = concepts is not None
    shown: list[dict[str, Any]] = []
    if concepts is not None:
        shown = select_concepts(concepts, len(key_concepts), expand)
    shown_ids = {c["id"] for c in shown}

    return {
        "expert": {"slug": expert.name, "topic": expert.topic},
        "computed": computed,
        "syllabus": syllabus,
        "sources": map_sources,
        "concepts": shown,
        "links": [
            {"from": link["from_node_id"], "to": link["to_node_id"]}
            for link in links
            if link["from_node_id"] in shown_ids and link["to_node_id"] in shown_ids
        ],
        "totals": {
            "concepts": len(concepts) if concepts is not None else None,
            "concepts_shown": len(shown),
            "claims": claims if computed else None,
            "sources": len(sources),
        },
        "expanded": expand if computed else None,
    }


def select_concepts(
    concepts: list[dict[str, Any]], key_concept_count: int, expand: int | None = None
) -> list[dict[str, Any]]:
    """Which concept nodes the cloud draws, in a stable order.

    Every concept at least :data:`SHARED_MIN_SOURCES` kept sources discuss; if
    that is fewer than :data:`TOP_UP_TO`, topped up with the busiest
    single-source concepts (``topped_up``); capped at
    :data:`DEFAULT_MAX_CONCEPTS`, most-sourced first. ``expand`` adds every
    concept in that key concept's sector, up to :data:`EXPANDED_MAX_CONCEPTS`.
    A concept with no kept source is never drawn — nothing on the orbit feeds it.
    """
    rows = [_map_concept(c, key_concept_count) for c in concepts if c.get("source_ids")]
    rank = sorted(rows, key=lambda c: (-len(c["source_ids"]), -c["degree"], c["id"]))

    shared = [c for c in rank if len(c["source_ids"]) >= SHARED_MIN_SOURCES]
    picked = shared[:DEFAULT_MAX_CONCEPTS]
    if len(picked) < TOP_UP_TO:
        single = sorted(
            (c for c in rank if len(c["source_ids"]) < SHARED_MIN_SOURCES),
            key=lambda c: (-c["degree"], c["id"]),
        )
        for concept in single[: TOP_UP_TO - len(picked)]:
            picked.append({**concept, "topped_up": True})

    if expand is not None and 0 <= expand < key_concept_count:
        have = {c["id"] for c in picked}
        for concept in rank:
            if len(picked) >= EXPANDED_MAX_CONCEPTS:
                break
            if concept["key_concept"] == expand and concept["id"] not in have:
                picked.append(
                    {**concept, "topped_up": len(concept["source_ids"]) < SHARED_MIN_SOURCES}
                )
                have.add(concept["id"])

    return sorted(picked, key=lambda c: c["id"])


def _map_concept(row: dict[str, Any], key_concept_count: int) -> dict[str, Any]:
    index = row.get("key_concept_idx")
    return {
        "id": row["id"],
        "label": row["label"],
        # An index past the end belongs to a plan that has since been rewritten;
        # it points at nothing, so the concept is unassigned rather than
        # misplaced.
        "key_concept": index if index is not None and 0 <= index < key_concept_count else None,
        "source_ids": sorted(set(row.get("source_ids") or [])),
        "degree": int(row.get("degree") or 0),
        "disputes": int(row.get("disputes") or 0),
        "topped_up": False,
    }


def _map_source(row: dict[str, Any], index_of: dict[str, int]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row.get("author"),
        "kind": row["source_type"],
        "tier": row.get("source_tier"),
        "passage_count": int(row.get("passage_count") or 0),
        "tags": [
            {"key_concept": index_of[concept], "depth": depth}
            for concept, depth in _tags(row)
            if concept in index_of
        ],
    }


def _tags(row: dict[str, Any]) -> list[tuple[str, str]]:
    """Every graded tag, mentions included; a pre-grading source's flat tags as ``treats``."""
    depths = row.get("concept_depths")
    if isinstance(depths, dict) and depths:
        tags = [(str(c), str(d)) for c, d in depths.items() if d in DEPTHS]
    else:
        tags = [(str(c), DEPTH_TREATS) for c in row.get("covered_concepts") or []]
    return sorted(dict(tags).items(), key=lambda tag: (DEPTHS.index(tag[1]), tag[0]))


def _syllabus(
    expert: Expert,
    plan: dict[str, Any],
    key_concepts: list[str],
    index_of: dict[str, int],
    sources: list[dict[str, Any]],
    target: CoverageTarget,
) -> dict[str, Any]:
    summary = expert.build_summary or {}
    measured = {
        str(c.get("concept")): c
        for c in (summary.get("coverage") or {}).get("concepts") or []
        if isinstance(c, dict)
    }
    named_status = {
        concept: str(c.get("named_text"))
        for concept, c in measured.items()
        if c.get("named_text") and c.get("named_text") != NAMED_NONE
    }
    named_works = _named_works(plan)

    facets_raw = [f for f in plan.get("facets") or [] if isinstance(f, dict)]
    coverage = compute_coverage(
        key_concepts,
        [_validated(s) for s in sources],
        target,
        facets=facets_raw or None,
        named_texts=named_status,
    )
    by_concept = {c.concept: c for c in coverage.concepts}

    facets: list[dict[str, Any]] | None = None
    facet_of: dict[int, str] = {}
    if facets_raw:
        facets = []
        for facet in facets_raw:
            members = [index_of[c] for c in facet.get("concepts") or [] if c in index_of]
            members = [i for i in members if i not in facet_of]
            if not members:
                continue
            name = str(facet.get("name") or "")
            for i in members:
                facet_of[i] = name
            facets.append({"name": name, "concepts": members})
        facets = facets or None

    key_concept_rows = []
    for i, concept in enumerate(key_concepts):
        report = by_concept[concept]
        status = named_status.get(concept)
        work = named_works.get(concept)
        key_concept_rows.append(
            {
                "index": i,
                "label": concept,
                "facet": facet_of.get(i),
                "sources": report.sources,
                "depth_counts": dict(report.depth_counts),
                "met": report.met,
                "named_text": (
                    {
                        "status": status,
                        "title": work["title"] if work else None,
                        "author": work["author"] if work else None,
                    }
                    if status
                    else None
                ),
            }
        )

    return {
        "facets": facets,
        "key_concepts": key_concept_rows,
        "gaps": _gaps(summary, named_status, named_works, index_of),
    }


def _named_works(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Concept → the primary text the plan named for it (the first, if several)."""
    works: dict[str, dict[str, Any]] = {}
    for entry in plan.get("concept_primary_texts") or []:
        if not isinstance(entry, dict) or not entry.get("concept") or not entry.get("title"):
            continue
        works.setdefault(
            str(entry["concept"]),
            {"title": str(entry["title"]), "author": entry.get("author") or None},
        )
    return works


def _gaps(
    summary: dict[str, Any],
    named_status: dict[str, str],
    named_works: dict[str, dict[str, Any]],
    index_of: dict[str, int],
) -> list[dict[str, Any]]:
    """Named texts and must-have works the build looked for and did not find.

    A concept's named text is a gap when its status is ``missing``. A must-have
    work is one when the resolver reported ``not_found``; it sits at its first
    concept's angle, or at the foot of the orbit when it names none. The same
    title is never a gap twice.
    """
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for concept, status in named_status.items():
        if status != "missing" or concept not in index_of:
            continue
        work = named_works.get(concept)
        if work is None:
            continue
        seen.add(work["title"].casefold())
        gaps.append(
            {
                "key_concept": index_of[concept],
                "title": work["title"],
                "author": work["author"],
                "kind": GAP_NAMED_TEXT,
            }
        )
    for entry in (summary.get("corpus") or {}).get("must_have") or []:
        if not isinstance(entry, dict) or entry.get("status") != "not_found":
            continue
        title = str(entry.get("title") or "")
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        first = next((c for c in entry.get("concepts") or [] if c in index_of), None)
        gaps.append(
            {
                "key_concept": index_of[first] if first is not None else None,
                "title": title,
                "author": entry.get("author") or None,
                "kind": GAP_MUST_HAVE,
            }
        )
    return gaps


def _validated(row: dict[str, Any]) -> ValidatedSource:
    """A kept source as coverage reads it. Only the fields coverage looks at are real."""
    try:
        source_type = SourceType(row["source_type"])
    except ValueError:
        source_type = SourceType.WEB
    depths = row.get("concept_depths")
    return ValidatedSource(
        raw=RawSource(
            source_type=source_type,
            url=row.get("url") or "",
            title=row.get("title") or "",
            author=row.get("author"),
            text="",
        ),
        quality_score=float(row.get("quality_score") or 0.0),
        relevance_score=float(row.get("relevance_score") or 0.0),
        content_type="",
        difficulty=0,
        key_claims=[],
        covered_concepts=list(row.get("covered_concepts") or []),
        source_tier=row.get("source_tier"),
        substance=row.get("substance"),
        concept_depths=dict(depths) if isinstance(depths, dict) else {},
    )


# ── one concept ─────────────────────────────────────────────────────────────


def build_concept_detail(detail: dict[str, Any], key_concept_count: int) -> dict[str, Any]:
    """The concept panel: description, its sources, its claims with their relations.

    Claims come with every kept source whose passage states them (``cited``,
    each with the first such passage, which the passage reader opens), and with
    the claim-to-claim relations that touch them. Disputes come first: where
    sources in this corpus were judged to disagree is the most checkable thing
    the graph knows, and ``point`` — required on every ``contradicts`` edge — is
    what makes it checkable.
    """
    node = detail["node"]
    source_title = {s["id"]: s["title"] for s in detail["sources"]}
    claim_ids = {c["id"] for c in detail["claims"]}

    relations_by_claim: dict[int, list[dict[str, Any]]] = {}
    for rel in detail["relations"]:
        props = rel.get("properties") or {}
        for mine, other, other_label in (
            (rel["from_node_id"], rel["to_node_id"], rel["to_label"]),
            (rel["to_node_id"], rel["from_node_id"], rel["from_label"]),
        ):
            if mine not in claim_ids:
                continue
            relations_by_claim.setdefault(mine, []).append(
                {
                    "type": rel["edge_type"],
                    "claim_id": other,
                    "text": other_label,
                    "point": props.get("point") or None,
                    "condition": props.get("condition") or None,
                }
            )

    claims = []
    for claim in detail["claims"]:
        relations = relations_by_claim.get(claim["id"], [])
        claims.append(
            {
                "id": claim["id"],
                "text": claim["label"],
                "sources": [
                    {
                        "source_id": cited["source_id"],
                        "title": source_title.get(cited["source_id"]),
                        "chunk_id": cited["chunk_id"],
                    }
                    for cited in claim.get("cited") or []
                    if cited and cited.get("source_id") is not None
                ],
                "relations": relations,
                "disputed": any(r["type"] == "contradicts" for r in relations),
            }
        )
    claims.sort(key=lambda c: (not c["disputed"], -len(c["sources"]), c["id"]))

    index = node.get("key_concept_idx")
    return {
        "id": node["id"],
        "label": node["label"],
        "description": node.get("description") or None,
        "key_concept": index if index is not None and 0 <= index < key_concept_count else None,
        "sources": [
            {
                "id": s["id"],
                "title": s["title"],
                "author": s.get("author"),
                "kind": s["source_type"],
                "tier": s.get("source_tier"),
                "passages": s["passages"],
                "chunk_id": s["chunk_id"],
            }
            for s in detail["sources"]
        ],
        "claims": claims,
        "disputes": sum(1 for c in claims if c["disputed"]),
        "part_of": [
            {
                "id": p["other_id"],
                "label": p["other_label"],
                # `part_of` points from the part to the whole.
                "relation": "whole" if p["from_node_id"] == node["id"] else "part",
            }
            for p in detail["part_of"]
        ],
    }
