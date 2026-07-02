-- Migration 010: associate experts with Supabase Auth users.
--
-- Each expert gains an owner_id (auth.users.id / the JWT `sub`). Experts created
-- before auth existed keep owner_id = NULL; the API treats NULL-owned experts as
-- belonging to the bootstrap admin (BOOTSTRAP_ADMIN_EMAIL) so nothing is orphaned.

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS owner_id UUID;

CREATE INDEX IF NOT EXISTS idx_experts_owner ON experts (owner_id);

-- Enforce referential integrity against Supabase's auth.users when that schema is
-- present (i.e. running against a real Supabase project). Skipped for a plain
-- local Postgres (dev / CI) where the auth schema does not exist. ON DELETE
-- CASCADE removes a user's experts when the account is deleted.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'experts' AND constraint_name = 'experts_owner_id_fkey'
    ) THEN
        ALTER TABLE experts
            ADD CONSTRAINT experts_owner_id_fkey
            FOREIGN KEY (owner_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END $$;
