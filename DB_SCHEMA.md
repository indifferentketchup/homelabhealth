# boolab — Database Schema
Last updated: March 2026

## Notes
- PostgreSQL 16
- All IDs are UUIDs (`gen_random_uuid()`)
- All timestamps are `TIMESTAMPTZ DEFAULT NOW()`
- `ON CONFLICT DO NOTHING` on all seed inserts
- ChromaDB collections are namespaced by `daw_id` — not in Postgres

---

## Core Tables

### `daws`
```sql
CREATE TABLE daws (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    icon_url TEXT,
    color TEXT DEFAULT '#7c3aed',
    shared BOOLEAN DEFAULT FALSE,  -- appears in both BooOps and 808notes
    sort_order INTEGER DEFAULT 0,
    pinned_booops BOOLEAN DEFAULT FALSE,
    pinned_808notes BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `daw_context_files` (BooOps — injected into system prompt)
```sql
CREATE TABLE daw_context_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,           -- extracted text
    file_url TEXT,                   -- stored file path
    embeddable BOOLEAN DEFAULT FALSE, -- also embed in Chroma for RAG
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `daw_instructions`
```sql
CREATE TABLE daw_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Chat Tables

### `chats`
```sql
CREATE TABLE chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    daw_id UUID REFERENCES daws(id) ON DELETE SET NULL,
    mode TEXT NOT NULL CHECK (mode IN ('booops', '808notes')),
    persona_id UUID REFERENCES personas(id) ON DELETE SET NULL,
    model TEXT NOT NULL DEFAULT 'qwen3.5:35b',
    web_search_enabled BOOLEAN DEFAULT FALSE,
    rag_enabled BOOLEAN DEFAULT TRUE,
    pruning_summary TEXT,            -- stored summary from last compress
    message_count INTEGER DEFAULT 0,
    is_main_chat BOOLEAN DEFAULT FALSE, -- 808notes: one main chat per DAW
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `messages`
```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    model TEXT,                      -- which model generated this
    tokens_used INTEGER,
    sources_used JSONB,              -- array of source chunk IDs used in RAG
    forked_from UUID REFERENCES messages(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `chat_source_selections` (808notes — which sources active per chat)
```sql
CREATE TABLE chat_source_selections (
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (chat_id, source_id)
);
```

---

## 808notes Tables

### `sources`
```sql
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    group_id UUID REFERENCES source_groups(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'pdf', 'docx', 'txt', 'csv', 'xlsx', 'html', 'md', 'url', 'code', 'note', 'bourbites'
    )),
    file_url TEXT,                   -- stored file path (null for URL/bourbites)
    original_url TEXT,               -- for URL type
    content_hash TEXT,               -- for dedup / change detection
    chunk_count INTEGER DEFAULT 0,
    embedding_status TEXT DEFAULT 'pending' CHECK (embedding_status IN (
        'pending', 'processing', 'complete', 'error'
    )),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `source_groups`
```sql
CREATE TABLE source_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (daw_id, name)
);
```

### `notes`
```sql
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    group_id UUID REFERENCES note_groups(id) ON DELETE SET NULL,
    title TEXT,
    content TEXT NOT NULL,           -- markdown
    source_type TEXT DEFAULT 'manual' CHECK (source_type IN (
        'manual', 'ai_response', 'ai_summary'
    )),
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL, -- if saved from chat
    converted_to_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    search_vector TSVECTOR,          -- for full-text search
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Full-text search index
CREATE INDEX notes_search_idx ON notes USING GIN(search_vector);

-- Auto-update search vector
CREATE OR REPLACE FUNCTION notes_search_vector_update() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.title, '') || ' ' || coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER notes_search_vector_trigger
    BEFORE INSERT OR UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION notes_search_vector_update();
```

### `note_groups`
```sql
CREATE TABLE note_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    daw_id UUID REFERENCES daws(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (daw_id, name)
);
```

---

## Persona + Identity Tables

### `personas`
```sql
CREATE TABLE personas (
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
```

### `memory_entries`
```sql
CREATE TABLE memory_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'auto')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### `custom_instructions`
```sql
CREATE TABLE custom_instructions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope TEXT NOT NULL CHECK (scope IN ('global', 'booops', '808notes')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (scope)
);
```

---

## Settings Tables

### `branding_config`
```sql
CREATE TABLE branding_config (
    mode TEXT PRIMARY KEY CHECK (mode IN ('booops', '808notes', 'boolab')),
    config JSONB NOT NULL DEFAULT '{}'
);
```

Branding config shape (per mode):
```json
{
  "title": "BooOps",
  "subtitle": "your AI",
  "accentColor": "#ff2d78",
  "accentBright": "#ff6eb0",
  "accentDim": "#7c1a3d",
  "bgColor": "#050505",
  "bgPanel": "#0d0d0d",
  "bgCard": "#111111",
  "textColor": "#f0f0f0",
  "textDim": "#888888",
  "borderColor": "#222222",
  "fontFamily": "Rajdhani",
  "fontSize": "15",
  "bannerHeight": "120",
  "sidebarWidth": "280"
}
```

### `global_settings`
```sql
CREATE TABLE global_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Key/value pairs:
```
ollama_url          http://100.101.41.16:11434
embedding_model     qwen3-embedding:latest
default_model       qwen3.5:35b
pruning_threshold   40          (messages before summarize-and-compress)
top_k               6           (RAG retrieved chunks)
chunk_size          512
chunk_overlap       64
searxng_url         http://100.114.205.53:8888
```

---

## Chroma Collections (not Postgres)
One collection per DAW:
```
daw_{daw_id}_sources    — embedded source chunks
daw_{daw_id}_notes      — embedded notes (when converted to source)
```

Chunk metadata stored in Chroma:
```json
{
  "source_id": "uuid",
  "daw_id": "uuid",
  "source_name": "Week1_Readings.pdf",
  "source_type": "pdf",
  "chunk_index": 3,
  "page_number": 2
}
```

---

## Indexes
```sql
CREATE INDEX chats_daw_id_idx ON chats(daw_id);
CREATE INDEX chats_mode_idx ON chats(mode);
CREATE INDEX chats_updated_at_idx ON chats(updated_at DESC);
CREATE INDEX messages_chat_id_idx ON messages(chat_id);
CREATE INDEX messages_created_at_idx ON messages(created_at);
CREATE INDEX sources_daw_id_idx ON sources(daw_id);
CREATE INDEX sources_embedding_status_idx ON sources(embedding_status);
CREATE INDEX notes_daw_id_idx ON notes(daw_id);
```
