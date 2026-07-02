-- Migration 010: durable background build jobs
--
-- Decouples expert builds from the HTTP request. A build is now a row in
-- build_jobs, claimed by a worker via SELECT ... FOR UPDATE SKIP LOCKED, with
-- progress persisted to build_events so clients can reconnect and builds survive
-- server restarts.

CREATE TABLE IF NOT EXISTS build_jobs (
    id            BIGSERIAL PRIMARY KEY,
    expert_id     INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    status        VARCHAR(20) NOT NULL DEFAULT 'queued',  -- queued|running|succeeded|failed|cancelled
    tier          VARCHAR(20) NOT NULL,
    source_filter JSONB,                                  -- optional --sources passthrough
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),     -- backoff gate for retries
    locked_by     TEXT,                                   -- worker id currently holding the job
    heartbeat_at  TIMESTAMPTZ,                            -- last liveness beat from the worker
    last_error    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cheap lookup of the next runnable job.
CREATE INDEX IF NOT EXISTS idx_build_jobs_claim
    ON build_jobs (available_at) WHERE status = 'queued';
-- Reaper scan over live jobs by heartbeat.
CREATE INDEX IF NOT EXISTS idx_build_jobs_running
    ON build_jobs (heartbeat_at) WHERE status = 'running';
-- At most one active job per expert, so double-submits never double-build.
CREATE UNIQUE INDEX IF NOT EXISTS idx_build_jobs_one_active
    ON build_jobs (expert_id) WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS build_events (
    seq        BIGSERIAL PRIMARY KEY,   -- global monotonic cursor for SSE tailing
    job_id     BIGINT NOT NULL REFERENCES build_jobs(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,           -- 'stage' | 'fetcher_done' | ... | 'done' | 'error'
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_build_events_job_seq ON build_events (job_id, seq);

-- Reconcile experts stranded in 'building' by the pre-jobs code path so the UI is
-- clean after deploy. There are no durable jobs to resume them.
UPDATE experts
SET status = 'failed',
    error = 'Interrupted before durable jobs existed — please rebuild.',
    updated_at = NOW()
WHERE status = 'building';
