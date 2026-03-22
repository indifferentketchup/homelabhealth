-- boolab — full schema (DB_SCHEMA.md). Table order respects foreign keys.

CREATE TABLE IF NOT EXISTS daws (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    icon_url TEXT,
    color TEXT DEFAULT '#7c3aed',
    shared BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    pinned_booops BOOLEAN DEFAULT FALSE,
    pinned_808notes BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    icon_url TEXT,
    system_prompt TEXT NOT NULL,
    default_model TEXT,
    web_search_enabled BOOLEAN DEFAULT FALSE,
    rag_enabled BOOLEAN DEFAULT TRUE,
    is_default_booops BOOLEAN DEFAULT FALSE,
    is_default_808notes BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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
    mode TEXT NOT NULL CHECK (mode IN ('booops', '808notes')),
    persona_id UUID REFERENCES personas(id) ON DELETE SET NULL,
    model TEXT NOT NULL DEFAULT 'qwen3.5:35b',
    web_search_enabled BOOLEAN DEFAULT FALSE,
    rag_enabled BOOLEAN DEFAULT TRUE,
    pruning_summary TEXT,
    message_count INTEGER DEFAULT 0,
    is_main_chat BOOLEAN DEFAULT FALSE,
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_source_selections (
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (chat_id, source_id)
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

CREATE TABLE IF NOT EXISTS branding_config (
    mode TEXT PRIMARY KEY CHECK (mode IN ('booops', '808notes', 'boolab')),
    config JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chats_daw_id_idx ON chats(daw_id);
CREATE INDEX IF NOT EXISTS chats_mode_idx ON chats(mode);
CREATE INDEX IF NOT EXISTS chats_updated_at_idx ON chats(updated_at DESC);
CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages(chat_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages(created_at);
CREATE INDEX IF NOT EXISTS sources_daw_id_idx ON sources(daw_id);
CREATE INDEX IF NOT EXISTS sources_embedding_status_idx ON sources(embedding_status);
CREATE INDEX IF NOT EXISTS notes_daw_id_idx ON notes(daw_id);

INSERT INTO global_settings (key, value) VALUES ('pruning_threshold', '40')
ON CONFLICT (key) DO NOTHING;
