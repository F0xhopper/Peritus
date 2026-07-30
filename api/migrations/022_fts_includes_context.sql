-- Make the keyword arm of hybrid search see the contextual prefixes.
--
-- The ingestion pipeline generates an Anthropic-style contextual prefix for
-- every chunk (a real per-chunk Claude cost) and stores it in
-- `source_chunks.context_text`. The semantic arm has always seen it: the
-- pipeline embeds `context_text + text` together. The keyword arm never did —
-- both the index and the query used `to_tsvector('english', text)` alone.
--
-- So the prefix was paid for, generated, embedded and stored, and then half the
-- retrieval pipeline was structurally unable to match on it. The contextual
-- prefix is exactly the text that carries the disambiguating nouns a keyword
-- query is most likely to use ("in the 2019 UK cohort study…"), which is the
-- half that most wanted it.
--
-- Migration 004 got this right on the legacy `chunks` table
-- (`coalesce(context,'') || ' ' || text`); the newer `source_chunks` table
-- dropped it. This restores it.
--
-- The index expression and both query sites in SearchService._hybrid_search must
-- match byte-for-byte or the planner will not use the index — keep them in sync.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS btree_gin;
    CREATE INDEX IF NOT EXISTS idx_source_chunks_expert_fts_ctx
        ON source_chunks USING gin (
            expert_id,
            to_tsvector('english', coalesce(context_text, '') || ' ' || text)
        );
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Composite expert_id+context FTS index skipped (%).', SQLERRM;
END $$;

-- Single-column fallback for planners that decline the composite index.
CREATE INDEX IF NOT EXISTS idx_source_chunks_fts_ctx
    ON source_chunks USING gin (
        to_tsvector('english', coalesce(context_text, '') || ' ' || text)
    );

-- The text-only indexes are now dead weight: no query references that
-- expression any more, and each one still costs an update on every chunk write.
DROP INDEX IF EXISTS idx_source_chunks_expert_fts;
DROP INDEX IF EXISTS idx_source_chunks_fts;
