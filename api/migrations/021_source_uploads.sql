-- Migration 021: user-supplied sources
--
-- Lets a user add their own material to an expert — a PDF, a text file, or a web
-- page. Discovery can only find what is publicly indexable, which for many
-- subjects excludes the material that matters most: anything in copyright, plus
-- private notes, internal documents, and papers behind a login. The user often
-- has the document; the pipeline just needed a way to accept it.
--
-- Three pieces:
--   1. build_jobs learns a job_type, so the existing durable worker (claim,
--      heartbeat, retry, reap, SSE event tail) runs ingest jobs unchanged.
--   2. source_uploads holds the raw payload between the HTTP request and the
--      worker, which is a different process.
--   3. sources records who supplied it.

-- ── 1. build_jobs becomes multi-purpose ──────────────────────────────────────

ALTER TABLE build_jobs
    ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'build';

ALTER TABLE build_jobs
    ADD COLUMN IF NOT EXISTS payload JSONB;

DO $$
BEGIN
    ALTER TABLE build_jobs
        ADD CONSTRAINT build_jobs_job_type_check
        CHECK (job_type IN ('build', 'ingest_source'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- The "at most one active job per expert" rule was written when every job was a
-- build. It must stay exactly that strict for builds — a double-submit that
-- double-builds would wipe and re-fetch a corpus twice concurrently — but it
-- must not stop a user queueing two documents, or queueing one while another
-- ingests. So the uniqueness is now scoped to builds, and "no ingest while a
-- build is running" is enforced in the API instead, where it can return a
-- comprehensible error rather than a constraint violation.
DROP INDEX IF EXISTS idx_build_jobs_one_active;

CREATE UNIQUE INDEX IF NOT EXISTS idx_build_jobs_one_active_build
    ON build_jobs (expert_id)
    WHERE status IN ('queued', 'running') AND job_type = 'build';

-- Claiming scans queued jobs by availability; keeping job_type in the index lets
-- a claim stay index-only as ingest volume grows.
DROP INDEX IF EXISTS idx_build_jobs_claim;

CREATE INDEX IF NOT EXISTS idx_build_jobs_claim
    ON build_jobs (available_at, job_type) WHERE status = 'queued';

-- ── 2. pending payloads ──────────────────────────────────────────────────────
--
-- The row is created by the request handler and read by the worker, so the bytes
-- have to be durable in between. There is no blob store configured in this
-- project, and pdf_parser already caps a document at 20 MB, so BYTEA in Postgres
-- is the right size of solution — not a placeholder for S3.
--
-- `content` and `text_content` are cleared once the job succeeds: the extracted
-- text lives on as chunks, and keeping a second copy of every uploaded book
-- would grow this table without bound.

CREATE TABLE IF NOT EXISTS source_uploads (
    id           BIGSERIAL PRIMARY KEY,
    expert_id    INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    owner_id     TEXT,                    -- Supabase auth.users.id; NULL = legacy/admin
    kind         TEXT NOT NULL,           -- 'pdf' | 'text' | 'url'
    title        TEXT NOT NULL,
    author       TEXT,
    filename     TEXT,                    -- original upload filename, for display
    url          TEXT,                    -- set when kind = 'url'
    media_type   TEXT,                    -- reported content type, advisory only
    byte_size    INTEGER,
    content      BYTEA,                   -- raw bytes for kind = 'pdf'
    text_content TEXT,                    -- decoded text for kind = 'text'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT source_uploads_kind_check CHECK (kind IN ('pdf', 'text', 'url')),
    -- Every kind must actually carry its payload, so a malformed row fails at
    -- insert rather than in the worker minutes later.
    CONSTRAINT source_uploads_payload_check CHECK (
        (kind = 'pdf'  AND content IS NOT NULL)
     OR (kind = 'text' AND text_content IS NOT NULL)
     OR (kind = 'url'  AND url IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_source_uploads_expert
    ON source_uploads (expert_id, created_at DESC);

-- ── 3. provenance on the source itself ───────────────────────────────────────
--
-- `discovered_via` (migration 012) already records *how* a source arrived and
-- takes the value 'upload' for these. This records *who* supplied it, which
-- matters once an expert is shared: a reader looking at a citation should be
-- able to tell the owner's own material from what discovery found.

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS uploaded_by TEXT;

CREATE INDEX IF NOT EXISTS idx_sources_expert_uploaded
    ON sources (expert_id)
    WHERE discovered_via = 'upload';
