-- Migration 015: expert visibility + curated public catalog.
--
-- Until now every expert was private to its owner (011_expert_owners.sql), with
-- owner_id IS NULL meaning "belongs to the bootstrap admin". There was no way to
-- say "this expert is a finished, good expert that any signed-up user may read
-- and chat with". That is the product's free tier and its first-90-seconds
-- experience, so it needs to be a first-class column rather than a convention.
--
-- Three visibility levels:
--   private   (default) — only the owner (and the admin for owner-less rows)
--   unlisted  — readable/chattable by anyone who knows the slug; never listed
--   public    — readable/chattable by anyone AND listed in the catalog
--
-- Everything else here is what a *curated* catalog needs on top of "is public":
-- a blurb to render on a card, a category to group by, tags to filter by, a
-- featured flag and a manual rank so the founder controls the shelf order, and
-- published_at/published_by for provenance.
--
-- NOTE: visibility governs READ + CHAT only. Mutation (rebuild, delete, curate)
-- stays owner-scoped in every code path — see experts/repository.py, which keeps
-- a strictly-owner clause (_visibility_clause, also used by conversations) apart
-- from the wider read clause (_readable_clause).

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS visibility   TEXT NOT NULL DEFAULT 'private',
    ADD COLUMN IF NOT EXISTS is_featured  BOOLEAN NOT NULL DEFAULT false,
    -- Manual shelf order within the catalog. NULL sorts last, so an un-ranked
    -- expert is still listed (by recency) rather than hidden.
    ADD COLUMN IF NOT EXISTS catalog_rank INTEGER,
    ADD COLUMN IF NOT EXISTS blurb        TEXT,
    ADD COLUMN IF NOT EXISTS category     TEXT,
    -- Free-form topic tags, e.g. {"systematic-review","oncology"}.
    ADD COLUMN IF NOT EXISTS tags         TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS published_by UUID;

DO $$
BEGIN
    ALTER TABLE experts
        ADD CONSTRAINT experts_visibility_check
        CHECK (visibility IN ('private', 'unlisted', 'public'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    -- The blurb renders on a catalog card; keep it card-sized at the schema
    -- level so an over-long one can never break the grid.
    ALTER TABLE experts
        ADD CONSTRAINT experts_blurb_len_check
        CHECK (blurb IS NULL OR char_length(blurb) <= 280);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- The catalog listing query: visibility = 'public' AND status = 'ready',
-- ordered by featured, then manual rank, then recency.
CREATE INDEX IF NOT EXISTS idx_experts_catalog
    ON experts (is_featured DESC, catalog_rank, created_at DESC)
    WHERE visibility = 'public';

-- Category facet on the catalog.
CREATE INDEX IF NOT EXISTS idx_experts_catalog_category
    ON experts (category)
    WHERE visibility = 'public' AND category IS NOT NULL;

-- Tag filtering.
CREATE INDEX IF NOT EXISTS idx_experts_tags ON experts USING gin (tags);

-- Read-visibility lookups ("is this slug readable by anyone?") hit this.
CREATE INDEX IF NOT EXISTS idx_experts_visibility ON experts (visibility);
