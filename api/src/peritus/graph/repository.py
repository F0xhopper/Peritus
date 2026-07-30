import json
from collections.abc import Awaitable, Callable

import asyncpg

from peritus.core.logging import get_logger

logger = get_logger(__name__)

# Async callback that turns node texts into embedding vectors (e.g. embed_batch).
Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

_NODE_PROPERTY_KEYS = ("difficulty", "content_type", "confidence")


def node_embedding_text(label: str, description: str | None) -> str:
    """Text embedded for a node — label plus description so homonyms disambiguate."""
    return f"{label}: {description}" if description else label


def merge_node_extractions(extractions: list[dict]) -> dict[str, dict]:
    """Merge raw extraction batches into one node per normalised label.

    Keeps the longest description and the first non-null value for each
    property; chunk ids are unioned. Pure function so the merge policy is
    testable without a database.
    """
    merged: dict[str, dict] = {}
    for ext in extractions:
        for node in ext.get("nodes", []):
            if not node.get("label"):
                logger.warning("Skipping node with no label: %r", node)
                continue
            key = node["label"].lower().strip()
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "label": node["label"],
                    "node_type": node.get("node_type", "concept"),
                    "description": node.get("description", ""),
                    "properties": {k: node.get(k) for k in _NODE_PROPERTY_KEYS},
                    "chunk_ids": list(node.get("chunk_db_ids", [])),
                }
                continue
            desc = node.get("description", "")
            if len(desc) > len(existing["description"]):
                existing["description"] = desc
            for k in _NODE_PROPERTY_KEYS:
                if existing["properties"].get(k) is None:
                    existing["properties"][k] = node.get(k)
            existing["chunk_ids"].extend(node.get("chunk_db_ids", []))
    return merged


class GraphRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def bulk_insert_from_extractions(
        self,
        expert_id: int,
        extractions: list[dict],
        embedder: Embedder | None = None,
    ) -> tuple[int, int]:
        """Ingest a list of raw extraction dicts. Returns (node_count, edge_count).

        Nodes are resolved by normalised label, both across the supplied
        extraction batches and against the expert's existing nodes, so this is
        safe to call repeatedly on a live graph: a concept already present is
        deepened (chunk evidence unioned, longest description kept) rather than
        duplicated. The counts returned are nodes and relations *touched*, which
        for a first build is also the number created.

        When ``embedder`` is provided, node embeddings are computed once here and
        persisted so entity resolution and future semantic node search can reuse
        them. Embedding failure degrades to inserting without vectors.
        """
        merged_nodes = merge_node_extractions(extractions)

        embeddings: list[list[float]] | None = None
        if embedder is not None and merged_nodes:
            texts = [
                node_embedding_text(n["label"], n["description"])
                for n in merged_nodes.values()
            ]
            try:
                embeddings = await embedder(texts)
            except Exception as exc:
                logger.warning("Node embedding failed, inserting without vectors: %s", exc)

        # Vector codecs are installed once per connection by the pool's init
        # callback (infrastructure.database), not per call.
        async with self._pool.acquire() as conn, conn.transaction():
            # Resolve each extracted label against the nodes this expert already
            # has. Without this, ingesting into a live graph (a source upload, or
            # any second extraction pass) creates a rival copy of every concept
            # the corpus already covers instead of deepening the existing one —
            # and only the build pipeline runs the embedding-similarity cleanup
            # afterwards, so the upload path accumulated duplicates permanently.
            existing = await conn.fetch(
                "SELECT id, lower(btrim(label)) AS key FROM expert_nodes WHERE expert_id = $1",
                expert_id,
            )
            existing_ids = {r["key"]: r["id"] for r in existing}

            label_to_id: dict[str, int] = {}
            for i, (key, node) in enumerate(merged_nodes.items()):
                embedding = embeddings[i] if embeddings else None
                chunk_ids = list(set(node["chunk_ids"]))
                node_id = existing_ids.get(key)
                if node_id is None:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO expert_nodes
                            (expert_id, node_type, label, description,
                             properties, chunk_ids, embedding)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                        RETURNING id
                        """,
                        expert_id,
                        node["node_type"],
                        node["label"],
                        node["description"],
                        json.dumps(node["properties"]),
                        chunk_ids,
                        embedding,
                    )
                    node_id = row["id"]
                else:
                    # Union the chunk evidence and keep the longer description —
                    # the same policy `merge_node_extractions` applies in memory.
                    # A re-extraction that produced no embedding must not blank
                    # the one already stored.
                    await conn.execute(
                        """
                        UPDATE expert_nodes
                        SET chunk_ids = ARRAY(
                                SELECT DISTINCT x FROM unnest(chunk_ids || $2::integer[]) x
                            ),
                            description = CASE
                                WHEN length($3) > length(coalesce(description, ''))
                                THEN $3 ELSE description
                            END,
                            properties = coalesce(properties, '{}'::jsonb) || $4::jsonb,
                            embedding = coalesce($5, embedding)
                        WHERE id = $1
                        """,
                        node_id,
                        chunk_ids,
                        node["description"],
                        json.dumps({
                            k: v for k, v in node["properties"].items() if v is not None
                        }),
                        embedding,
                    )
                label_to_id[key] = node_id

            # Resolve every edge to node ids first, then write them in one
            # round trip. Duplicates across batches collapse onto the unique
            # relation, keeping the strongest weight.
            strongest: dict[tuple[int, int, str], float] = {}
            for ext in extractions:
                for edge in ext.get("edges", []):
                    if not edge.get("from_label") or not edge.get("to_label"):
                        logger.warning("Skipping edge with missing label: %r", edge)
                        continue
                    from_id = label_to_id.get(edge["from_label"].lower().strip())
                    to_id = label_to_id.get(edge["to_label"].lower().strip())
                    # An edge naming a node no extraction produced, or a
                    # self-loop, carries no information.
                    if from_id is None or to_id is None or from_id == to_id:
                        continue
                    weight = min(max(float(edge.get("weight", 1.0)), 0.0), 1.0)
                    relation = (from_id, to_id, edge.get("edge_type", "builds_on"))
                    strongest[relation] = max(weight, strongest.get(relation, 0.0))

            if strongest:
                await conn.executemany(
                    """
                    INSERT INTO expert_edges
                        (expert_id, from_node_id, to_node_id, edge_type, weight)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (expert_id, from_node_id, to_node_id, edge_type)
                    DO UPDATE SET weight = GREATEST(expert_edges.weight, EXCLUDED.weight)
                    """,
                    [
                        (expert_id, from_id, to_id, edge_type, weight)
                        for (from_id, to_id, edge_type), weight in strongest.items()
                    ],
                )

        return len(merged_nodes), len(strongest)

    async def get_top_nodes(self, expert_id: int, limit: int = 20) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT n.id, n.label, n.node_type, n.description,
                       COUNT(e.id) AS degree
                FROM expert_nodes n
                LEFT JOIN expert_edges e
                    ON e.from_node_id = n.id OR e.to_node_id = n.id
                WHERE n.expert_id = $1
                GROUP BY n.id, n.label, n.node_type, n.description
                ORDER BY degree DESC
                LIMIT $2
                """,
                expert_id, limit,
            )
        return [dict(r) for r in rows]

    async def get_all_nodes(self, expert_id: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, label, description, chunk_ids, embedding
                FROM expert_nodes WHERE expert_id = $1
                """,
                expert_id,
            )
        return [dict(r) for r in rows]

    async def merge_nodes(self, expert_id: int, keep_id: int, drop_id: int) -> None:
        """Redirect all edges from drop_id to keep_id, merge chunk_ids, delete drop_id."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE expert_nodes
                SET chunk_ids = ARRAY(
                    SELECT DISTINCT x FROM unnest(
                        chunk_ids || (SELECT chunk_ids FROM expert_nodes WHERE id = $2)
                    ) x
                )
                WHERE id = $1
                """,
                keep_id, drop_id,
            )
            # Redirecting can collide with an existing (from, to, type) relation,
            # so drop the redundant rows first, then redirect the rest.
            await conn.execute(
                """
                DELETE FROM expert_edges e1
                USING expert_edges e2
                WHERE e1.expert_id = $3 AND e2.expert_id = $3
                  AND e1.from_node_id = $2 AND e2.from_node_id = $1
                  AND e1.to_node_id = e2.to_node_id
                  AND e1.edge_type = e2.edge_type
                """,
                keep_id, drop_id, expert_id,
            )
            await conn.execute(
                """
                DELETE FROM expert_edges e1
                USING expert_edges e2
                WHERE e1.expert_id = $3 AND e2.expert_id = $3
                  AND e1.to_node_id = $2 AND e2.to_node_id = $1
                  AND e1.from_node_id = e2.from_node_id
                  AND e1.edge_type = e2.edge_type
                """,
                keep_id, drop_id, expert_id,
            )
            await conn.execute(
                "UPDATE expert_edges SET from_node_id = $1 WHERE from_node_id = $2 AND expert_id = $3",
                keep_id, drop_id, expert_id,
            )
            await conn.execute(
                "UPDATE expert_edges SET to_node_id = $1 WHERE to_node_id = $2 AND expert_id = $3",
                keep_id, drop_id, expert_id,
            )
            await conn.execute(
                "DELETE FROM expert_edges WHERE from_node_id = to_node_id AND expert_id = $1",
                expert_id,
            )
            await conn.execute("DELETE FROM expert_nodes WHERE id = $1", drop_id)

    async def get_nodes_for_chunks(
        self, expert_id: int, chunk_ids: list[int]
    ) -> list[dict]:
        if not chunk_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, label, node_type, description, chunk_ids
                FROM expert_nodes
                WHERE expert_id = $1
                  AND chunk_ids && $2::integer[]
                """,
                expert_id, chunk_ids,
            )
        return [dict(r) for r in rows]

    async def get_neighbours(
        self,
        expert_id: int,
        node_ids: list[int],
        hops: int = 1,
        max_new_per_hop: int = 50,
    ) -> tuple[list[dict], list[dict]]:
        """Return (nodes, edges) reachable within `hops` from node_ids.

        Expansion is capped per hop, preferring the strongest edges, so a hub
        node cannot pull the whole graph into the context window.
        """
        if not node_ids:
            return [], []

        async with self._pool.acquire() as conn:
            visited_ids = set(node_ids)
            frontier = list(node_ids)

            for _ in range(hops):
                edge_rows = await conn.fetch(
                    """
                    SELECT from_node_id, to_node_id, edge_type, weight
                    FROM expert_edges
                    WHERE expert_id = $1
                      AND (from_node_id = ANY($2) OR to_node_id = ANY($2))
                    ORDER BY weight DESC
                    """,
                    expert_id, frontier,
                )
                new_ids: list[int] = []
                for r in edge_rows:
                    if len(new_ids) >= max_new_per_hop:
                        break
                    for nid in (r["from_node_id"], r["to_node_id"]):
                        if nid not in visited_ids:
                            visited_ids.add(nid)
                            new_ids.append(nid)
                frontier = new_ids
                if not frontier:
                    break

            all_node_ids = list(visited_ids)
            node_rows = await conn.fetch(
                """
                SELECT id, label, node_type, description
                FROM expert_nodes WHERE expert_id = $1 AND id = ANY($2)
                """,
                expert_id, all_node_ids,
            )
            edge_rows = await conn.fetch(
                """
                SELECT from_node_id, to_node_id, edge_type, weight
                FROM expert_edges
                WHERE expert_id = $1
                  AND from_node_id = ANY($2)
                  AND to_node_id = ANY($2)
                """,
                expert_id, all_node_ids,
            )

        return [dict(r) for r in node_rows], [dict(r) for r in edge_rows]
