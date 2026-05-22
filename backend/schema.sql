-- HomeLab Health — full schema (DB_SCHEMA.md). Table order respects foreign keys.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    icon_url TEXT,
    color TEXT DEFAULT '#7c3aed',
    shared BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    pinned BOOLEAN DEFAULT FALSE,
    model TEXT,
    rag_mode TEXT NOT NULL DEFAULT 'auto',
    system_prompt TEXT NOT NULL DEFAULT '',
    owner_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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

-- FK back-references now that users exist
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;

UPDATE users SET display_name = username WHERE display_name IS NULL OR btrim(display_name) = '';
UPDATE users SET bio = COALESCE(bio, '') WHERE bio IS NULL;
UPDATE users SET avatar_emoji = COALESCE(NULLIF(trim(avatar_emoji), ''), '👤') WHERE avatar_emoji IS NULL;

CREATE TABLE IF NOT EXISTS source_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (workspace_id, name)
);

CREATE TABLE IF NOT EXISTS note_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (workspace_id, name)
);

CREATE TABLE IF NOT EXISTS workspace_context_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    file_url TEXT,
    embeddable BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
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

-- Personas removal (one-time destructive migration; idempotent on subsequent re-applies).
ALTER TABLE chats DROP COLUMN IF EXISTS persona_id;
ALTER TABLE workspaces DROP COLUMN IF EXISTS persona_id;
DROP TABLE IF EXISTS personas CASCADE;

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

-- B0 safeguards: stamp the active safeguard prompt version on every assistant
-- message write. NULL for pre-B0 historical rows; populated values copy verbatim
-- on fork (see fork_chat_at_message in routers/chats.py).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS safeguard_version TEXT;

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
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
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
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
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE custom_instructions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
UPDATE custom_instructions SET updated_at = COALESCE(updated_at, created_at, NOW()) WHERE updated_at IS NULL;

CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS chats_workspace_id_idx ON chats(workspace_id);
CREATE INDEX IF NOT EXISTS chats_updated_at_idx ON chats(updated_at DESC);
CREATE INDEX IF NOT EXISTS chats_owner_id_idx ON chats(owner_id);
CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages(chat_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages(created_at);
CREATE INDEX IF NOT EXISTS sources_workspace_id_idx ON sources(workspace_id);
CREATE INDEX IF NOT EXISTS sources_embedding_status_idx ON sources(embedding_status);
CREATE INDEX IF NOT EXISTS notes_workspace_id_idx ON notes(workspace_id);
CREATE INDEX IF NOT EXISTS workspaces_owner_id_idx ON workspaces(owner_id);

-- Global settings seed
INSERT INTO global_settings (key, value) VALUES ('pruning_threshold', '40')
ON CONFLICT (key) DO NOTHING;

INSERT INTO global_settings (key, value) VALUES ('ollama_hidden_models', '[]') ON CONFLICT (key) DO NOTHING;

INSERT INTO global_settings (key, value) VALUES
  ('rag_similarity_threshold', '0.35'),
  ('memory_similarity_threshold', '0.45')
ON CONFLICT (key) DO NOTHING;

-- Single markdown blob for freeform notes; enforced as singleton.
CREATE TABLE IF NOT EXISTS mode_memory (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS mode_memory_singleton_idx ON mode_memory ((1));

-- RAG chunk storage + upload metadata
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

-- Ollama host hints
CREATE TABLE IF NOT EXISTS ollama_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO ollama_config (key, value) VALUES
    ('flash_attention', '1'),
    ('max_loaded_models', '1'),
    ('keep_alive', '30m')
ON CONFLICT (key) DO NOTHING;

-- SearXNG search settings (singleton row; enforced via unique index on constant expression)
CREATE TABLE IF NOT EXISTS searxng_config (
    id SERIAL PRIMARY KEY,
    safe_search INTEGER NOT NULL DEFAULT 0 CHECK (safe_search IN (0, 1, 2)),
    image_proxy BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_engines TEXT NOT NULL DEFAULT '',
    autocomplete TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS searxng_config_singleton_idx ON searxng_config ((1));

-- Drop legacy constraint from old multi-mode schema if present on existing DBs.
ALTER TABLE searxng_config DROP CONSTRAINT IF EXISTS searxng_config_mode_check;

-- Seed sensible defaults for the bundled SearXNG sidecar on first boot.
-- Engines list matches AVAILABLE_ENGINES in SearchSettingsTab.jsx; subset
-- enabled by default to keep result pages tidy. Operator can toggle in UI.
INSERT INTO searxng_config (id, safe_search, image_proxy, enabled_engines, autocomplete)
SELECT 1, 0, FALSE, 'wikipedia,brave,mojeek,startpage,arxiv,pubmed', ''
 WHERE NOT EXISTS (SELECT 1 FROM searxng_config);

CREATE TABLE IF NOT EXISTS workspace_memory (
    id SERIAL PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS workspace_memory_workspace_id_idx ON workspace_memory(workspace_id);

CREATE UNIQUE INDEX IF NOT EXISTS custom_instructions_singleton_idx ON custom_instructions ((1));

-- ────────────────────────────────────────────────────────────────────────────
-- Providers + per-workspace provider binding (added 2026-05-21).
-- Replaces env-var-only OPENAI_API_KEY / *_URL config. See
-- docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md
-- ────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    api_key TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    last_verified_at TIMESTAMPTZ,
    last_verified_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS providers_enabled_sort_idx
    ON providers (enabled, sort_order, created_at);

ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS provider_id UUID REFERENCES providers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS workspaces_provider_id_idx
    ON workspaces (provider_id);

-- Pre-clean any rows that would violate the new CHECK constraint (drop-cold upgrade).
-- Effectively a no-op on subsequent re-applies.
UPDATE workspaces
   SET model = NULL
 WHERE provider_id IS NULL
   AND model IS NOT NULL
   AND model <> '';

-- Guarded CHECK so re-running schema.sql doesn't error if already present.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'workspaces_provider_model_paired'
    ) THEN
        ALTER TABLE workspaces
            ADD CONSTRAINT workspaces_provider_model_paired
            CHECK ((provider_id IS NULL AND (model IS NULL OR model = ''))
                OR (provider_id IS NOT NULL AND model IS NOT NULL AND model <> ''));
    END IF;
END $$;

-- ────────────────────────────────────────────────────────────────────────────
-- Bundled-system takes everything (2026-05-22). See:
-- docs/superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md
-- ────────────────────────────────────────────────────────────────────────────

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS is_bundled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS role TEXT;  -- 'chat' | 'embed' | 'rerank' | NULL (general-purpose external)

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS bundle_group TEXT;  -- 'homelab-health-ai' for bundled rows; NULL otherwise

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'providers_role_check'
    ) THEN
        ALTER TABLE providers
            ADD CONSTRAINT providers_role_check
            CHECK (role IN ('chat', 'embed', 'rerank'));
    END IF;
END $$;

-- Backfill the existing bundled-chat row on first apply. Guarded so subsequent
-- applies are no-ops. Order-safe: this runs in schema.sql before
-- ensure_bundled_providers in lifespan; IN-clause handles both legacy + post-rename names.
UPDATE providers
   SET is_bundled = TRUE,
       role = 'chat',
       bundle_group = 'homelab-health-ai'
 WHERE is_bundled = FALSE
   AND name IN ('bundled-chat', 'HomeLab Health AI · Chat');

CREATE TABLE IF NOT EXISTS hf_token_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    token_encrypted TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'hf_token_config'
           AND column_name = 'token_encrypted'
           AND data_type = 'bytea'
    ) THEN
        ALTER TABLE hf_token_config
            ALTER COLUMN token_encrypted TYPE TEXT
            USING CASE WHEN token_encrypted IS NULL THEN NULL ELSE convert_from(token_encrypted, 'UTF8') END;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'hf_token_config_id_check'
    ) THEN
        ALTER TABLE hf_token_config
            ADD CONSTRAINT hf_token_config_id_check
            CHECK (id = 1);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS hf_token_config_singleton_idx
    ON hf_token_config ((1));

-- chats.model becomes nullable post-providers: the workspace's (provider_id, model)
-- pair is the authoritative source for sends, so chat.model is now informational.
-- Existing rows with the legacy hardcoded default 'qwen3.5:9b' are harmless —
-- send-time always re-resolves via the workspace. Idempotent: re-running is a no-op
-- once the column is already nullable / has no default.
ALTER TABLE chats ALTER COLUMN model DROP NOT NULL;
ALTER TABLE chats ALTER COLUMN model DROP DEFAULT;

-- ────────────────────────────────────────────────────────────────────────────
-- Phase 0: bundled-AI hardware detect + tier picker (singleton).
-- Spec: docs/hlh_phase0_design.md §Schema
-- IF NOT EXISTS added to satisfy dispatch hard rule #7 (idempotent re-apply);
-- design DDL is bare CREATE TABLE — flagged in 0.B report.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_profile (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tier            TEXT NOT NULL DEFAULT 'external',
    tier_source     TEXT NOT NULL CHECK (tier_source IN ('auto', 'manual')) DEFAULT 'manual',
    sysinfo_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_at     TIMESTAMPTZ,
    chosen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    setup_complete  BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO system_profile (id) VALUES (1) ON CONFLICT DO NOTHING;

-- A1.7: first-launch acknowledgement timestamp (2026-05-22).
ALTER TABLE system_profile ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;

-- ────────────────────────────────────────────────────────────────────────────
-- Phase 1: bundled-AI model artifacts + pull tracking.
-- Spec: hlh_phase1_design.md §Schema additions
-- One row per (role, tier, model_id, quant) combination, seeded from
-- services/model_puller.py:MODEL_REGISTRY at lifespan start.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bundled_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role            TEXT NOT NULL CHECK (role IN ('chat', 'embed', 'rerank', 'vision', 'medsiglip', 'stt', 'ocr')),
    tier            TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    quant           TEXT,
    repo            TEXT NOT NULL,
    filename        TEXT NOT NULL,
    expected_bytes  BIGINT,
    sha256          TEXT,
    license         TEXT,
    license_url     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'pulling', 'ready', 'failed', 'skipped'))
                    DEFAULT 'pending',
    pulled_bytes    BIGINT NOT NULL DEFAULT 0,
    error_message   TEXT,
    pull_started_at TIMESTAMPTZ,
    pull_finished_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role, tier, model_id, quant)
);

CREATE INDEX IF NOT EXISTS bundled_models_role_tier_idx ON bundled_models (role, tier);
CREATE INDEX IF NOT EXISTS bundled_models_status_idx ON bundled_models (status);

-- B2: HuggingFace git ref pinning (branch, tag, or commit SHA). NULL falls
-- back to 'main' in _hf_url; populated as 'main' for all Phase 1 chat specs.
ALTER TABLE bundled_models ADD COLUMN IF NOT EXISTS revision TEXT;
