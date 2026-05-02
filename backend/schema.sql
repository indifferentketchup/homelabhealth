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
    avatar_emoji TEXT DEFAULT '🤖',
    is_default_booops BOOLEAN DEFAULT FALSE,
    is_default_808notes BOOLEAN DEFAULT FALSE,
    is_default_boocode BOOLEAN DEFAULT FALSE,
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
    mode TEXT NOT NULL CHECK (mode IN ('booops', '808notes', 'boocode')),
    persona_id UUID REFERENCES personas(id) ON DELETE SET NULL,
    model TEXT NOT NULL DEFAULT 'qwen3.5:9b',
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
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         UUID REFERENCES chats(id) ON DELETE CASCADE NOT NULL,
    source_id       UUID REFERENCES sources(id) ON DELETE CASCADE NOT NULL,
    position        INTEGER NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(chat_id, source_id)
);

-- Skills system
CREATE TABLE IF NOT EXISTS skills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    source_url      TEXT,
    raw_content     TEXT NOT NULL,
    tags            TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daw_skills (
    daw_id          UUID REFERENCES daws(id) ON DELETE CASCADE NOT NULL,
    skill_id        UUID REFERENCES skills(id) ON DELETE CASCADE NOT NULL,
    active          BOOLEAN DEFAULT true,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (daw_id, skill_id)
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
    mode TEXT PRIMARY KEY CHECK (mode IN ('booops', '808notes', 'boolab', 'boocode')),
    config JSONB NOT NULL DEFAULT '{}'
);

-- BooCode: add mode value to CHECK constraint (idempotent)
DO $boocode_mode_chk$
BEGIN
    ALTER TABLE branding_config DROP CONSTRAINT IF EXISTS branding_config_mode_check;
    ALTER TABLE branding_config ADD CONSTRAINT branding_config_mode_check
        CHECK (mode IN ('booops', '808notes', 'boolab', 'boocode'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$boocode_mode_chk$;

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

INSERT INTO global_settings (key, value) VALUES ('ollama_hidden_models', '[]') ON CONFLICT (key) DO NOTHING;

INSERT INTO global_settings (key, value) VALUES
  ('rag_similarity_threshold', '0.35'),
  ('memory_similarity_threshold', '0.45'),
  ('rag_intent_gate_enabled', 'true'),
  ('rag_min_words_for_intent', '8')
ON CONFLICT (key) DO NOTHING;

-- Personas: ensure columns + unique-default indexes exist (idempotent).
ALTER TABLE personas ADD COLUMN IF NOT EXISTS avatar_emoji TEXT DEFAULT '🤖';
ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default_booops BOOLEAN DEFAULT FALSE;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default_808notes BOOLEAN DEFAULT FALSE;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS is_default_boocode BOOLEAN DEFAULT FALSE;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS personas_one_default_booops_idx ON personas ((1)) WHERE is_default_booops = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS personas_one_default_808notes_idx ON personas ((1)) WHERE is_default_808notes = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS personas_one_default_boocode_idx ON personas ((1)) WHERE is_default_boocode = TRUE;

-- Phase 3: one markdown blob per mode (separate from memory_entries)
CREATE TABLE IF NOT EXISTS mode_memory (
    id SERIAL PRIMARY KEY,
    mode TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Live DBs that already have mode_memory with mode as PK: add id only; keep PRIMARY KEY on mode.
ALTER TABLE mode_memory ADD COLUMN IF NOT EXISTS id SERIAL;

-- custom_instructions: track updates for API
ALTER TABLE custom_instructions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
UPDATE custom_instructions SET updated_at = COALESCE(updated_at, created_at, NOW()) WHERE updated_at IS NULL;

-- daws: mode/system_prompt/persona_id columns (idempotent)
ALTER TABLE daws ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'booops';
ALTER TABLE daws ADD COLUMN IF NOT EXISTS system_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE daws ADD COLUMN IF NOT EXISTS persona_id UUID REFERENCES personas(id) ON DELETE SET NULL;

DO $daw_mode_chk$
BEGIN
    ALTER TABLE daws ADD CONSTRAINT daws_mode_check CHECK (mode IN ('booops', '808notes', 'boocode'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$daw_mode_chk$;

CREATE INDEX IF NOT EXISTS daws_mode_idx ON daws(mode);

-- memory_entries: scope by app mode + soft delete (prompt assembly filters is_deleted)
ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'booops';
ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

DO $mem_mode_chk$
BEGIN
    ALTER TABLE memory_entries ADD CONSTRAINT memory_entries_mode_check CHECK (mode IN ('booops', '808notes'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$mem_mode_chk$;

-- Phase 04: semantic memory retrieval (same embedding dim as source_chunks)
ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedding vector(1024);
ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

-- Phase 5: RAG chunk storage + upload metadata
CREATE TABLE IF NOT EXISTS source_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS source_chunks_source_id_idx ON source_chunks(source_id);

CREATE EXTENSION IF NOT EXISTS vector;

-- pgvector migration: add embedding column to source_chunks
ALTER TABLE source_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- HNSW indexes for cosine-distance ANN search (pgvector 0.5+).
-- Without these, every retrieval does a sequential scan over source_chunks / memory_entries.
CREATE INDEX IF NOT EXISTS source_chunks_embedding_hnsw
    ON source_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memory_entries_embedding_hnsw
    ON memory_entries USING hnsw (embedding vector_cosine_ops);

-- DubDrive sync folder per DAW
ALTER TABLE daws ADD COLUMN IF NOT EXISTS dubdrive_sync_folder TEXT;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS dubdrive_sync_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS dubdrive_last_synced_at TIMESTAMPTZ;

ALTER TABLE sources ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER;

-- DAW inference: model pin (model NULL = use global chat model)
ALTER TABLE daws ADD COLUMN IF NOT EXISTS model TEXT;

-- Phase 06: per-DAW RAG mode (auto / always / off). 808notes DAWs use always.
ALTER TABLE daws ADD COLUMN IF NOT EXISTS rag_mode TEXT NOT NULL DEFAULT 'auto';



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
    mode TEXT NOT NULL UNIQUE CHECK (mode IN ('booops', '808notes')),
    safe_search INTEGER NOT NULL DEFAULT 0 CHECK (safe_search IN (0, 1, 2)),
    image_proxy BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_engines TEXT NOT NULL DEFAULT '',
    autocomplete TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auth & user tiers (owner env / members table / guests by IP)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member')),
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS icon_url TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_emoji TEXT DEFAULT '👤';

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('member', 'super_admin', 'owner'));

UPDATE users SET display_name = username WHERE display_name IS NULL OR btrim(display_name) = '';
UPDATE users SET bio = COALESCE(bio, '') WHERE bio IS NULL;
UPDATE users SET avatar_emoji = COALESCE(NULLIF(trim(avatar_emoji), ''), '👤') WHERE avatar_emoji IS NULL;

DROP TABLE IF EXISTS guest_message_counts;
DROP TABLE IF EXISTS member_message_counts;

ALTER TABLE personas ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chats DROP COLUMN IF EXISTS guest_ip;

CREATE INDEX IF NOT EXISTS chats_owner_id_idx ON chats(owner_id);
CREATE INDEX IF NOT EXISTS personas_owner_id_idx ON personas(owner_id);
CREATE INDEX IF NOT EXISTS daws_owner_id_idx ON daws(owner_id);

CREATE TABLE IF NOT EXISTS daw_memory (
    id SERIAL PRIMARY KEY,
    daw_id UUID NOT NULL REFERENCES daws(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS daw_memory_daw_id_idx ON daw_memory(daw_id);

-- BooCode Phase 3: repo ingest (DubDrive → tree-sitter chunks → pgvector).
-- Idempotent: safe to re-apply after the live migration.
ALTER TABLE chats DROP CONSTRAINT IF EXISTS chats_mode_check;
ALTER TABLE chats ADD CONSTRAINT chats_mode_check
    CHECK (mode IN ('booops', '808notes', 'boocode'));

ALTER TABLE daws DROP CONSTRAINT IF EXISTS daws_mode_check;
ALTER TABLE daws ADD CONSTRAINT daws_mode_check
    CHECK (mode IN ('booops', '808notes', 'boocode'));

ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_path TEXT;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_branch TEXT DEFAULT 'main';
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_last_synced_at TIMESTAMPTZ;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_sync_status TEXT;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_sync_error TEXT;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_auto_sync BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_file_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE daws ADD COLUMN IF NOT EXISTS repo_chunk_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE daws DROP CONSTRAINT IF EXISTS daws_repo_sync_status_check;
ALTER TABLE daws ADD CONSTRAINT daws_repo_sync_status_check
    CHECK (repo_sync_status IS NULL OR repo_sync_status IN ('idle', 'syncing', 'error'));

-- BooCode Phase 4: widen searxng_config.mode to include boocode, and seed a row.
ALTER TABLE searxng_config DROP CONSTRAINT IF EXISTS searxng_config_mode_check;
ALTER TABLE searxng_config ADD CONSTRAINT searxng_config_mode_check
    CHECK (mode IN ('booops', '808notes', 'boocode'));

CREATE TABLE IF NOT EXISTS repo_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID NOT NULL REFERENCES daws(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (daw_id, path)
);
CREATE INDEX IF NOT EXISTS repo_files_daw_idx ON repo_files(daw_id);

CREATE TABLE IF NOT EXISTS repo_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE,
    daw_id UUID NOT NULL REFERENCES daws(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    symbol_kind TEXT,
    symbol_name TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024),
    tokens INTEGER NOT NULL DEFAULT 0,
    UNIQUE (file_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS repo_chunks_daw_idx ON repo_chunks(daw_id);
CREATE INDEX IF NOT EXISTS repo_chunks_embedding_hnsw
    ON repo_chunks USING hnsw (embedding vector_cosine_ops);

-- BooCode Phase 5: terminals (tmux-backed, multi-device attach).
CREATE TABLE IF NOT EXISTS terminal_machines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    ssh_user TEXT,
    default_cwd TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS terminal_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE SET NULL,
    machine_id UUID NOT NULL REFERENCES terminal_machines(id),
    tmux_name TEXT NOT NULL UNIQUE,
    label TEXT,
    starting_cmd TEXT,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_detached_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_term_daw
    ON terminal_sessions(daw_id)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_term_lru
    ON terminal_sessions(last_detached_at)
    WHERE closed_at IS NULL AND pinned = FALSE;

-- Phase 5.1: agentic spawn. Existing rows default to 'bash'. CHECK keeps
-- the column tight so an unknown type can't sneak in via a buggy client.
ALTER TABLE terminal_sessions
    ADD COLUMN IF NOT EXISTS session_type TEXT NOT NULL DEFAULT 'bash';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'terminal_sessions_session_type_check'
    ) THEN
        ALTER TABLE terminal_sessions
            ADD CONSTRAINT terminal_sessions_session_type_check
            CHECK (session_type IN ('bash', 'claude', 'opencode'));
    END IF;
END$$;

-- Idempotent seed. `ubuntu-homelab` is the host itself reached via SSH
-- from the agent container (host's Tailscale IP, ssh_user=samkintop) —
-- this lets host-installed agents (claude, opencode) keep their auth
-- state without bind-mounts. /HomeLabRepos resolves natively on the host.
-- `local` is kept as a legacy alias and force-disabled (use ubuntu-homelab
-- instead). `embedding` stays disabled until key-based auth is populated
-- on that host.
INSERT INTO terminal_machines (name, host, ssh_user, default_cwd, enabled) VALUES
    ('local',          'localhost',         NULL,         '/opt',           FALSE),
    ('ubuntu-homelab', '100.114.205.53',    'samkintop',  '/HomeLabRepos',  TRUE),
    ('sam-desktop',    '100.101.41.16',     'samki',      NULL,             TRUE),
    ('embedding',      '100.90.172.55',     'samkintop',  NULL,             FALSE)
ON CONFLICT (name) DO NOTHING;

-- Legacy `local` row: ubuntu-homelab now fills this role. Keep the row
-- so historical session foreign keys still resolve, but disable it.
UPDATE terminal_machines
   SET enabled = FALSE
 WHERE name = 'local';

-- Phase 5.1: ubuntu-homelab is an SSH target to the host itself. The agent
-- container reaches it via the host's Tailscale IP. Reverses the prior
-- "force back to localhost" repair from Phase 5 Session 2 — that decision
-- predated agent-type support, where claude/opencode must run on the host
-- where they're installed. Idempotent on every API restart.
UPDATE terminal_machines
   SET host = '100.114.205.53',
       ssh_user = 'samkintop',
       default_cwd = '/HomeLabRepos',
       enabled = TRUE
 WHERE name = 'ubuntu-homelab';

-- `embedding` host migrated: Tailscale IP changed (100.93.187.4 →
-- 100.90.172.55) and ssh_user is known (samkintop). Keep enabled=FALSE
-- until key-based auth lands on the target (authorized_keys populated
-- via ssh-copy-id on host). Flip to TRUE in a follow-up commit once the
-- agent can reach the host without a password prompt.
UPDATE terminal_machines
   SET host = '100.90.172.55', ssh_user = 'samkintop'
 WHERE name = 'embedding';

-- Audit log — events: open, close, paste, pin, rename, device_connect,
-- device_disconnect. Paste entries store sha256(text) + len, not plaintext.
CREATE TABLE IF NOT EXISTS terminal_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES terminal_sessions(id) ON DELETE SET NULL,
    event TEXT NOT NULL,
    client_ip TEXT,
    ua TEXT,
    extra JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS terminal_audit_session_idx
    ON terminal_audit(session_id);
CREATE INDEX IF NOT EXISTS terminal_audit_created_idx
    ON terminal_audit(created_at DESC);

-- Persistent chat generation: status, sequencing, error tracking, timestamps.
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_status_check;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'complete' CHECK (status IN ('pending','streaming','complete','error','cancelled'));
ALTER TABLE messages ADD COLUMN IF NOT EXISTS last_seq integer NOT NULL DEFAULT 0;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS error text;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS finished_at timestamptz;

CREATE TABLE IF NOT EXISTS message_tokens (
    message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seq integer NOT NULL,
    delta text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_inflight
    ON messages(status)
    WHERE status IN ('pending','streaming');

