-- Concept-coverage tagging and discovery provenance for sources.
-- covered_concepts: which of the expert's key concepts the validator judged this
-- source to substantively cover (drives the gap-fill re-search round).
-- discovered_via: how the source entered the corpus — 'plan', 'snowball', or
-- 'gapfill:<concept>' — so corpus quality can be evaluated per discovery path.
ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS covered_concepts JSONB,
    ADD COLUMN IF NOT EXISTS discovered_via   TEXT;
