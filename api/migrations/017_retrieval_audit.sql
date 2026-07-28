-- Migration 017: answer-level retrieval audit trail + indexes for the corpus audit surface.
--
-- Peritus already records how every SOURCE entered the corpus (scores, drop
-- reason, validator model, rubric version, discovery path). What it did not
-- record is how evidence reached an individual ANSWER. These tables close that
-- gap: for each grounded answer we persist which passages were retrieved, which
-- of them actually reached the model's prompt, and which the answer cited.
--
-- This is a provenance trail, NOT a quality judgement. Nothing here scores an
-- answer; it only records the path the evidence took, so a researcher can
-- reconstruct and defend it later.
--
-- Deliberate denormalisation: chunk_id / source_id are soft references (no FK).
-- Rebuilding an expert deletes and recreates every row in `sources` and
-- `source_chunks`, so a hard FK would cascade away the audit trail of answers
-- that were given before the rebuild — destroying exactly the record this table
-- exists to keep. Source title / type / quality are copied in so a past answer's
-- trail stays readable after its corpus has been rebuilt.

CREATE TABLE IF NOT EXISTS answer_audits (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expert_id               INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    -- Set for the stateful conversation flow; NULL for the stateless
    -- /experts/{slug}/chat endpoint, which has no conversation to hang off.
    -- CASCADE so deleting a conversation also removes its answer trails.
    conversation_id         UUID REFERENCES conversations(id) ON DELETE CASCADE,
    question                TEXT NOT NULL,
    subqueries              JSONB NOT NULL DEFAULT '[]'::jsonb,
    followup_queries        JSONB NOT NULL DEFAULT '[]'::jsonb,
    coverage_satisfied      BOOLEAN,            -- NULL when the coverage check failed open
    second_pass             BOOLEAN NOT NULL DEFAULT false,
    retrieved_passages      INTEGER NOT NULL DEFAULT 0,  -- hits returned by retrieval
    duplicate_hits          INTEGER NOT NULL DEFAULT 0,  -- same chunk retrieved twice
    unique_passages         INTEGER NOT NULL DEFAULT 0,  -- distinct chunks considered
    context_passages        INTEGER NOT NULL DEFAULT 0,  -- passages placed in the prompt
    cited_passages          INTEGER NOT NULL DEFAULT 0,  -- passages the answer cited
    context_cap             INTEGER,                     -- tier's max_context_passages
    sources_in_context      INTEGER NOT NULL DEFAULT 0,
    sources_cited           INTEGER NOT NULL DEFAULT 0,
    contradiction_traversed BOOLEAN NOT NULL DEFAULT false,
    answer_chars            INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "Show me the audit trail for this expert's recent answers" — the list query.
CREATE INDEX IF NOT EXISTS idx_answer_audits_expert_recent
    ON answer_audits (expert_id, created_at DESC);
-- "Show me the trail for every answer in this conversation."
CREATE INDEX IF NOT EXISTS idx_answer_audits_conversation
    ON answer_audits (conversation_id, created_at DESC)
    WHERE conversation_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS answer_audit_passages (
    id              BIGSERIAL PRIMARY KEY,
    audit_id        UUID NOT NULL REFERENCES answer_audits(id) ON DELETE CASCADE,
    -- The [n] the model saw. NULL means the passage was retrieved but never
    -- reached the prompt (it fell outside the tier's context cap).
    passage_n       INTEGER,
    chunk_id        INTEGER,        -- soft ref to source_chunks.id (see header)
    source_id       INTEGER,        -- soft ref to sources.id (see header)
    source_title    TEXT,
    source_type     TEXT,
    quality_score   REAL,
    retrieval_rank  INTEGER NOT NULL,   -- 1-based position in the retrieval order
    retrieval_score REAL,               -- fused RRF score, or reranker score
    retrieved_via   TEXT NOT NULL DEFAULT 'primary',  -- primary | coverage_followup
    -- cited | in_context_uncited | not_in_context
    disposition     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_answer_audit_passages_audit
    ON answer_audit_passages (audit_id, retrieval_rank);

-- ── indexes the corpus-audit read path needs ────────────────────────────────

-- /experts/{slug}/contradictions filters expert_edges to one edge type and
-- orders by weight. expert_edges only had a plain (expert_id) index, so this
-- was a scan of every relationship in the graph to find the handful that
-- contradict. Partial: `contradicts` is a small minority of edges.
CREATE INDEX IF NOT EXISTS idx_expert_edges_contradicts
    ON expert_edges (expert_id, weight DESC, id)
    WHERE edge_type = 'contradicts';

-- The corpus report's per-source passage counts and the contradiction
-- passage lookup both join source_chunks by source; idx_source_chunks_source
-- (migration 005) already covers that, so no new index is needed there.
