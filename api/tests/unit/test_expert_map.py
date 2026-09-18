"""The expert's map payload (docs/plans/expert-brain.md, phase 1).

Pure functions over repository rows, so each rule the web draws from is pinned
here: which concepts reach the cloud, how a thin corpus is topped up, what a
planless expert and a still-extracting expert get, and where gaps come from.
"""

from datetime import UTC, datetime

from peritus.audit.expert_map import (
    DEFAULT_MAX_CONCEPTS,
    EXPANDED_MAX_CONCEPTS,
    TOP_UP_TO,
    build_concept_detail,
    build_map,
    select_concepts,
)
from peritus.experts.domain import Expert, ExpertConfig, ExpertStatus, ExpertTier

KEY_CONCEPTS = ["Being and essence", "Analogy", "Five Ways"]


def _expert(key_concepts=KEY_CONCEPTS, build_summary=None) -> Expert:
    return Expert(
        id=1,
        name="thomism",
        topic="Thomism",
        status=ExpertStatus.READY,
        tier=ExpertTier.STANDARD,
        config=ExpertConfig.from_tier(ExpertTier.STANDARD),
        key_concepts=list(key_concepts),
        build_summary=build_summary,
        readiness="graph_ready",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _source(id, tier="primary", depths=None, covered=None, source_type="gutenberg"):
    return {
        "id": id,
        "title": f"Source {id}",
        "author": None,
        "url": f"https://example.org/{id}",
        "source_type": source_type,
        "source_tier": tier,
        "substance": None,
        "quality_score": 8.0,
        "relevance_score": 8.0,
        "covered_concepts": covered or [],
        "concept_depths": depths,
        "passage_count": 10,
    }


def _concept(id, sources, key_concept=None, degree=1, disputes=0):
    return {
        "id": id,
        "label": f"Concept {id}",
        "key_concept_idx": key_concept,
        "source_ids": sources,
        "degree": degree,
        "disputes": disputes,
    }


def _target():
    return ExpertConfig.from_tier(ExpertTier.STANDARD).coverage_target()


# ── which concepts are drawn ────────────────────────────────────────────────


def test_shared_concepts_are_drawn_and_a_thin_cloud_is_topped_up_with_the_busiest():
    concepts = [_concept(1, [10, 11]), _concept(2, [10, 11, 12])]
    concepts += [_concept(100 + i, [10], degree=i) for i in range(100)]

    shown = select_concepts(concepts, 3)

    assert len(shown) == TOP_UP_TO
    by_id = {c["id"]: c for c in shown}
    assert not by_id[1]["topped_up"] and not by_id[2]["topped_up"]
    topped = [c for c in shown if c["topped_up"]]
    assert len(topped) == TOP_UP_TO - 2
    # The busiest single-source concepts, not the first ones in id order.
    assert min(c["degree"] for c in topped) == 100 - len(topped)


def test_a_rich_cloud_is_not_topped_up_and_is_capped():
    concepts = [_concept(i, [10, 11]) for i in range(DEFAULT_MAX_CONCEPTS + 40)]
    concepts.append(_concept(9999, [10], degree=500))
    shown = select_concepts(concepts, 3)
    assert len(shown) == DEFAULT_MAX_CONCEPTS
    assert all(not c["topped_up"] for c in shown)


def test_a_concept_no_kept_source_discusses_is_never_drawn():
    """A removed source leaves its nodes behind; they must not linger as orphans."""
    shown = select_concepts([_concept(1, []), _concept(2, [10, 11])], 3)
    assert [c["id"] for c in shown] == [2]


def test_expanding_a_sector_adds_everything_in_it_up_to_the_cap():
    concepts = [_concept(i, [10, 11]) for i in range(70)]
    concepts += [_concept(1000 + i, [10], key_concept=2) for i in range(800)]
    concepts += [_concept(5000 + i, [10], key_concept=1) for i in range(20)]

    shown = select_concepts(concepts, 3, expand=2)

    assert len(shown) == EXPANDED_MAX_CONCEPTS
    assert not any(c["key_concept"] == 1 for c in shown)


def test_a_key_concept_index_past_the_plan_is_unassigned_not_misplaced():
    shown = select_concepts([_concept(1, [10, 11], key_concept=7)], 3)
    assert shown[0]["key_concept"] is None


# ── the whole payload ───────────────────────────────────────────────────────


def test_an_expert_still_extracting_gets_its_syllabus_and_sources_and_no_cloud():
    body = build_map(
        _expert(),
        None,
        [_source(10, covered=["Analogy"])],
        None,
        [],
        0,
        _target(),
    )
    assert body["computed"] is False
    assert body["concepts"] == [] and body["links"] == []
    assert body["totals"]["concepts"] is None  # not recorded, not zero
    assert body["totals"]["claims"] is None
    assert len(body["syllabus"]["key_concepts"]) == 3
    assert body["sources"][0]["tags"] == [{"key_concept": 1, "depth": "treats"}]


def test_a_planless_expert_has_no_facets_no_gaps_and_flat_tags_read_as_treats():
    body = build_map(
        _expert(),
        None,
        [_source(10, covered=["Being and essence", "Five Ways", "Not on the plan"])],
        [_concept(1, [10, 11], key_concept=0)],
        [],
        4,
        _target(),
    )
    syllabus = body["syllabus"]
    assert syllabus["facets"] is None
    assert syllabus["gaps"] == []
    assert all(k["facet"] is None and k["named_text"] is None for k in syllabus["key_concepts"])
    # Off-plan tags are dropped; the two on the plan read as `treats`.
    assert body["sources"][0]["tags"] == [
        {"key_concept": 0, "depth": "treats"},
        {"key_concept": 2, "depth": "treats"},
    ]


def test_coverage_is_live_from_the_kept_sources_not_the_build_summary():
    summary = {"coverage": {"concepts": [{"concept": "Analogy", "sources": 99}]}}
    body = build_map(
        _expert(build_summary=summary),
        None,
        [
            _source(10, depths={"Analogy": "sets_out"}),
            _source(11, depths={"Analogy": "treats", "Five Ways": "mentions"}),
        ],
        [],
        [],
        0,
        _target(),
    )
    analogy = body["syllabus"]["key_concepts"][1]
    assert analogy["sources"] == 2
    assert analogy["depth_counts"] == {"sets_out": 1, "treats": 1}
    # A mention is drawn as a tag but never counts toward coverage.
    assert body["syllabus"]["key_concepts"][2]["sources"] == 0
    assert {"key_concept": 2, "depth": "mentions"} in body["sources"][1]["tags"]


def test_facets_named_texts_and_gaps_come_from_the_plan_and_the_summary():
    plan = {
        "facets": [
            {"name": "Metaphysics", "concepts": ["Being and essence", "Analogy"]},
            {"name": "Natural theology", "concepts": ["Five Ways", "Not a key concept"]},
        ],
        "concept_primary_texts": [
            {"concept": "Being and essence", "title": "On Being and Essence", "author": "Aquinas"},
            {"concept": "Five Ways", "title": "Summa Theologiae", "author": "Aquinas"},
        ],
    }
    summary = {
        "coverage": {
            "concepts": [
                {"concept": "Being and essence", "named_text": "missing"},
                {"concept": "Five Ways", "named_text": "found"},
                {"concept": "Analogy", "named_text": "none_named"},
            ]
        },
        "corpus": {
            "must_have": [
                {"title": "Summa Contra Gentiles", "status": "not_found", "concepts": ["Analogy"]},
                {"title": "On Being and Essence", "status": "not_found", "concepts": []},
                {"title": "Aeterni Patris", "status": "found_whole", "concepts": []},
                {"title": "Degrees of Knowledge", "status": "not_found", "concepts": []},
            ]
        },
    }
    body = build_map(_expert(build_summary=summary), plan, [], [], [], 0, _target())
    syllabus = body["syllabus"]

    assert syllabus["facets"] == [
        {"name": "Metaphysics", "concepts": [0, 1]},
        {"name": "Natural theology", "concepts": [2]},
    ]
    being, analogy, five = syllabus["key_concepts"]
    assert being["facet"] == "Metaphysics"
    assert being["named_text"] == {
        "status": "missing",
        "title": "On Being and Essence",
        "author": "Aquinas",
    }
    assert five["named_text"]["status"] == "found"
    assert analogy["named_text"] is None
    # The named text first; each missing title once; a work with no concept at the foot.
    assert syllabus["gaps"] == [
        {
            "key_concept": 0,
            "title": "On Being and Essence",
            "author": "Aquinas",
            "kind": "named_text",
        },
        {
            "key_concept": 1,
            "title": "Summa Contra Gentiles",
            "author": None,
            "kind": "must_have",
        },
        {
            "key_concept": None,
            "title": "Degrees of Knowledge",
            "author": None,
            "kind": "must_have",
        },
    ]


def test_links_are_part_of_between_drawn_concepts_only():
    concepts = [_concept(1, [10, 11]), _concept(2, [10, 11]), _concept(3, [])]
    links = [
        {"from_node_id": 1, "to_node_id": 2},
        {"from_node_id": 1, "to_node_id": 3},
    ]
    body = build_map(_expert(), None, [], concepts, links, 0, _target())
    assert body["links"] == [{"from": 1, "to": 2}]


# ── one concept ─────────────────────────────────────────────────────────────


def test_a_concepts_claims_carry_their_sources_and_disputes_come_first():
    detail = {
        "node": {
            "id": 1,
            "label": "Divine simplicity",
            "description": "God is not composed.",
            "key_concept_idx": 2,
            "chunk_ids": [100, 101],
        },
        "sources": [
            {
                "id": 10,
                "title": "Summa",
                "author": "Aquinas",
                "source_type": "gutenberg",
                "source_tier": "primary",
                "passages": 2,
                "chunk_id": 100,
            }
        ],
        "claims": [
            {"id": 50, "label": "God has no parts.", "cited": [{"source_id": 10, "chunk_id": 100}]},
            {
                "id": 51,
                "label": "God has attributes.",
                "cited": [{"source_id": 11, "chunk_id": 200}],
            },
        ],
        "relations": [
            {
                "from_node_id": 51,
                "to_node_id": 99,
                "edge_type": "contradicts",
                "properties": {"point": "whether attributes are parts"},
                "from_label": "God has attributes.",
                "to_label": "Attributes are distinct in God.",
            }
        ],
        "part_of": [{"from_node_id": 1, "to_node_id": 7, "other_id": 7, "other_label": "God"}],
    }

    body = build_concept_detail(detail, 3)

    assert body["key_concept"] == 2
    assert [c["id"] for c in body["claims"]] == [51, 50]
    disputed = body["claims"][0]
    assert disputed["disputed"] is True
    assert disputed["relations"] == [
        {
            "type": "contradicts",
            "claim_id": 99,
            "text": "Attributes are distinct in God.",
            "point": "whether attributes are parts",
            "condition": None,
        }
    ]
    assert body["claims"][1]["sources"] == [{"source_id": 10, "title": "Summa", "chunk_id": 100}]
    assert body["disputes"] == 1
    assert body["part_of"] == [{"id": 7, "label": "God", "relation": "whole"}]
