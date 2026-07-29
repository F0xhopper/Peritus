-- Migration 020: record how close each source sits to the subject itself.
--
-- Validation already scores quality and relevance, and a corpus can score well
-- on both while consisting entirely of material *about* a subject rather than
-- *of* it — reader reviews, study guides, and summary services describe a work
-- accurately and on-topic without ever being the work. That corpus can only
-- produce second-hand answers, and until now nothing recorded the difference,
-- so it was invisible to the build log, the audit trail, and any later query.
--
--   primary    the work, text, dataset, standard, or original research itself,
--              or a practitioner writing first-hand
--   secondary  substantive scholarly or expert analysis making its own argument
--              about primary material
--   tertiary   summaries, reviews, study guides, listicles, encyclopedia-style
--              overviews — material that mainly restates what others have said
--
-- Nullable on purpose, and left NULL for every existing row: NULL means "not
-- classified" (validated under rubric v3, or a validator error), which is not
-- the same as any of the three tiers. Backfilling a guess would put fabricated
-- judgements into the provenance record. `sources.rubric_version` says which
-- rubric produced a row — v4-tiered-q5r6 and later carry a tier.

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS source_tier TEXT;

DO $$
BEGIN
    ALTER TABLE sources
        ADD CONSTRAINT sources_source_tier_check
        CHECK (source_tier IS NULL OR source_tier IN ('primary', 'secondary', 'tertiary'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- The read this exists for: "what is this expert's corpus actually made of",
-- always scoped to one expert and to the sources that passed validation.
CREATE INDEX IF NOT EXISTS idx_sources_expert_tier
    ON sources (expert_id, source_tier)
    WHERE passed = true;
