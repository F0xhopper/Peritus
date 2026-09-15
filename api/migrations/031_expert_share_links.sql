-- Migration 031: share links replace "unlisted".
--
-- 015 gave experts an `unlisted` visibility meaning "anyone who knows the slug".
-- Slugs are derived from the topic (`thomism`, `thomism-2`), so that was a
-- guessable secret, not a link. Sharing is now a capability token:
--
--   expert_share_links   one random token per share. At most one *active* link
--                        per expert; resetting the link revokes the old row and
--                        inserts a new one, so every earlier grant stops working
--                        at once without being deleted.
--   expert_share_grants  who has opened a link while signed in. Read access for
--                        a non-owner is "holds a grant on a live link" — which
--                        is what lets the rest of the API keep resolving experts
--                        by slug without the slug itself granting anything.
--
-- The token is stored in plain text on purpose: the owner must be able to copy
-- the link again later, exactly like a document's share URL. It is 192 random
-- bits, so it is not enumerable.

UPDATE experts SET visibility = 'private', published_at = NULL WHERE visibility = 'unlisted';

ALTER TABLE experts DROP CONSTRAINT IF EXISTS experts_visibility_check;
ALTER TABLE experts
    ADD CONSTRAINT experts_visibility_check CHECK (visibility IN ('private', 'public'));

CREATE TABLE IF NOT EXISTS expert_share_links (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expert_id   INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE CHECK (char_length(token) >= 32),
    created_by  UUID,                     -- soft FK to auth.users, like experts.owner_id
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

-- One live link per expert. Enabling twice returns the same link; a concurrent
-- double-enable loses the race here instead of minting two.
CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_share_links_active
    ON expert_share_links (expert_id)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS expert_share_grants (
    link_id     UUID NOT NULL REFERENCES expert_share_links(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (link_id, user_id)
);

-- The read clause and "shared with me" both look grants up by user.
CREATE INDEX IF NOT EXISTS idx_expert_share_grants_user ON expert_share_grants (user_id);
