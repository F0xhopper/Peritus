ALTER TABLE experts
    ADD COLUMN tier   VARCHAR(16) NOT NULL DEFAULT 'standard',
    ADD COLUMN config JSONB       NOT NULL DEFAULT '{}';
