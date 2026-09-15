-- The one grounding signal every answer emits for free: [n] markers that point
-- at no passage — the model inventing a reference. It was logged per answer and
-- sent to the client, and never persisted, so its rate could not be queried.
-- Additive with a default, so audits written before it read as "none recorded".

ALTER TABLE answer_audits
    ADD COLUMN IF NOT EXISTS dangling_citations INTEGER[] NOT NULL DEFAULT '{}';
