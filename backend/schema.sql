-- homelabhealth — canonical schema (post-strip). Table order respects foreign keys. Applied idempotently on every startup.

CREATE TABLE IF NOT EXISTS daws (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    icon_url TEXT,
    color TEXT DEFAULT '#7c3aed',
    shared BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    pinned_808notes BOOLEAN DEFAULT FALSE,
    model TEXT,
    rag_mode TEXT NOT NULL DEFAULT 'auto',
    system_prompt TEXT NOT NULL DEFAULT '',
    persona_id UUID,
    owner_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    icon_url TEXT,
    system_prompt TEXT NOT NULL,
    web_search_enabled BOOLEAN DEFAULT FALSE,
    rag_enabled BOOLEAN DEFAULT TRUE,
    avatar_emoji TEXT DEFAULT '🤖',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    owner_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure is_default exists on live DBs upgraded from the old schema (idempotent).
ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;
-- Ensure avatar_emoji and updated_at exist on older live DBs.
ALTER TABLE personas ADD COLUMN IF NOT EXISTS avatar_emoji TEXT DEFAULT '🤖';
ALTER TABLE personas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Single-default uniqueness (partial index allows multiple FALSE).
CREATE UNIQUE INDEX IF NOT EXISTS idx_personas_default_one
    ON personas (is_default)
    WHERE is_default IS TRUE;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'super_admin', 'owner')),
    display_name TEXT,
    bio TEXT NOT NULL DEFAULT '',
    icon_url TEXT,
    avatar_emoji TEXT DEFAULT '👤',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- FK back-references now that users and personas exist
ALTER TABLE daws ADD COLUMN IF NOT EXISTS persona_id UUID REFERENCES personas(id) ON DELETE SET NULL;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;

UPDATE users SET display_name = username WHERE display_name IS NULL OR btrim(display_name) = '';
UPDATE users SET bio = COALESCE(bio, '') WHERE bio IS NULL;
UPDATE users SET avatar_emoji = COALESCE(NULLIF(trim(avatar_emoji), ''), '👤') WHERE avatar_emoji IS NULL;

CREATE TABLE IF NOT EXISTS source_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (daw_id, name)
);

CREATE TABLE IF NOT EXISTS note_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (daw_id, name)
);

CREATE TABLE IF NOT EXISTS daw_context_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    file_url TEXT,
    embeddable BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daw_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    daw_id UUID REFERENCES daws(id) ON DELETE SET NULL,
    persona_id UUID REFERENCES personas(id) ON DELETE SET NULL,
    model TEXT NOT NULL DEFAULT 'qwen3.5:9b',
    web_search_enabled BOOLEAN DEFAULT FALSE,
    rag_enabled BOOLEAN DEFAULT TRUE,
    pruning_summary TEXT,
    message_count INTEGER DEFAULT 0,
    is_main_chat BOOLEAN DEFAULT FALSE,
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    model TEXT,
    tokens_used INTEGER,
    sources_used JSONB,
    forked_from UUID REFERENCES messages(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    group_id UUID REFERENCES source_groups(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'pdf', 'docx', 'txt', 'csv', 'xlsx', 'html', 'md', 'url', 'code', 'note', 'bourbites'
    )),
    file_url TEXT,
    original_url TEXT,
    content_hash TEXT,
    chunk_count INTEGER DEFAULT 0,
    embedding_status TEXT DEFAULT 'pending' CHECK (embedding_status IN (
        'pending', 'processing', 'complete', 'error'
    )),
    error_message TEXT,
    mime_type TEXT,
    file_size_bytes INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_source_selections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         UUID REFERENCES chats(id) ON DELETE CASCADE NOT NULL,
    source_id       UUID REFERENCES sources(id) ON DELETE CASCADE NOT NULL,
    position        INTEGER NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(chat_id, source_id)
);

CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    group_id UUID REFERENCES note_groups(id) ON DELETE SET NULL,
    title TEXT,
    content TEXT NOT NULL,
    source_type TEXT DEFAULT 'manual' CHECK (source_type IN (
        'manual', 'ai_response', 'ai_summary'
    )),
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    converted_to_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notes_search_idx ON notes USING GIN(search_vector);

CREATE OR REPLACE FUNCTION notes_search_vector_update() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.title, '') || ' ' || coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS notes_search_vector_trigger ON notes;
CREATE TRIGGER notes_search_vector_trigger
    BEFORE INSERT OR UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION notes_search_vector_update();

CREATE TABLE IF NOT EXISTS memory_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'auto')),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    embedding vector(1024),
    embedded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS custom_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope TEXT NOT NULL CHECK (scope IN ('global', 'booops', '808notes')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (scope)
);

ALTER TABLE custom_instructions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
UPDATE custom_instructions SET updated_at = COALESCE(updated_at, created_at, NOW()) WHERE updated_at IS NULL;

CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE EXTENSION IF NOT EXISTS vector;

-- Indexes
CREATE INDEX IF NOT EXISTS chats_daw_id_idx ON chats(daw_id);
CREATE INDEX IF NOT EXISTS chats_updated_at_idx ON chats(updated_at DESC);
CREATE INDEX IF NOT EXISTS chats_owner_id_idx ON chats(owner_id);
CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages(chat_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages(created_at);
CREATE INDEX IF NOT EXISTS sources_daw_id_idx ON sources(daw_id);
CREATE INDEX IF NOT EXISTS sources_embedding_status_idx ON sources(embedding_status);
CREATE INDEX IF NOT EXISTS notes_daw_id_idx ON notes(daw_id);
CREATE INDEX IF NOT EXISTS personas_owner_id_idx ON personas(owner_id);
CREATE INDEX IF NOT EXISTS daws_owner_id_idx ON daws(owner_id);

-- Global settings seed
INSERT INTO global_settings (key, value) VALUES ('pruning_threshold', '40')
ON CONFLICT (key) DO NOTHING;

INSERT INTO global_settings (key, value) VALUES ('ollama_hidden_models', '[]') ON CONFLICT (key) DO NOTHING;

INSERT INTO global_settings (key, value) VALUES
  ('rag_similarity_threshold', '0.35'),
  ('memory_similarity_threshold', '0.45')
ON CONFLICT (key) DO NOTHING;

-- Phase 3: one markdown blob per mode (separate from memory_entries)
CREATE TABLE IF NOT EXISTS mode_memory (
    id SERIAL PRIMARY KEY,
    mode TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Live DBs that already have mode_memory with mode as PK: add id only; keep PRIMARY KEY on mode.
ALTER TABLE mode_memory ADD COLUMN IF NOT EXISTS id SERIAL;

-- Phase 5: RAG chunk storage + upload metadata
CREATE TABLE IF NOT EXISTS source_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS source_chunks_source_id_idx ON source_chunks(source_id);

-- HNSW indexes for cosine-distance ANN search (pgvector 0.5+).
-- Without these, every retrieval does a sequential scan over source_chunks / memory_entries.
CREATE INDEX IF NOT EXISTS source_chunks_embedding_hnsw
    ON source_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memory_entries_embedding_hnsw
    ON memory_entries USING hnsw (embedding vector_cosine_ops);

-- Ollama host hints (applied when syncing env / restarting Ollama on sam-desktop)
CREATE TABLE IF NOT EXISTS ollama_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO ollama_config (key, value) VALUES
    ('flash_attention', '1'),
    ('max_loaded_models', '1'),
    ('keep_alive', '30m')
ON CONFLICT (key) DO NOTHING;

-- SearXNG settings per app mode (API applies on each search; optional YAML sync via SEARXNG_SETTINGS_YML)
CREATE TABLE IF NOT EXISTS searxng_config (
    id SERIAL PRIMARY KEY,
    mode TEXT NOT NULL UNIQUE CHECK (mode IN ('booops', '808notes', 'boocode')),
    safe_search INTEGER NOT NULL DEFAULT 0 CHECK (safe_search IN (0, 1, 2)),
    image_proxy BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_engines TEXT NOT NULL DEFAULT '',
    autocomplete TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- BooCode Phase 4: widen searxng_config.mode to include boocode (idempotent on existing DBs).
ALTER TABLE searxng_config DROP CONSTRAINT IF EXISTS searxng_config_mode_check;
ALTER TABLE searxng_config ADD CONSTRAINT searxng_config_mode_check
    CHECK (mode IN ('booops', '808notes', 'boocode'));

CREATE TABLE IF NOT EXISTS daw_memory (
    id SERIAL PRIMARY KEY,
    daw_id UUID NOT NULL REFERENCES daws(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS daw_memory_daw_id_idx ON daw_memory(daw_id);
