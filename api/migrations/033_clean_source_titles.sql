-- Migration 033: clean the titles already in `sources`.
--
-- Titles are stored as the fetcher gave them, and three things came with them:
-- HTML entities and tags printed literally
-- (`The symbiotic bacteria &lt;i&gt;Frischella perrara&lt;/i&gt;`), catalogue
-- metadata in full capitals (`LANGSTROTH ON THE HIVE AND THE HONEY-BEE`), and
-- stray whitespace from scraped pages. A title is read on the Sources page, on
-- every citation an answer makes, and in the RIS a reader takes to Zotero, so
-- this is not cosmetic.
--
-- `peritus.sources.titles.clean_title` does the same work for every new source
-- at the moment it enters the system (it runs in `RawSource.__post_init__`);
-- this file is the one-off for rows written before it existed. The two agree on
-- the rules, including the small-word list — a title cleaned here and one
-- cleaned there must not differ, or the same work would appear twice in a
-- corpus under two spellings.
--
-- Nothing is truncated and no row is deleted: every statement below rewrites a
-- title in place, and a title that is already well-formed is left untouched.

BEGIN;

-- Entities first, then tags: `&lt;i&gt;` has to become `<i>` before the tag
-- stripper can see it. Twice, because a field escaped by an API that had
-- already escaped it arrives as `&amp;lt;`.
CREATE OR REPLACE FUNCTION pg_temp.unescape_once(t TEXT) RETURNS TEXT AS $$
    SELECT replace(replace(replace(replace(replace(replace(replace(
             t, '&amp;', '&'), '&lt;', '<'), '&gt;', '>'),
             '&quot;', '"'), '&#39;', ''''), '&apos;', ''''), '&nbsp;', ' ')
$$ LANGUAGE SQL IMMUTABLE;

-- The small words that stay lowercase inside a de-shouted title. Kept in step
-- with `_SMALL_WORDS` in `sources/titles.py`.
CREATE OR REPLACE FUNCTION pg_temp.title_case(t TEXT) RETURNS TEXT AS $$
    SELECT string_agg(
        CASE
            WHEN ord > 1
             AND ord < (SELECT count(*) FROM regexp_split_to_table(t, '\s+'))
             AND lower(btrim(w, ',.;:')) = ANY (ARRAY[
                 'a','an','the','and','or','nor','but','for','so','yet','at','by',
                 'in','of','on','to','up','via','with','from','into','onto','over',
                 'under','as','if','is','it','its'])
            THEN lower(w)
            ELSE initcap(w)
        END, ' ' ORDER BY ord)
    FROM regexp_split_to_table(t, '\s+') WITH ORDINALITY AS parts(w, ord)
$$ LANGUAGE SQL IMMUTABLE;

-- 1. Entities, tags and whitespace, for every row that has any of them.
UPDATE sources
   SET title = btrim(regexp_replace(
                   regexp_replace(
                       pg_temp.unescape_once(pg_temp.unescape_once(title)),
                       '<[^>]{1,120}>', ' ', 'g'),
                   '\s+', ' ', 'g'))
 WHERE title IS NOT NULL
   AND (title ~ '&[a-z]{2,6};' OR title ~ '&#[0-9]{2,5};' OR title ~ '<[^>]{1,120}>'
        OR title ~ '\s\s' OR title ~ '^\s' OR title ~ '\s$');

-- 2. Shouting. The guard is "every letter is a capital and there are at least
--    twelve of them", so `The ABC and XYZ of Bee Culture` and a bare `DWV` are
--    both left exactly as they are — the same test the Python does.
UPDATE sources
   SET title = pg_temp.title_case(title)
 WHERE title IS NOT NULL
   AND title = upper(title)
   AND length(regexp_replace(title, '[^A-Za-z]', '', 'g')) >= 12;

COMMIT;
