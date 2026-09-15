-- Migration 029: make source selection visible.
--
-- What a build stored about how its corpus was chosen, before this: validator
-- scores and tier, per *fetched* source. What it did not store: the research
-- plan; each candidate's triage score, prior and fetch rank; which candidates
-- were ranked but not fetched, and why. On the Thomism build (job 53) an
-- actress, a disambiguation page and an OCR'd visual-analytics paper were
-- fetched on a fallback triage score, and nothing in the database could show
-- it. See docs/plans/source-selection.md §4.
--
-- 1. The plan, on the expert. Key concepts were already stored; the queries,
--    fetcher weights and must-have works lived only in a worker log line.
--
-- 2. A screening ledger: one row per candidate triage saw, fetched or not.
--    `job_id` is nullable, unlike the plan's first sketch, because CLI builds
--    run without a job and their selection is just as worth auditing. Rows
--    cascade with the expert and with the job.
--
-- 3. On `sources`: the triage score the fetch queue sorted on, and the
--    substance of the text (full / partial / abstract), which decides whether a
--    source counts toward coverage. Nullable and not backfilled — a source
--    built before this migration was never triaged under these rules.

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS research_plan JSONB;

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS triage_score REAL,
    ADD COLUMN IF NOT EXISTS substance    TEXT;

CREATE TABLE IF NOT EXISTS candidate_screenings (
    id                BIGSERIAL PRIMARY KEY,
    job_id            BIGINT REFERENCES build_jobs(id) ON DELETE CASCADE,
    expert_id         BIGINT NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    round             SMALLINT NOT NULL,
    source_type       TEXT NOT NULL,
    url               TEXT NOT NULL,
    title             TEXT NOT NULL,
    author            TEXT,
    -- What triage was shown, truncated as triage truncates it — so the
    -- triage harness (eval/triage.py) can re-score exactly this candidate.
    snippet           TEXT NOT NULL DEFAULT '',
    -- plan | snowball:backward | snowball:forward | canonical | feedback:<concept>
    discovered_via    TEXT NOT NULL,
    -- The model's own number. NULL when the model never scored the candidate.
    model_score       REAL,
    domain_adjustment REAL NOT NULL DEFAULT 0,
    -- What the fetch queue sorted on.
    triage_score      REAL NOT NULL,
    -- scored | reasked | unscored | must_have | priority
    triage_status     TEXT NOT NULL,
    -- Position in the round's fetch order; NULL when never queued.
    fetch_rank        INTEGER,
    -- fetched | failed | capped | below_floor | near_duplicate | budget |
    -- not_reached | content_duplicate
    fetch_outcome     TEXT,
    source_id         BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_candidate_screenings_job_round
    ON candidate_screenings (job_id, round);
CREATE INDEX IF NOT EXISTS idx_candidate_screenings_expert
    ON candidate_screenings (expert_id, created_at);
