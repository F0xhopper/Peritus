-- Migration 005: Peritus schema — experts, sources, source_chunks, property graph

CREATE TABLE IF NOT EXISTS experts (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    topic           TEXT NOT NULL,
    persona_name    TEXT,
    persona_bio     TEXT,
    persona_style   TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'building',
    source_count    INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    node_count      INTEGER NOT NULL DEFAULT 0,
    edge_count      INTEGER NOT NULL DEFAULT 0,
    avg_quality     REAL,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experts_name ON experts (lower(name));
CREATE INDEX IF NOT EXISTS idx_experts_name_trgm ON experts USING gin (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS sources (
    id              SERIAL PRIMARY KEY,
    expert_id       INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    source_type     VARCHAR(20) NOT NULL,
    url             TEXT,
    title           TEXT NOT NULL,
    author          TEXT,
    quality_score   REAL,
    relevance_score REAL,
    content_type    VARCHAR(50),
    difficulty      INTEGER,
    key_claims      JSONB,
    passed          BOOLEAN NOT NULL,
    drop_reason     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sources_expert_passed ON sources (expert_id, passed);

CREATE TABLE IF NOT EXISTS source_chunks (
    id              SERIAL PRIMARY KEY,
    expert_id       INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    sequence_n      INTEGER NOT NULL,
    text            TEXT NOT NULL,
    context_text    TEXT,
    embedding       vector(3072),
    chunk_meta      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW supports ≤2000 dims in standard pgvector builds; Supabase supports 3072.
-- We attempt HNSW and silently fall back so the migration is portable.
DO $$ BEGIN
    BEGIN
        CREATE INDEX idx_source_chunks_hnsw
            ON source_chunks USING hnsw (embedding vector_cosine_ops);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'HNSW index skipped (dimension limit): %; vector search will use sequential scan until index is added manually.', SQLERRM;
    END;
END $$;
CREATE INDEX IF NOT EXISTS idx_source_chunks_fts
    ON source_chunks USING gin (to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS idx_source_chunks_expert ON source_chunks (expert_id);
CREATE INDEX IF NOT EXISTS idx_source_chunks_source ON source_chunks (source_id);

CREATE TABLE IF NOT EXISTS expert_nodes (
    id          SERIAL PRIMARY KEY,
    expert_id   INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    node_type   VARCHAR(20) NOT NULL,
    label       TEXT NOT NULL,
    description TEXT,
    properties  JSONB,
    chunk_ids   INTEGER[],
    embedding   vector(3072)
);

CREATE INDEX IF NOT EXISTS idx_expert_nodes_expert ON expert_nodes (expert_id, node_type);

CREATE TABLE IF NOT EXISTS expert_edges (
    id              SERIAL PRIMARY KEY,
    expert_id       INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    from_node_id    INTEGER NOT NULL REFERENCES expert_nodes(id) ON DELETE CASCADE,
    to_node_id      INTEGER NOT NULL REFERENCES expert_nodes(id) ON DELETE CASCADE,
    edge_type       VARCHAR(30) NOT NULL,
    weight          REAL NOT NULL DEFAULT 1.0,
    properties      JSONB
);

CREATE INDEX IF NOT EXISTS idx_expert_edges_expert ON expert_edges (expert_id);
CREATE INDEX IF NOT EXISTS idx_expert_edges_from   ON expert_edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_expert_edges_to     ON expert_edges (to_node_id);
