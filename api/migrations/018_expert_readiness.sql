-- Migration 018: retrieval readiness, separate from build-job status.
--
-- `experts.status` describes the build job (queued → building → ready/failed).
-- It is a poor proxy for "can I talk to this expert", because the corpus is
-- retrievable well before the job ends: hybrid search reads only source_chunks
-- + sources and has no dependency on the concept graph, and graph expansion is
-- already a no-op for an expert with no nodes. So an expert is answerable the
-- moment the embed stage lands — roughly one stage (graph extract + entity
-- resolution + persona) before `status` flips to 'ready'.
--
-- `readiness` records that:
--   pending      no retrievable corpus yet (plan / discover / validate)
--   chat_ready   chunks embedded — hybrid search + citations work; no graph
--                expansion (and possibly no persona voice) yet
--   graph_ready  concept graph extracted and resolved — full retrieval
--
-- It moves forward only within a build; a rebuild resets it to 'pending' before
-- the previous corpus is replaced.

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS readiness      TEXT        NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS chat_ready_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS graph_ready_at TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE experts
        ADD CONSTRAINT experts_readiness_check
        CHECK (readiness IN ('pending', 'chat_ready', 'graph_ready'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Backfill: every expert that already finished a build has a full corpus and a
-- concept graph, so it is graph_ready. Timestamps are unknown historically —
-- use updated_at, which for a finished build is when it was marked ready.
UPDATE experts
SET readiness      = 'graph_ready',
    chat_ready_at  = COALESCE(chat_ready_at, updated_at),
    graph_ready_at = COALESCE(graph_ready_at, updated_at)
WHERE status = 'ready'
  AND readiness <> 'graph_ready';

-- Anything mid-build or failed has no guarantees about its chunks.
UPDATE experts
SET readiness = 'pending'
WHERE status <> 'ready'
  AND readiness <> 'pending';

-- Listing "which of my experts can I use" is the hot read.
CREATE INDEX IF NOT EXISTS idx_experts_readiness
    ON experts (owner_id, readiness);
