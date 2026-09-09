-- Migration 024: the concept graph's relationship vocabulary.
--
-- Six edge types become five, and the five mean something the endpoints can be
-- checked against. The old set described a concept ontology — "A defines B",
-- "A builds on B" — which a fast model reading ten chunks at a time cannot
-- assert reliably and which no product surface ever consumed: five of the six
-- types had exactly one reader, a one-line annotation under a retrieved
-- passage. The one type that does real work, `contradicts`, was wrong nearly
-- half the time in a specific and structural way: 45% of contradiction edges
-- sat between two *concepts*, and two concepts cannot contradict each other.
-- Only two propositions can.
--
-- The new set is an evidence map rather than an ontology:
--
--   contradicts  claim → claim      the two propositions cannot both be true
--   supports     claim → claim      a second source asserts, or evidences, the same
--   qualifies    claim → claim      true, but only under a stated condition
--   about        claim → concept    the concept a claim is about — the index
--   part_of      concept → concept  the one hierarchy edge between concepts
--
-- No expert needs rebuilding. Everything mappable is mapped, everything else is
-- dropped, and `/contradictions` keeps working throughout because it only ever
-- read claim→claim `contradicts` — the subset being kept.

-- ── 1. Node types ───────────────────────────────────────────────────────────
-- The schema allowed `concept` and `claim` and enforced neither, so the model
-- leaked the `content_type` vocabulary into `node_type`. An argument or a
-- counterargument is a proposition, so it becomes a claim; everything else
-- outside the enum becomes a concept.
UPDATE expert_nodes
SET node_type = CASE
        WHEN lower(node_type) IN ('argument', 'counterargument')
          OR lower(coalesce(properties->>'content_type', '')) IN ('argument', 'counterargument')
        THEN 'claim'
        ELSE 'concept'
    END
WHERE lower(node_type) NOT IN ('concept', 'claim');

-- `content_type` picked up edge type names in the same exchange.
UPDATE expert_nodes
SET properties = properties - 'content_type'
WHERE properties ? 'content_type'
  AND lower(properties->>'content_type') NOT IN
      ('definition', 'theorem', 'example', 'argument', 'counterargument');

-- ── 2. Edge vocabulary ──────────────────────────────────────────────────────
-- Retyping collapses distinct old relations onto the same new one, so the
-- uniqueness constraint from migration 013 comes off first and goes back on
-- after the duplicates it would have rejected are merged.
DROP INDEX IF EXISTS uq_expert_edges_relation;

-- claim → concept, however it was labelled, is what `about` now says. So is the
-- same relation written backwards: `defines` and `exemplifies` were extracted in
-- both directions (the direction was one of the type's documented problems), and
-- a concept→claim edge of those types is a claim about a concept with its ends
-- swapped, not a different fact.
UPDATE expert_edges e
SET edge_type = 'about'
FROM expert_nodes fn, expert_nodes tn
WHERE fn.id = e.from_node_id AND tn.id = e.to_node_id
  AND e.edge_type IN ('builds_on', 'defines', 'exemplifies')
  AND fn.node_type = 'claim' AND tn.node_type = 'concept';

UPDATE expert_edges e
SET edge_type = 'about',
    from_node_id = e.to_node_id,
    to_node_id = e.from_node_id
FROM expert_nodes fn, expert_nodes tn
WHERE fn.id = e.from_node_id AND tn.id = e.to_node_id
  AND e.edge_type IN ('defines', 'exemplifies')
  AND fn.node_type = 'concept' AND tn.node_type = 'claim';

-- concept → concept hierarchy, under whichever of the four names it arrived.
-- One type, not three, because a ten-chunk window cannot tell "is a kind of"
-- from "is a component of" from "is a prerequisite for" with any reliability,
-- and no consumer needed the distinction.
UPDATE expert_edges e
SET edge_type = 'part_of'
FROM expert_nodes fn, expert_nodes tn
WHERE fn.id = e.from_node_id AND tn.id = e.to_node_id
  AND e.edge_type IN ('builds_on', 'defines', 'includes', 'contains')
  AND fn.node_type = 'concept' AND tn.node_type = 'concept';

-- Everything that survives must be one of the five, between the right kinds of
-- node. That drops: `cites` (86 edges asserted between concepts by a model that
-- never saw a reference list — real citation structure lives in the sources
-- ledger, at DOI resolution); the dozen off-schema types that leaked in
-- (`enriches`, `affects`, `causes`, `requires`, …), each of which is a claim
-- about the world dressed as an ontology edge; and every `contradicts` or
-- `supports` with a concept on either end.
DELETE FROM expert_edges e
USING expert_nodes fn, expert_nodes tn
WHERE fn.id = e.from_node_id AND tn.id = e.to_node_id
  AND NOT (
        (e.edge_type IN ('contradicts', 'supports', 'qualifies')
         AND fn.node_type = 'claim' AND tn.node_type = 'claim')
     OR (e.edge_type = 'about'
         AND fn.node_type = 'claim' AND tn.node_type = 'concept')
     OR (e.edge_type = 'part_of'
         AND fn.node_type = 'concept' AND tn.node_type = 'concept')
  );

DELETE FROM expert_edges WHERE from_node_id = to_node_id;

DELETE FROM expert_edges e1
USING expert_edges e2
WHERE e1.expert_id = e2.expert_id
  AND e1.from_node_id = e2.from_node_id
  AND e1.to_node_id = e2.to_node_id
  AND e1.edge_type = e2.edge_type
  AND e1.id > e2.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_edges_relation
    ON expert_edges (expert_id, from_node_id, to_node_id, edge_type);

-- ── 3. Evidence replaces weight ─────────────────────────────────────────────
-- `weight` was a "strength" the model was asked for and given no definition of,
-- so it returned its prior: three quarters of edges landed above 0.8 and one
-- percent below 0.6. The retriever ordered hop expansion by it and the graph
-- view scaled line width by it, and neither was doing anything.
--
-- `evidence` is counted off the corpus instead: how many distinct sources the
-- passages behind the edge's two endpoints come from. It cannot be read as
-- confidence, because it isn't one — it is how much of the corpus stands behind
-- the relation.
ALTER TABLE expert_edges ADD COLUMN IF NOT EXISTS evidence INTEGER NOT NULL DEFAULT 0;

UPDATE expert_edges e
SET evidence = v.n
FROM (
    SELECT e2.id, count(DISTINCT sc.source_id)::int AS n
    FROM expert_edges e2
    JOIN expert_nodes fn ON fn.id = e2.from_node_id
    JOIN expert_nodes tn ON tn.id = e2.to_node_id
    LEFT JOIN source_chunks sc
      ON sc.id = ANY(coalesce(fn.chunk_ids, '{}') || coalesce(tn.chunk_ids, '{}'))
    GROUP BY e2.id
) v
WHERE e.id = v.id;

-- Drops idx_expert_edges_contradicts (migration 017) with it; replaced below.
ALTER TABLE expert_edges DROP COLUMN IF EXISTS weight;

CREATE INDEX IF NOT EXISTS idx_expert_edges_contradicts
    ON expert_edges (expert_id, evidence DESC, id)
    WHERE edge_type = 'contradicts';

-- The reconciliation pass walks `about` from every concept to its claims.
CREATE INDEX IF NOT EXISTS idx_expert_edges_about
    ON expert_edges (expert_id, to_node_id)
    WHERE edge_type = 'about';

-- ── 4. Enforce the vocabulary ───────────────────────────────────────────────
-- The tool schema always declared these enums; nothing checked them, and
-- `bulk_insert_from_extractions` defaulted a missing edge type to `builds_on`
-- rather than rejecting it, which silently mislabelled. Ingest now rejects and
-- counts; these constraints are the backstop that keeps a future writer honest.
-- Endpoint rules span rows and so cannot be a CHECK — they live in
-- `peritus.graph.domain.edge_is_valid`, applied on both write paths.
ALTER TABLE expert_nodes DROP CONSTRAINT IF EXISTS expert_nodes_node_type_chk;
ALTER TABLE expert_nodes ADD CONSTRAINT expert_nodes_node_type_chk
    CHECK (node_type IN ('concept', 'claim'));

ALTER TABLE expert_edges DROP CONSTRAINT IF EXISTS expert_edges_edge_type_chk;
ALTER TABLE expert_edges ADD CONSTRAINT expert_edges_edge_type_chk
    CHECK (edge_type IN ('contradicts', 'supports', 'qualifies', 'about', 'part_of'));
