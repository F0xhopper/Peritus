"""The graph vocabulary against a real DB.

Needs PERITUS_TEST_DATABASE_URL (skips otherwise).

Two things are worth pinning here and cannot be pinned in a unit test. The
first is that ingest actually *rejects* — the old schema declared its enums in a
tool definition and enforced none of them, which is how the graph came to hold
`contradicts` edges between two concepts and nodes typed `example`. The second
is the SQL the reconciliation pass runs on: grouping claims by the concept they
are `about`, and counting the sources behind an edge.
"""

import pytest

from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.graph.repository import GraphRepository

pytestmark = pytest.mark.asyncio


async def _expert(pool, name: str):
    return await ExpertRepository(pool).create(
        name=name, topic="beekeeping", tier=ExpertTier.LITE
    )


async def _chunks(pool, expert_id: int, titles: list[str]) -> list[int]:
    """One passing source per title, one chunk each. Returns the chunk ids."""
    chunk_ids = []
    async with pool.acquire() as conn:
        for i, title in enumerate(titles):
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (expert_id, source_type, url, title, passed)
                VALUES ($1, 'web', 'https://e.test/x', $2, true) RETURNING id
                """,
                expert_id, title,
            )
            chunk_ids.append(await conn.fetchval(
                """
                INSERT INTO source_chunks (expert_id, source_id, sequence_n, text)
                VALUES ($1, $2, $3, 'passage') RETURNING id
                """,
                expert_id, source_id, i,
            ))
    return chunk_ids


def _extraction(chunk_id: int, claim: str, edges: list[dict]) -> dict:
    return {
        "nodes": [
            {"label": claim, "node_type": "claim", "description": claim,
             "chunk_db_ids": [chunk_id]},
            {"label": "Varroa destructor", "node_type": "concept",
             "description": "A parasitic mite", "chunk_db_ids": [chunk_id]},
        ],
        "edges": edges,
    }


async def test_ingest_rejects_edges_the_endpoints_do_not_support(db_pool):
    """A `contradicts` between two concepts is a category error, and it was 45%
    of the old graph's contradictions."""
    expert = await _expert(db_pool, "endpoints")
    chunk_id = (await _chunks(db_pool, expert.id, ["A"]))[0]
    repo = GraphRepository(db_pool)

    _, edge_count = await repo.bulk_insert_from_extractions(expert.id, [{
        "nodes": [
            {"label": "Varroa destructor", "node_type": "concept", "description": "mite",
             "chunk_db_ids": [chunk_id]},
            {"label": "Apiary", "node_type": "concept", "description": "yard",
             "chunk_db_ids": [chunk_id]},
            {"label": "Colonies collapse", "node_type": "claim", "description": "c",
             "chunk_db_ids": [chunk_id]},
            {"label": "Leaked", "node_type": "example", "description": "not a node type",
             "chunk_db_ids": [chunk_id]},
        ],
        "edges": [
            # Rejected: concept endpoints on a claim relation.
            {"from_label": "Varroa destructor", "to_label": "Apiary",
             "edge_type": "contradicts"},
            # Rejected: type not in the vocabulary at all.
            {"from_label": "Varroa destructor", "to_label": "Apiary",
             "edge_type": "builds_on"},
            # Rejected: `about` runs claim → concept, not the other way.
            {"from_label": "Varroa destructor", "to_label": "Colonies collapse",
             "edge_type": "about"},
            # Kept.
            {"from_label": "Colonies collapse", "to_label": "Varroa destructor",
             "edge_type": "about"},
            {"from_label": "Apiary", "to_label": "Varroa destructor",
             "edge_type": "part_of"},
        ],
    }])

    assert edge_count == 2
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM expert_nodes WHERE expert_id = $1 AND label = 'Leaked'",
            expert.id,
        ) == 0
        types = [r["edge_type"] for r in await conn.fetch(
            "SELECT edge_type FROM expert_edges WHERE expert_id = $1 ORDER BY edge_type",
            expert.id,
        )]
    assert types == ["about", "part_of"]


async def test_claims_by_concept_groups_across_sources(db_pool):
    expert = await _expert(db_pool, "grouping")
    a, b = await _chunks(db_pool, expert.id, ["Review", "Preprint"])
    repo = GraphRepository(db_pool)

    about = [{"from_label": "Mites suppress immunity", "to_label": "Varroa destructor",
              "edge_type": "about"}]
    await repo.bulk_insert_from_extractions(expert.id, [
        _extraction(a, "Mites suppress immunity", about),
        _extraction(b, "Mites do not suppress immunity", [
            {"from_label": "Mites do not suppress immunity",
             "to_label": "Varroa destructor", "edge_type": "about"},
        ]),
    ])

    groups = await repo.claims_by_concept(expert.id)
    assert len(groups) == 1
    group = groups[0]
    assert group.concept_label == "Varroa destructor"
    assert group.source_count == 2
    assert {c.source_title for c in group.claims} == {"Review", "Preprint"}

    # A concept only one source makes claims about has no cross-source pair to
    # find, so it does not earn a call.
    assert await repo.claims_by_concept(expert.id, min_sources=3) == []


async def test_insert_relations_and_evidence_count(db_pool):
    expert = await _expert(db_pool, "relations")
    a, b = await _chunks(db_pool, expert.id, ["Review", "Preprint"])
    repo = GraphRepository(db_pool)
    await repo.bulk_insert_from_extractions(expert.id, [
        _extraction(a, "Mites suppress immunity", [
            {"from_label": "Mites suppress immunity", "to_label": "Varroa destructor",
             "edge_type": "about"},
        ]),
        _extraction(b, "Mites do not suppress immunity", [
            {"from_label": "Mites do not suppress immunity",
             "to_label": "Varroa destructor", "edge_type": "about"},
        ]),
    ])
    claims = {c.label: c.node_id for g in await repo.claims_by_concept(expert.id)
              for c in g.claims}

    inserted = await repo.insert_relations(expert.id, [
        # Kept, with the point it states.
        {"from_node_id": claims["Mites suppress immunity"],
         "to_node_id": claims["Mites do not suppress immunity"],
         "edge_type": "contradicts",
         "properties": {"point": "whether Varroa alone suppresses immunity"}},
        # Rejected: a contradiction with nothing stated about what is disputed.
        {"from_node_id": claims["Mites do not suppress immunity"],
         "to_node_id": claims["Mites suppress immunity"],
         "edge_type": "contradicts", "properties": {}},
    ])
    assert inserted == 1

    await repo.recompute_edge_evidence(expert.id)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT edge_type, evidence, properties FROM expert_edges
            WHERE expert_id = $1 AND edge_type = 'contradicts'
            """,
            expert.id,
        )
    # Both sides' passages, and they come from two different sources — which is
    # the only kind of contradiction that is a disagreement *between* sources.
    assert row["evidence"] == 2
    assert "whether Varroa alone" in row["properties"]
