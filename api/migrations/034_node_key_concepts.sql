-- Migration 034: which key concept each concept node belongs to.
--
-- The expert's map (docs/plans/expert-brain.md) places every concept node in the
-- sector of the syllabus it belongs to, and nothing recorded that. A key concept
-- is a line of the plan ("Being, essence, and existence (act/potency)"); a node
-- is what extraction found in a passage ("Divine simplicity"). Across all five
-- experts not one node label equals a key concept, which is why the old concept
-- panel's "Sources covering this" button never rendered.
--
-- The assignment is by embedding: each key concept is embedded once with the
-- node embedder and every concept node takes its nearest one above a floor.
-- Below the floor the node is unassigned (NULL), which is honest — some concepts
-- belong to the topic and to no line of its syllabus.
--
-- `key_concept_idx` indexes `experts.key_concepts`, the canonical list; a plan
-- rewritten by a rebuild wipes the graph first, so the index cannot outlive the
-- list it points into. `key_concept_sim` is kept so the floor can be moved
-- without re-embedding anything. Both are NULL for claims and for any node
-- written before this migration until `peritus graph assign-key-concepts` runs.

ALTER TABLE expert_nodes
    ADD COLUMN IF NOT EXISTS key_concept_idx SMALLINT,
    ADD COLUMN IF NOT EXISTS key_concept_sim REAL;
