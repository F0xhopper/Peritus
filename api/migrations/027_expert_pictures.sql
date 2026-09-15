-- Migration 027: a found, licensed picture of what each expert is *about*.
--
-- Migration 026 gave an expert a rendering *recipe* — a generator, a seed and a
-- hue — and NULL meant "derive a monogram from the persona name". This table
-- adds a third thing to draw: a real image of the subject, found on Wikimedia
-- during the build, stored with its licence and its provenance.
--
-- **The precedence, and why it is three levels rather than two.**
--
--     experts.avatar (the owner's recipe)  →  expert_pictures  →  derived sigil
--
-- 026's contract — "a non-null `avatar` is a choice the owner made and is
-- authoritative from then on" — stays exactly true, because the build writes
-- *here* and never to `experts.avatar`. That is the whole reason this is a
-- separate table and not a seventh avatar style: a style written by the builder
-- would be indistinguishable from a style chosen by a person, and the next
-- build would overwrite someone's decision.
--
-- **Why the bytes are in Postgres.** The same reasoning as source uploads
-- (021): one 30–150 KB thumbnail per expert is not worth an object store, a CDN
-- and a second set of credentials, and hotlinking upload.wikimedia.org would
-- put a third-party request in every user's browser, break when a file is
-- renamed on Commons, and lean on a service that asks not to be hotlinked at
-- volume. `GET /experts` never selects `image`; only the one endpoint that
-- serves the bytes does.
--
-- **What is not here.** No hue: colour is chosen, never derived, so a dominant
-- colour pulled out of a JPEG would be a hue nobody picked. No second size: the
-- Wikimedia thumbnail service already produced the width we ask for and the
-- client crops square with `object-fit: cover`.
--
-- `candidates` is metadata only — title, file name, thumbnail URL, licence,
-- artist — for the picker's "find another", never bytes.
--
-- Deletion cascades from `experts`. `ExpertRepository.reset_build_state` does
-- *not* touch this table: a rebuild re-searches the corpus, but the topic has
-- not changed and the owner may have chosen this picture, so only an explicit
-- refresh re-finds.

CREATE TABLE IF NOT EXISTS expert_pictures (
    expert_id      INTEGER PRIMARY KEY REFERENCES experts(id) ON DELETE CASCADE,
    image          BYTEA        NOT NULL,
    content_type   TEXT         NOT NULL,
    width          INTEGER      NOT NULL,
    height         INTEGER      NOT NULL,
    byte_size      INTEGER      NOT NULL CHECK (byte_size > 0 AND byte_size <= 400000),
    sha256         TEXT         NOT NULL,
    provider       TEXT         NOT NULL CHECK (provider IN ('wikipedia', 'commons', 'openverse')),
    file_name      TEXT,                          -- 'File:Zeno_of_Citium.jpg'
    file_url       TEXT         NOT NULL,         -- the thumbnail that was fetched
    file_page_url  TEXT         NOT NULL,         -- where the licence is stated
    page_url       TEXT,                          -- the article it illustrates
    page_title     TEXT,
    artist         TEXT,
    license        TEXT         NOT NULL,
    license_url    TEXT,
    query          TEXT,                          -- the query that found it
    candidates     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    chosen_by      TEXT         NOT NULL DEFAULT 'build' CHECK (chosen_by IN ('build', 'owner')),
    found_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- The backfill walks experts that have no picture yet; this keeps that a plain
-- anti-join rather than a sequential scan of the blob table.
CREATE INDEX IF NOT EXISTS idx_expert_pictures_found_at
    ON expert_pictures (found_at DESC);
