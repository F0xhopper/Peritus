-- Stamp each source with how it was vetted, so the credential card can show
-- *which model* and *which rubric* produced the quality/relevance scores.
ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS validator_model TEXT,
    ADD COLUMN IF NOT EXISTS rubric_version  TEXT;
