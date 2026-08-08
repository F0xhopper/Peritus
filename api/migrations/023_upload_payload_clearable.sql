-- 023: make upload payloads clearable.
--
-- 021 promised that `content`/`text_content` are cleared once ingestion
-- succeeds (the text lives on as chunks), but its payload CHECK required the
-- payload to be present *forever* — so `clear_payload` violated the constraint
-- on every successful pdf/text ingest, the UPDATE failed, and the raw bytes of
-- every uploaded document were retained unboundedly.
--
-- `cleared_at` records the transition explicitly: a row must either still carry
-- the payload its kind implies, or say when it was cleared. Malformed inserts
-- (a pdf with no bytes, a url row with no url) still fail at insert, which is
-- the guarantee 021 actually wanted.

ALTER TABLE source_uploads
    ADD COLUMN IF NOT EXISTS cleared_at TIMESTAMPTZ;

ALTER TABLE source_uploads
    DROP CONSTRAINT IF EXISTS source_uploads_payload_check;

ALTER TABLE source_uploads
    ADD CONSTRAINT source_uploads_payload_check CHECK (
        cleared_at IS NOT NULL
     OR (kind = 'pdf'  AND content IS NOT NULL)
     OR (kind = 'text' AND text_content IS NOT NULL)
     OR (kind = 'url'  AND url IS NOT NULL)
    );
