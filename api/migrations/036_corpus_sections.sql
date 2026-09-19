-- Migration 036: section summaries, as a routing index for broad questions.
--
-- Every question used to get the same retrieval: the top chunks by hybrid search
-- and rerank. That is the right shape for "what does Aquinas say about X" and
-- the wrong one for "who mattered most" or "how did this change over the
-- period", which need the corpus seen from above — and nothing held that view
-- (docs/plans/beating-closed-book.md §3.4, phase 4).
--
-- One row per section: a run of consecutive chunks of one source sharing a
-- heading, with ~120 words on what it establishes and an embedding of that. A
-- broad question searches these, takes the best sections across distinct
-- sources, and seats each one's best chunks. The summary routes; it is never
-- shown to the answering model or cited. Summaries find, passages prove.
--
-- Small (a few hundred rows per expert), so no vector index: a filtered scan of
-- one expert's rows is cheaper than an HNSW graph on a 500 MB database.

CREATE TABLE IF NOT EXISTS corpus_sections (
    id          SERIAL PRIMARY KEY,
    expert_id   INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    section     TEXT NOT NULL DEFAULT '',
    seq_start   INTEGER NOT NULL,
    seq_end     INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    embedding   vector(3072),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_corpus_sections_expert ON corpus_sections (expert_id);
