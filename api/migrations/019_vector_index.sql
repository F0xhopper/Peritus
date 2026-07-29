-- Migration 019: give source_chunks.embedding a usable ANN index.
--
-- Migration 005 attempted `USING hnsw (embedding vector_cosine_ops)` inside a
-- DO block that swallows failures, with a NOTICE explaining that HNSW tops out
-- at 2000 dimensions. The corpus is embedded at 3072, so that CREATE INDEX has
-- always failed and the table has always had *no* vector index: every semantic
-- search sorts by exact distance over every chunk the expert owns, and a chat
-- turn runs four to six of those concurrently.
--
-- pgvector 0.7 added `halfvec`, whose HNSW support goes to 4000 dimensions. The
-- index below is on the *expression* `embedding::halfvec(n)`, so nothing about
-- how embeddings are stored or returned changes — the column stays full-precision
-- `vector(n)` and existing rows are untouched. SearchService orders by the same
-- expression (see search/service.py::_distance_expr), which is what lets the
-- planner use this index.
--
-- Half precision is the right trade here: this ranks *candidates* that a
-- cross-encoder reranks afterwards, and 3072 dimensions of fp16 preserve cosine
-- ordering far more tightly than the reranking that follows can distinguish.
--
-- Portability: on pgvector < 0.7 there is no halfvec type, the block below is
-- skipped with a NOTICE, and the query layer falls back to the plain `vector`
-- expression (unindexed, exactly as today). Nothing breaks; it just stays slow
-- until pgvector is upgraded.

DO $$
DECLARE
    dim int;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'halfvec') THEN
        RAISE NOTICE 'pgvector predates halfvec (0.7.0) — skipping HNSW index; semantic search will keep using exact scans. Upgrade pgvector and re-run this migration.';
        RETURN;
    END IF;

    -- Read the dimension off the column rather than hardcoding 3072, so a
    -- deployment that changed EMBED_DIM still gets a matching index.
    SELECT atttypmod INTO dim
    FROM pg_attribute
    WHERE attrelid = 'source_chunks'::regclass AND attname = 'embedding';

    IF dim IS NULL OR dim <= 0 THEN
        RAISE NOTICE 'source_chunks.embedding has no declared dimension — skipping HNSW index.';
        RETURN;
    END IF;

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_source_chunks_hnsw_halfvec '
        'ON source_chunks USING hnsw ((embedding::halfvec(%s)) halfvec_cosine_ops)',
        dim
    );
    RAISE NOTICE 'Created idx_source_chunks_hnsw_halfvec on % dimensions.', dim;
END $$;

-- The keyword arm of hybrid search always filters by expert_id before matching
-- the tsquery. A GIN index over (expert_id, fts) lets one bitmap scan satisfy
-- both, instead of scanning every expert's postings and filtering afterwards.
-- btree_gin supplies the int4 opclass GIN needs for the scalar column.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS btree_gin;
    CREATE INDEX IF NOT EXISTS idx_source_chunks_expert_fts
        ON source_chunks USING gin (expert_id, to_tsvector('english', text));
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Composite expert_id+FTS index skipped (%); the single-column FTS index still applies.', SQLERRM;
END $$;

-- The old, never-created index name from migration 005. Dropped defensively in
-- case a deployment on a build with a raised dimension limit did create it —
-- two ANN indexes on one column would just make the planner choose badly.
DROP INDEX IF EXISTS idx_source_chunks_hnsw;

-- hnsw.iterative_scan is a CORRECTNESS setting for this schema, because every
-- semantic search filters by expert_id and an HNSW index cannot carry that
-- filter. With the default `off`, a filtered scan stops after one ef_search
-- pass and silently returns however few rows survived the filter — measured
-- here at 40 rows returned for an expert owning 184 chunks.
--
-- Set it at database level where permissions allow, so every backend inherits
-- it. On managed Postgres (Supabase) this is refused to non-superusers, which
-- is why SearchService._hybrid_search also issues `SET LOCAL` inside the
-- query's own transaction — the only scope that survives a transaction pooler.
-- Applying it here as well is free and removes the need for that on
-- self-hosted deployments.
DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET hnsw.iterative_scan = relaxed_order', current_database()
    );
    RAISE NOTICE 'Set hnsw.iterative_scan = relaxed_order on database %.', current_database();
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not set hnsw.iterative_scan at database level (%) — the retrieval path sets it per transaction instead.', SQLERRM;
END $$;
