-- Graph integrity: deduplicate edges, enforce uniqueness, index the chunk-overlap lookup.

-- Surviving edge keeps the strongest observed weight before duplicates are removed.
UPDATE expert_edges e
SET weight = g.max_weight
FROM (
    SELECT expert_id, from_node_id, to_node_id, edge_type, MAX(weight) AS max_weight
    FROM expert_edges
    GROUP BY expert_id, from_node_id, to_node_id, edge_type
    HAVING COUNT(*) > 1
) g
WHERE e.expert_id = g.expert_id
  AND e.from_node_id = g.from_node_id
  AND e.to_node_id = g.to_node_id
  AND e.edge_type = g.edge_type;

DELETE FROM expert_edges e1
USING expert_edges e2
WHERE e1.expert_id = e2.expert_id
  AND e1.from_node_id = e2.from_node_id
  AND e1.to_node_id = e2.to_node_id
  AND e1.edge_type = e2.edge_type
  AND e1.id > e2.id;

DELETE FROM expert_edges WHERE from_node_id = to_node_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_edges_relation
    ON expert_edges (expert_id, from_node_id, to_node_id, edge_type);

-- get_nodes_for_chunks filters with `chunk_ids && $2::integer[]` on every chat turn.
CREATE INDEX IF NOT EXISTS idx_expert_nodes_chunks
    ON expert_nodes USING gin (chunk_ids);
