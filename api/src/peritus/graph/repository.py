import json
from collections import Counter
from collections.abc import Awaitable, Callable

import asyncpg

from peritus.core.logging import get_logger
from peritus.graph.domain import (
    CONTENT_TYPES,
    EDGE_REQUIRED_PROPERTY,
    NodeType,
    coerce_edge_type,
    coerce_node_type,
    edge_is_valid,
)
from peritus.graph.reconciler import ClaimRow, ConceptClaims

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

    A node whose ``node_type`` is not in the enum is dropped, not coerced. The
    tool schema has always declared the enum and nothing enforced it, which is
    how the graph came to hold nodes typed `definition`, `example` and
    `argument` — and how `content_type` came to hold *edge* type names. A wrong
    type is worse than a missing node: every endpoint rule below is stated in
    terms of it.
    """
    merged: dict[str, dict] = {}
    for ext in extractions:
        for node in ext.get("nodes", []):
            if not node.get("label"):
                logger.warning("Skipping node with no label: %r", node)
                continue
            node_type = coerce_node_type(node.get("node_type"))
            if node_type is None:
                logger.debug(
                    "Rejecting node %r: node_type %r is not in the schema",
                    node.get("label"),
                    node.get("node_type"),
                )
                continue
            key = node["label"].lower().strip()
            existing = merged.get(key)
            if existing is None:
                properties = {k: node.get(k) for k in _NODE_PROPERTY_KEYS}
                if properties.get("content_type") not in CONTENT_TYPES:
                    properties["content_type"] = None
                merged[key] = {
                    "label": node["label"],
                    "node_type": str(node_type),
                    "description": node.get("description", ""),
                    "properties": properties,
                    "chunk_ids": list(node.get("chunk_db_ids", [])),
                }
                continue
            desc = node.get("description", "")
            if len(desc) > len(existing["description"]):
                existing["description"] = desc
            for k in _NODE_PROPERTY_KEYS:
                value = node.get(k)
                if k == "content_type" and value not in CONTENT_TYPES:
                    continue
                if existing["properties"].get(k) is None:
                    existing["properties"][k] = value
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
                node_embedding_text(n["label"], n["description"]) for n in merged_nodes.values()
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
                """
                SELECT id, node_type, lower(btrim(label)) AS key
                FROM expert_nodes WHERE expert_id = $1
                """,
                expert_id,
            )
            existing_ids = {r["key"]: r["id"] for r in existing}
            # Endpoint rules are stated in node types, so the resolver carries
            # the type of every node an edge could name — including the ones
            # already in the graph, which this batch may only be deepening.
            node_types: dict[str, NodeType] = {
                r["key"]: coerce_node_type(r["node_type"]) or NodeType.CONCEPT for r in existing
            }

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
                        json.dumps({k: v for k, v in node["properties"].items() if v is not None}),
                        embedding,
                    )
                label_to_id[key] = node_id
                node_types[key] = coerce_node_type(node["node_type"]) or NodeType.CONCEPT

            # Resolve every edge to node ids first, then write them in one
            # round trip. Nothing is coerced on the way: an edge whose type is
            # not in the enum, or whose endpoints are the wrong kind of node for
            # its type, is rejected and counted. The old code defaulted a
            # missing type to `builds_on`, which silently mislabelled rather
            # than dropping, and let `contradicts` stand between two concepts —
            # a category error that accounted for nearly half the graph's
            # headline signal.
            relations: dict[tuple[int, int, str], dict] = {}
            rejected: Counter[str] = Counter()
            for ext in extractions:
                for edge in ext.get("edges", []):
                    if not edge.get("from_label") or not edge.get("to_label"):
                        rejected["missing_label"] += 1
                        continue
                    edge_type = coerce_edge_type(edge.get("edge_type"))
                    if edge_type is None:
                        rejected[f"unknown_type:{edge.get('edge_type')}"] += 1
                        continue
                    from_key = edge["from_label"].lower().strip()
                    to_key = edge["to_label"].lower().strip()
                    from_id, to_id = label_to_id.get(from_key), label_to_id.get(to_key)
                    # An edge naming a node no extraction produced, or a
                    # self-loop, carries no information.
                    if from_id is None or to_id is None:
                        rejected["unresolved_endpoint"] += 1
                        continue
                    if from_id == to_id:
                        rejected["self_loop"] += 1
                        continue
                    if not edge_is_valid(edge_type, node_types[from_key], node_types[to_key]):
                        rejected[f"bad_endpoints:{edge_type}"] += 1
                        continue

                    properties = {
                        k: v
                        for k, v in (edge.get("properties") or {}).items()
                        if isinstance(v, (str, int, float, bool))
                    }
                    required = EDGE_REQUIRED_PROPERTY.get(edge_type)
                    if required is not None and not str(properties.get(required, "")).strip():
                        rejected[f"missing_{required}"] += 1
                        continue
                    relations[(from_id, to_id, str(edge_type))] = properties

            if rejected:
                logger.info(
                    "Graph ingest for expert %d rejected %d edge(s): %s",
                    expert_id,
                    sum(rejected.values()),
                    dict(rejected),
                )

            if relations:
                await conn.executemany(
                    """
                    INSERT INTO expert_edges
                        (expert_id, from_node_id, to_node_id, edge_type, properties)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (expert_id, from_node_id, to_node_id, edge_type)
                    DO UPDATE SET properties =
                        coalesce(expert_edges.properties, '{}'::jsonb) || EXCLUDED.properties
                    """,
                    [
                        (expert_id, from_id, to_id, edge_type, json.dumps(properties))
                        for (from_id, to_id, edge_type), properties in relations.items()
                    ],
                )

        return len(merged_nodes), len(relations)

    async def delete_graph(self, expert_id: int) -> None:
        """Remove every node and edge for an expert, leaving the corpus alone."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM expert_edges WHERE expert_id = $1", expert_id)
            await conn.execute("DELETE FROM expert_nodes WHERE expert_id = $1", expert_id)

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
                expert_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_all_nodes(self, expert_id: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, node_type, label, description, chunk_ids, embedding
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
                keep_id,
                drop_id,
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
                keep_id,
                drop_id,
                expert_id,
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
                keep_id,
                drop_id,
                expert_id,
            )
            await conn.execute(
                "UPDATE expert_edges SET from_node_id = $1 WHERE from_node_id = $2 AND expert_id = $3",
                keep_id,
                drop_id,
                expert_id,
            )
            await conn.execute(
                "UPDATE expert_edges SET to_node_id = $1 WHERE to_node_id = $2 AND expert_id = $3",
                keep_id,
                drop_id,
                expert_id,
            )
            await conn.execute(
                "DELETE FROM expert_edges WHERE from_node_id = to_node_id AND expert_id = $1",
                expert_id,
            )
            await conn.execute("DELETE FROM expert_nodes WHERE id = $1", drop_id)

    async def get_nodes_for_chunks(self, expert_id: int, chunk_ids: list[int]) -> list[dict]:
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
                expert_id,
                chunk_ids,
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

        Expansion is capped per hop, preferring the best-evidenced edges, so a
        hub node cannot pull the whole graph into the context window.
        """
        if not node_ids:
            return [], []

        async with self._pool.acquire() as conn:
            visited_ids = set(node_ids)
            frontier = list(node_ids)

            for _ in range(hops):
                edge_rows = await conn.fetch(
                    """
                    SELECT from_node_id, to_node_id, edge_type, evidence, properties
                    FROM expert_edges
                    WHERE expert_id = $1
                      AND (from_node_id = ANY($2) OR to_node_id = ANY($2))
                    ORDER BY evidence DESC
                    """,
                    expert_id,
                    frontier,
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
                expert_id,
                all_node_ids,
            )
            edge_rows = await conn.fetch(
                """
                SELECT from_node_id, to_node_id, edge_type, evidence, properties
                FROM expert_edges
                WHERE expert_id = $1
                  AND from_node_id = ANY($2)
                  AND to_node_id = ANY($2)
                """,
                expert_id,
                all_node_ids,
            )

        return [dict(r) for r in node_rows], [_edge_dict(r) for r in edge_rows]

    # ── reconciliation pass ──────────────────────────────────────────────────

    async def claims_by_concept(
        self,
        expert_id: int,
        min_sources: int = 2,
        touching_chunk_ids: list[int] | None = None,
    ) -> list[ConceptClaims]:
        """Every claim in the corpus, grouped by the concept it is `about`.

        This is the unit the reconciliation pass works in, and the reason
        `about` earns its place in the vocabulary: without a claim→concept
        index there is no bounded way to put the claims two sources make about
        the same thing in front of a model at once.

        A claim's source is the source behind its passages. Claims spanning
        several sources (after entity resolution merged two labels) are listed
        once per source, so the pass can still see them from both sides.

        ``touching_chunk_ids`` narrows the concepts to those some claim in those
        passages is about — every claim about them still comes back, from every
        source. That is what makes reconciliation affordable on the upload path:
        one document's concepts get re-examined against the whole corpus,
        instead of the whole corpus being re-examined against itself.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id            AS concept_id,
                       c.label         AS concept_label,
                       n.id            AS claim_id,
                       n.label         AS claim_label,
                       n.description   AS claim_description,
                       s.id            AS source_id,
                       s.title         AS source_title,
                       s.source_type   AS source_type
                FROM expert_edges e
                JOIN expert_nodes n ON n.id = e.from_node_id AND n.node_type = 'claim'
                JOIN expert_nodes c ON c.id = e.to_node_id   AND c.node_type = 'concept'
                LEFT JOIN LATERAL (
                    SELECT DISTINCT sc.source_id
                    FROM source_chunks sc
                    WHERE sc.id = ANY(n.chunk_ids)
                ) cs ON true
                LEFT JOIN sources s ON s.id = cs.source_id
                WHERE e.expert_id = $1 AND e.edge_type = 'about'
                  AND ($2::integer[] IS NULL OR c.id IN (
                        SELECT e2.to_node_id
                        FROM expert_edges e2
                        JOIN expert_nodes n2 ON n2.id = e2.from_node_id
                        WHERE e2.expert_id = $1 AND e2.edge_type = 'about'
                          AND n2.chunk_ids && $2::integer[]
                  ))
                ORDER BY c.id, n.id
                """,
                expert_id,
                touching_chunk_ids,
            )

        groups: dict[int, ConceptClaims] = {}
        for r in rows:
            group = groups.get(r["concept_id"])
            if group is None:
                group = ConceptClaims(concept_id=r["concept_id"], concept_label=r["concept_label"])
                groups[r["concept_id"]] = group
            group.claims.append(
                ClaimRow(
                    node_id=r["claim_id"],
                    label=r["claim_label"],
                    description=r["claim_description"],
                    source_id=r["source_id"],
                    source_title=r["source_title"],
                    source_type=r["source_type"],
                )
            )
        return [g for g in groups.values() if g.source_count >= min_sources]

    async def insert_relations(self, expert_id: int, relations: list[dict]) -> int:
        """Persist claim-to-claim relations from the reconciliation pass.

        Validated here as well as at extraction: this path takes node ids
        straight from a model's answer, so the endpoint rule is re-checked
        against the stored node types rather than assumed.
        """
        if not relations:
            return 0

        wanted = {r["from_node_id"] for r in relations} | {r["to_node_id"] for r in relations}
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "SELECT id, node_type FROM expert_nodes WHERE expert_id = $1 AND id = ANY($2)",
                expert_id,
                list(wanted),
            )
            types = {r["id"]: coerce_node_type(r["node_type"]) or NodeType.CONCEPT for r in rows}

            payload: dict[tuple[int, int, str], dict] = {}
            rejected: Counter[str] = Counter()
            for relation in relations:
                edge_type = coerce_edge_type(relation.get("edge_type"))
                from_id, to_id = relation["from_node_id"], relation["to_node_id"]
                if edge_type is None:
                    rejected[f"unknown_type:{relation.get('edge_type')}"] += 1
                    continue
                if from_id not in types or to_id not in types or from_id == to_id:
                    rejected["unresolved_endpoint"] += 1
                    continue
                if not edge_is_valid(edge_type, types[from_id], types[to_id]):
                    rejected[f"bad_endpoints:{edge_type}"] += 1
                    continue
                required = EDGE_REQUIRED_PROPERTY.get(edge_type)
                properties = relation.get("properties") or {}
                if required is not None and not str(properties.get(required, "")).strip():
                    rejected[f"missing_{required}"] += 1
                    continue
                payload[(from_id, to_id, str(edge_type))] = properties

            if rejected:
                logger.info(
                    "Reconciliation for expert %d rejected %d relation(s): %s",
                    expert_id,
                    sum(rejected.values()),
                    dict(rejected),
                )
            if not payload:
                return 0

            await conn.executemany(
                """
                INSERT INTO expert_edges
                    (expert_id, from_node_id, to_node_id, edge_type, properties)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (expert_id, from_node_id, to_node_id, edge_type)
                DO UPDATE SET properties =
                    coalesce(expert_edges.properties, '{}'::jsonb) || EXCLUDED.properties
                """,
                [
                    (expert_id, from_id, to_id, edge_type, json.dumps(properties))
                    for (from_id, to_id, edge_type), properties in payload.items()
                ],
            )
        return len(payload)

    async def recompute_edge_evidence(self, expert_id: int) -> None:
        """Count the distinct sources behind each edge's two endpoints.

        This replaces the model-asserted `weight`, which was a number with no
        definition: three quarters of edges sat above 0.8, so ordering by it
        ordered nothing. The count here is read off the corpus — how many
        sources the passages behind both endpoints come from — so an edge that
        two independent sources stand behind outranks one asserted from a single
        paragraph, and nothing about the ordering is a model's opinion.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE expert_edges e
                SET evidence = coalesce(v.n, 0)
                FROM (
                    SELECT e2.id,
                           count(DISTINCT sc.source_id)::int AS n
                    FROM expert_edges e2
                    JOIN expert_nodes fn ON fn.id = e2.from_node_id
                    JOIN expert_nodes tn ON tn.id = e2.to_node_id
                    LEFT JOIN source_chunks sc
                      ON sc.id = ANY(coalesce(fn.chunk_ids, '{}') || coalesce(tn.chunk_ids, '{}'))
                    WHERE e2.expert_id = $1
                    GROUP BY e2.id
                ) v
                WHERE e.id = v.id AND e.expert_id = $1
                """,
                expert_id,
            )


def _edge_dict(row: asyncpg.Record) -> dict:
    """One edge row with its properties decoded.

    The pool registers no JSONB codec, so `properties` arrives as text on some
    paths and as an object on others; the stated point of a contradiction is
    read on every chat turn, so it is decoded once here rather than at each
    reader.
    """
    edge = dict(row)
    raw = edge.get("properties")
    if isinstance(raw, str):
        try:
            edge["properties"] = json.loads(raw)
        except json.JSONDecodeError:
            edge["properties"] = {}
    elif raw is None:
        edge["properties"] = {}
    return edge
