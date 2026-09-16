-- Migration 032: drop the tables from before experts existed.
--
-- `books`, `chunks`, `specialties`, `specialty_books` and `api_keys` are
-- created by 001, 002 and 006 and referenced by nothing in `src/` — the corpus
-- has lived in `sources` and `source_chunks` since 007. Every fresh database
-- still got all five, and every reader of the migration directory had to work
-- out for themselves which half of it was dead.
--
-- 001 also builds an HNSW index on `chunks.embedding` that (per 019's own
-- comment) never worked at 3,072 dimensions, so it has been a cost with no
-- benefit on every rebuild since.
--
-- The old files stay. `apply.py` is filename-keyed, so re-running them on an
-- existing database is a no-op, and rewriting history to pretend the tables
-- never existed would make 003's `ALTER TABLE books` unreadable.
--
-- The guard below is the point of doing this as a migration rather than by
-- hand: this file runs as the release command against production, and a DROP
-- that takes data with it must not be possible. If any of the five holds a row,
-- the release aborts and says which — nothing is dropped, and the deploy stops
-- before any machine is updated.

DO $$
DECLARE
    tbl TEXT;
    rows_found BIGINT;
    populated TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOREACH tbl IN ARRAY ARRAY['books', 'chunks', 'specialties', 'specialty_books', 'api_keys']
    LOOP
        IF to_regclass('public.' || tbl) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('SELECT count(*) FROM public.%I', tbl) INTO rows_found;
        IF rows_found > 0 THEN
            populated := populated || format('%s (%s rows)', tbl, rows_found);
        END IF;
    END LOOP;

    IF array_length(populated, 1) > 0 THEN
        RAISE EXCEPTION
            'Refusing to drop legacy tables that still hold data: %. '
            'Nothing was dropped. Export what matters, empty them, and redeploy.',
            array_to_string(populated, ', ');
    END IF;
END $$;

-- CASCADE takes the indexes and the specialty_books foreign keys with them.
DROP TABLE IF EXISTS specialty_books CASCADE;
DROP TABLE IF EXISTS specialties CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS books CASCADE;
DROP TABLE IF EXISTS api_keys CASCADE;
