-- Migration 030: graded concept tags.
--
-- The validator used to tag each source with the key concepts it "substantively
-- covers" — one flat list, no depth, no cap — and coverage counted every tag. A
-- 200,000-character volume "covered" four concepts at once, and the Thomism
-- build (expert 60) declared natural law met with primary sources while the
-- treatise on law, the plan's own named text for it, was missing.
--
-- Tags now carry a depth: sets_out | treats | mentions. `covered_concepts` keeps
-- its shape (the names at treats or deeper) so every reader of it is unchanged;
-- this column holds the depth of every tag, mentions included. Nullable and not
-- backfilled — a source validated before rubric v8 was never graded.
-- See docs/plans/syllabus.md, 4.A.

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS concept_depths JSONB;
