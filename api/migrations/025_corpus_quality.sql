-- Migration 025: source identity, full-text provenance, review provenance, and
-- the discovery loop's own summary.
--
-- Four things the pipeline already knew and had nowhere to write down.
--
-- 1. IDENTITY. Fetchers receive DOIs, arXiv ids, PMIDs, PMCIDs and OpenAlex ids
--    from the APIs they call, and every one of them ended up in a free-form
--    `metadata` dict that this table has no column for — so a DOI never reached
--    the database at all. Without it, the same paper arriving as an arXiv
--    preprint, a journal DOI and a Semantic Scholar OA PDF is three rows, paid
--    for three times, competing with itself at retrieval. It also makes the RIS
--    export weak for exactly the users it is for: a reference manager wants a
--    DOI, and a record without one is a record a reviewer has to look up again.
--
-- 2. FULL-TEXT PROVENANCE. `full_text_method` says how a source's text was
--    obtained — ar5iv HTML, Europe PMC JATS, OCR of a PDF, a landing page, or
--    just the abstract — and `text_chars` says how much of it there was. Both
--    are the first questions a reviewer asks about a corpus, and neither was
--    answerable.
--
-- 3. REVIEW PROVENANCE. Sources scored near the accept/reject threshold get a
--    second opinion from a stronger model, and that verdict replaces the first.
--    Keeping both is what makes the decision reviewable: `validator_model` is
--    whose verdict stands, `review_model` says a reviewer was involved, and the
--    first-pass scores say what it changed.
--
-- 4. BUILD SUMMARY. Discovery now iterates and stops for a stated reason. That
--    reason, the round count and the final coverage table belong with the
--    expert, not only in an event log that may be pruned.
--
-- Every column is nullable and nothing is backfilled. A row written before this
-- migration genuinely does not know its DOI or how its text was fetched, and
-- inventing a value would put a fabrication into the provenance record.
-- `rubric_version` already says which rubric produced a row.

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS doi                   TEXT,
    ADD COLUMN IF NOT EXISTS arxiv_id              TEXT,
    ADD COLUMN IF NOT EXISTS identifiers           JSONB,
    ADD COLUMN IF NOT EXISTS full_text_method      TEXT,
    ADD COLUMN IF NOT EXISTS text_chars            INTEGER,
    ADD COLUMN IF NOT EXISTS review_model          TEXT,
    ADD COLUMN IF NOT EXISTS first_pass_quality    REAL,
    ADD COLUMN IF NOT EXISTS first_pass_relevance  REAL,
    -- Which accepted sources' citations led here, by URL. The "reference trail"
    -- the corpus report can only half draw without it.
    ADD COLUMN IF NOT EXISTS snowball_seed_urls    JSONB;

-- The dedup read: "has this expert already got this work?", asked once per
-- candidate during a build. Partial so the index carries only rows that have an
-- identifier, which before this migration is none of them.
CREATE INDEX IF NOT EXISTS idx_sources_expert_doi
    ON sources (expert_id, doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_expert_arxiv
    ON sources (expert_id, arxiv_id) WHERE arxiv_id IS NOT NULL;

ALTER TABLE experts
    -- What the discovery loop did and why it stopped: rounds, stop reason,
    -- accepted/rejected counts, spend against budget, and the final per-concept
    -- coverage table. Read by the audit surface, and the seed of the
    -- living-review follow-on, where a rebuild starts from the last build's
    -- summary instead of from nothing.
    ADD COLUMN IF NOT EXISTS build_summary JSONB;
