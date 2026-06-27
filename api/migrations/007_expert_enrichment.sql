-- Migration 007: Persist key concepts generated during the research plan stage

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS key_concepts JSONB NOT NULL DEFAULT '[]';
