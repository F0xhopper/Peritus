-- Migration 014: persistent expert conversations.
--
-- A conversation is created on the user's first message to an expert and holds
-- the full transcript (user + assistant turns, with the citations each answer
-- actually used). Conversations are owner-scoped exactly like experts
-- (owner_id = auth.users.id / JWT `sub`; NULL only for legacy/dev rows).

CREATE TABLE IF NOT EXISTS conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expert_id        INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    owner_id         UUID,                -- soft FK to auth.users, same as experts.owner_id
    title            TEXT,                -- NULL until the first message sets it
    message_count    INT  NOT NULL DEFAULT 0,
    -- Optimistic claim so only one answer streams per conversation at a time.
    -- Set when a stream starts, cleared when it ends; a crashed worker's stale
    -- claim self-heals after a 3-minute window (enforced in the repository).
    streaming_started_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_owner_recent
    ON conversations (owner_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_expert_recent
    ON conversations (expert_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    citations        JSONB,               -- assistant only: [{n, label, source_id}]
    has_contradiction BOOLEAN NOT NULL DEFAULT false,
    interrupted      BOOLEAN NOT NULL DEFAULT false,  -- stream died before `done`
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON conversation_messages (conversation_id, id);

-- Enforce referential integrity against Supabase's auth.users when that schema
-- is present (real Supabase project); skipped on plain local Postgres (dev/CI).
-- ON DELETE CASCADE removes a user's conversations when the account is deleted.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'conversations' AND constraint_name = 'conversations_owner_id_fkey'
    ) THEN
        ALTER TABLE conversations
            ADD CONSTRAINT conversations_owner_id_fkey
            FOREIGN KEY (owner_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END $$;
