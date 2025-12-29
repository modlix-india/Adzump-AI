-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Collections
CREATE TABLE IF NOT EXISTS rag_collections
(
    id          UUID PRIMARY KEY     DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Documents
CREATE TABLE IF NOT EXISTS rag_documents
(
    id            UUID PRIMARY KEY     DEFAULT gen_random_uuid(),
    collection_id UUID        NOT NULL REFERENCES rag_collections (id) ON DELETE CASCADE,
    external_id   TEXT,
    uri           TEXT,
    source        TEXT,
    sha256        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (collection_id, external_id)
);

-- Chunks with embeddings
CREATE TABLE IF NOT EXISTS rag_chunks
(
    id          UUID PRIMARY KEY     DEFAULT gen_random_uuid(),
    document_id UUID        NOT NULL REFERENCES rag_documents (id) ON DELETE CASCADE,
    ord         INT         NOT NULL, -- order of chunk in the doc
    content     TEXT        NOT NULL,
    metadata    JSONB                DEFAULT '{}'::jsonb,
    tokens      INT,
    embedding   VECTOR(1536),         -- dimension must match your model
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, ord)
);

-- Similarity index (IVFFLAT). Requires ANALYZE after insertions for best performance.
-- Choose cosine distance ops if your embeddings are normalized (recommended).
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_ivfflat
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Full-text search support
CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON rag_chunks USING GIN (to_tsvector('english'::regconfig, content));

-- Helpful foreign-key indexes
CREATE INDEX IF NOT EXISTS idx_docs_collection ON rag_documents (collection_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON rag_chunks (document_id);