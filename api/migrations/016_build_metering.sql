-- Migration 016: build cost metering + the entitlement/credit substrate.
--
-- A build is the product's capex: Claude calls for planning, triage, validation,
-- contextualisation of every chunk, graph extraction over every chunk, and the
-- persona, plus OpenAI embeddings for every chunk and graph node. Until now none
-- of that was measured and none of it was gated, so spend was unbounded and
-- unattributable.
--
-- Two halves, deliberately in one migration (015/016 are the only slots this
-- change owns):
--
--   A. METERING — what a build actually cost, per stage, recorded from observed
--      runtime usage. Never inferred from configuration: `mode` records whether
--      a response actually came back through the Message Batches API or a live
--      call, because whether batching is on is decided elsewhere and may change
--      per build.
--
--   B. ENTITLEMENTS — an account with a plan, an append-only credit ledger, and
--      a per-build hold that is placed at ENQUEUE time and refunded if the build
--      does not produce a usable expert. Provider-agnostic on purpose: there is
--      no payment provider here, only a `source` string on each ledger entry so
--      one can be bolted on later without a schema change.

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Metering
-- ─────────────────────────────────────────────────────────────────────────────

-- One row per (job, stage, provider, model, mode) — the meter aggregates calls
-- in memory and flushes periodically, so this stays small even for a Pro build
-- that makes thousands of calls.
CREATE TABLE IF NOT EXISTS build_usage_events (
    id            BIGSERIAL PRIMARY KEY,
    job_id        BIGINT NOT NULL REFERENCES build_jobs(id) ON DELETE CASCADE,
    expert_id     INTEGER REFERENCES experts(id) ON DELETE SET NULL,
    owner_id      UUID,                 -- denormalised for per-user spend reporting
    -- plan | triage | validation | contextualization | graph_extraction |
    -- persona | embedding | other
    stage         TEXT NOT NULL,
    provider      TEXT NOT NULL,        -- anthropic | openai
    model         TEXT NOT NULL,        -- as reported by the API response, not config
    mode          TEXT NOT NULL,        -- live | batch — OBSERVED, never inferred
    calls         INTEGER NOT NULL DEFAULT 0,
    input_tokens  BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cache_creation_input_tokens BIGINT NOT NULL DEFAULT 0,
    cache_read_input_tokens     BIGINT NOT NULL DEFAULT 0,
    -- Embedding calls report a single token count; it lands in input_tokens.
    cost_usd      NUMERIC(14, 6) NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_build_usage_job   ON build_usage_events (job_id);
CREATE INDEX IF NOT EXISTS idx_build_usage_owner ON build_usage_events (owner_id, created_at DESC);

-- Rollup on the job itself so "what did this build cost" is one row read, and
-- so the cap can be enforced without scanning the event table.
ALTER TABLE build_jobs
    ADD COLUMN IF NOT EXISTS cost_usd        NUMERIC(14, 6) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS input_tokens    BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS output_tokens   BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS embed_tokens    BIGINT NOT NULL DEFAULT 0,
    -- The tier's per-build spend cap, captured at enqueue so a later change to
    -- the price ladder cannot retroactively re-judge a running build.
    ADD COLUMN IF NOT EXISTS spend_cap_usd   NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS cap_exceeded_at TIMESTAMPTZ;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Entitlements and credits
-- ─────────────────────────────────────────────────────────────────────────────

-- One row per user. Auto-provisioned on first authenticated touch.
CREATE TABLE IF NOT EXISTS accounts (
    owner_id     UUID PRIMARY KEY,
    plan         TEXT NOT NULL DEFAULT 'free',
    email        TEXT,               -- best-effort, for admin grants by email
    -- Optional per-account override of the plan's per-build spend cap. NULL =
    -- use the tier/plan default.
    spend_cap_override_usd NUMERIC(14, 6),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts (lower(email));

-- Append-only credit ledger. Balance = SUM(delta). Never UPDATE a row here;
-- corrections are new rows. This is the audit trail a "auditable evidence
-- synthesis" product should be able to show its customers.
--
-- entry_type:
--   grant   (+) manual/admin issuance, signup grant, plan renewal, promo
--   hold    (-) reservation taken when a build job is ENQUEUED
--   refund  (+) hold returned because the build failed / was cancelled / hit cap
--   adjust  (±) manual correction
CREATE TABLE IF NOT EXISTS credit_ledger (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    UUID NOT NULL REFERENCES accounts(owner_id) ON DELETE CASCADE,
    entry_type  TEXT NOT NULL,
    delta       INTEGER NOT NULL,     -- credits; negative for holds
    job_id      BIGINT REFERENCES build_jobs(id) ON DELETE SET NULL,
    tier        TEXT,                 -- tier the hold was priced at
    reason      TEXT,
    -- Provider-agnostic seam. 'manual' / 'signup' / 'plan' today; a payment
    -- provider later writes its own value plus external_ref. NO payment
    -- provider is integrated — this is only the shape one would plug into.
    source      TEXT NOT NULL DEFAULT 'manual',
    external_ref TEXT,                -- provider-side id, when there is one
    actor       TEXT,                 -- who issued it (admin email / 'system')
    -- Realised spend attributed to this entry, for reporting. Populated on
    -- holds when the build finishes.
    cost_usd    NUMERIC(14, 6),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    ALTER TABLE credit_ledger
        ADD CONSTRAINT credit_ledger_type_check
        CHECK (entry_type IN ('grant', 'hold', 'refund', 'adjust'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_credit_ledger_owner ON credit_ledger (owner_id, id DESC);

-- Exactly one hold and at most one refund per job. This is what makes
-- authorisation idempotent: a double-submitted build cannot be charged twice,
-- and a retried refund cannot credit twice.
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_one_hold
    ON credit_ledger (job_id) WHERE entry_type = 'hold' AND job_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_one_refund
    ON credit_ledger (job_id) WHERE entry_type = 'refund' AND job_id IS NOT NULL;

-- Referential integrity against Supabase's auth.users when that schema exists
-- (real project); skipped on plain local Postgres (dev/CI), same pattern as
-- migrations 011 and 014.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'accounts' AND constraint_name = 'accounts_owner_id_fkey'
    ) THEN
        ALTER TABLE accounts
            ADD CONSTRAINT accounts_owner_id_fkey
            FOREIGN KEY (owner_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END $$;
