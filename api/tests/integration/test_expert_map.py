"""The expert's map against a real DB (docs/plans/expert-brain.md).

Needs PERITUS_TEST_DATABASE_URL (skips otherwise).

The payload's rules are unit-tested in tests/unit/test_expert_map.py; what is
pinned here is the SQL under them — a concept's kept sources read off its
passages, its disputes read off the claims about it, cosine computed in
Postgres for the key-concept join — none of which a mock can check.
"""

import pytest

from peritus.audit.service import AuditService
from peritus.experts.domain import ExpertTier
from peritus.experts.repository import ExpertRepository
from peritus.graph.key_concepts import assign_key_concepts
from peritus.graph.repository import GraphRepository

pytestmark = pytest.mark.asyncio

DIM = 3072


def _unit(axis: int) -> list[float]:
    vector = [0.0] * DIM
    vector[axis] = 1.0
    return vector


async def _seed(pool):
    repo = ExpertRepository(pool)
    expert = await repo.create(name="brain", topic="beekeeping", tier=ExpertTier.LITE)
    await repo.update_key_concepts(expert.id, ["Varroa control", "Hive equipment"])
    async with pool.acquire() as conn:
        await conn.execute("UPDATE experts SET readiness = 'graph_ready' WHERE id = $1", expert.id)
        sources, chunks = [], []
        for i, passed in enumerate([True, True, False]):
            source_id = await conn.fetchval(
                """
                INSERT INTO sources (expert_id, source_type, url, title, passed,
                                     source_tier, covered_concepts, concept_depths)
                VALUES ($1, 'web', 'https://e.test/x', $2, $3, 'primary',
                        '["Varroa control"]', '{"Varroa control": "sets_out"}')
                RETURNING id
                """,
                expert.id,
                f"Source {i}",
                passed,
            )
            sources.append(source_id)
            chunks.append(
                await conn.fetchval(
                    """
                    INSERT INTO source_chunks (expert_id, source_id, sequence_n, text)
                    VALUES ($1, $2, 0, 'passage') RETURNING id
                    """,
                    expert.id,
                    source_id,
                )
            )

        async def node(label, node_type, chunk_ids, axis=None):
            return await conn.fetchval(
                """
                INSERT INTO expert_nodes (expert_id, node_type, label, description,
                                          chunk_ids, embedding)
                VALUES ($1, $2, $3, 'd', $4, $5) RETURNING id
                """,
                expert.id,
                node_type,
                label,
                chunk_ids,
                _unit(axis) if axis is not None else None,
            )

        shared = await node("Oxalic acid", "concept", [chunks[0], chunks[1]], axis=0)
        dropped_only = await node("Only in a dropped source", "concept", [chunks[2]], axis=1)
        single = await node("Langstroth hive", "concept", [chunks[0]], axis=1)
        claim_a = await node("Oxalic acid kills mites.", "claim", [chunks[0]])
        claim_b = await node("Oxalic acid does not kill mites.", "claim", [chunks[1]])

        await conn.executemany(
            """
            INSERT INTO expert_edges (expert_id, from_node_id, to_node_id, edge_type, properties)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            [
                (expert.id, claim_a, shared, "about", "{}"),
                (expert.id, claim_b, shared, "about", "{}"),
                (expert.id, claim_a, claim_b, "contradicts", '{"point": "efficacy"}'),
                (expert.id, single, shared, "part_of", "{}"),
            ],
        )
    fresh = await repo.get_by_id(expert.id)
    assert fresh is not None
    return fresh, sources, {"shared": shared, "dropped": dropped_only, "single": single}


async def test_the_map_reads_sources_off_passages_and_disputes_off_claims(db_pool):
    expert, sources, nodes = await _seed(db_pool)

    body = await AuditService(db_pool).expert_map(expert)

    assert body["computed"] is True
    by_id = {c["id"]: c for c in body["concepts"]}
    # Kept sources only: the dropped source's concept has nothing feeding it.
    assert nodes["dropped"] not in by_id
    assert by_id[nodes["shared"]]["source_ids"] == sources[:2]
    assert by_id[nodes["shared"]]["disputes"] == 1
    # A thin corpus is topped up with the single-source concept.
    assert by_id[nodes["single"]]["topped_up"] is True
    assert body["links"] == [{"from": nodes["single"], "to": nodes["shared"]}]
    assert body["totals"] == {"concepts": 3, "concepts_shown": 2, "claims": 2, "sources": 2}
    assert [s["id"] for s in body["sources"]] == sources[:2]
    assert body["syllabus"]["key_concepts"][0]["sources"] == 2


async def test_one_concept_lists_its_sources_claims_and_the_point_in_dispute(db_pool):
    expert, sources, nodes = await _seed(db_pool)

    detail = await AuditService(db_pool).map_concept(expert, nodes["shared"])

    assert detail is not None
    assert [s["id"] for s in detail["sources"]] == sources[:2]
    assert detail["disputes"] == 2  # both sides of the one disagreement are about it
    first = detail["claims"][0]
    assert first["disputed"] is True
    assert first["relations"][0]["point"] == "efficacy"
    assert first["sources"][0]["chunk_id"] is not None
    assert detail["part_of"] == [
        {"id": nodes["single"], "label": "Langstroth hive", "relation": "part"}
    ]
    # A claim is not a concept, and another expert's node is not this one's.
    assert await AuditService(db_pool).map_concept(expert, first["id"]) is None


async def test_key_concepts_are_assigned_by_cosine_in_postgres(db_pool):
    expert, _sources, nodes = await _seed(db_pool)
    graph = GraphRepository(db_pool)

    async def embedder(texts):
        return [_unit(i) for i in range(len(texts))]

    stats = await assign_key_concepts(graph, expert.id, expert.key_concepts, embedder)

    assert stats.nodes == 3  # concepts with embeddings; claims are never assigned
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, key_concept_idx, key_concept_sim FROM expert_nodes WHERE expert_id = $1",
            expert.id,
        )
    placed = {r["id"]: (r["key_concept_idx"], r["key_concept_sim"]) for r in rows}
    assert placed[nodes["shared"]] == (0, pytest.approx(1.0))
    assert placed[nodes["single"]] == (1, pytest.approx(1.0))

    body = await AuditService(db_pool).expert_map(expert)
    assert {c["id"]: c["key_concept"] for c in body["concepts"]} == {
        nodes["shared"]: 0,
        nodes["single"]: 1,
    }
