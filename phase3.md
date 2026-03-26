Here's the Phase 3 Cursor prompt:

```
## Phase 3 — Personas, Memory, DAWs

### Overview
- Personas: named AI identities with system prompts. One global default, overridable per-chat.
- Memory: persistent user facts, auto-extracted by the chat model + on-demand. Injected into every system prompt.
- DAWs (Dynamic AI Workspaces): per-chat system prompt contexts that can set a default persona and override/fork it.
- All managed from a new "AI" settings page.

---

### Backend — Schema additions (`schema.sql`)

```sql
-- Personas
CREATE TABLE IF NOT EXISTS personas (
  id SERIAL PRIMARY KEY,
  mode TEXT NOT NULL DEFAULT 'booops',
  name TEXT NOT NULL,
  system_prompt TEXT NOT NULL DEFAULT '',
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  avatar_emoji TEXT NOT NULL DEFAULT '🤖',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Only one default per mode
CREATE UNIQUE INDEX IF NOT EXISTS personas_mode_default_idx ON personas (mode) WHERE is_default = TRUE;

-- Seed default persona
INSERT INTO personas (mode, name, system_prompt, is_default, avatar_emoji)
VALUES ('booops', 'BooOps', 'You are BooOps, a helpful AI assistant.', TRUE, '🤖')
ON CONFLICT DO NOTHING;

-- Memory
CREATE TABLE IF NOT EXISTS memory (
  id SERIAL PRIMARY KEY,
  mode TEXT NOT NULL DEFAULT 'booops',
  content TEXT NOT NULL DEFAULT '',  -- markdown: headings + bullet lists
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO memory (mode, content) VALUES ('booops', '') ON CONFLICT DO NOTHING;

-- DAWs
CREATE TABLE IF NOT EXISTS daws (
  id SERIAL PRIMARY KEY,
  mode TEXT NOT NULL DEFAULT 'booops',
  name TEXT NOT NULL,
  system_prompt TEXT NOT NULL DEFAULT '',
  persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add persona_id and daw_id to chats
ALTER TABLE chats ADD COLUMN IF NOT EXISTS persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS daw_id INTEGER REFERENCES daws(id) ON DELETE SET NULL;
```

---

### Backend — New routers

#### `backend/routers/personas.py`
- `GET /api/personas?mode=booops` — list all personas for mode
- `POST /api/personas` — create `{mode, name, system_prompt, avatar_emoji}`
- `GET /api/personas/{id}` — get one
- `PUT /api/personas/{id}` — update `{name, system_prompt, avatar_emoji, is_default}`
  - If `is_default=true`, unset all other defaults for that mode first (in same transaction)
- `DELETE /api/personas/{id}` — delete (reject if is_default)

#### `backend/routers/memory.py`
- `GET /api/memory?mode=booops` — get memory content for mode
- `PUT /api/memory?mode=booops` — replace full content `{content: string}`
- `POST /api/memory/extract?mode=booops` — trigger extraction:
  - Fetch last 20 messages from most recent chat for mode
  - Fetch current memory content
  - Call Ollama (model from env `DEFAULT_MODEL`) with prompt:
    ```
    You are a memory extraction assistant. Given the conversation below and the existing memory, update the memory to reflect new facts about the user. Keep it concise — use markdown headings and bullet points. Do not repeat existing facts. Do not invent facts. Return only the updated memory text, nothing else.

    Existing memory:
    {current_memory}

    Recent conversation:
    {messages}
    ```
  - Replace memory content with model response
  - Return `{content: string}`

#### `backend/routers/daws.py`
- `GET /api/daws?mode=booops` — list all DAWs
- `POST /api/daws` — create `{mode, name, system_prompt, persona_id?}`
- `GET /api/daws/{id}` — get one
- `PUT /api/daws/{id}` — update
- `DELETE /api/daws/{id}` — delete

#### Update `backend/routers/chats.py`
When building the system prompt for a chat message, assemble it in this order:
1. Resolve persona: if chat has `persona_id` → use that persona's `system_prompt`; else if chat has `daw_id` and DAW has `persona_id` → use that; else use mode's default persona system prompt
2. If chat has `daw_id`: append DAW's `system_prompt` after persona prompt (separated by `\n\n`)
3. Append memory: if memory content is non-empty, append `\n\n## What I know about you:\n{memory_content}`
4. Pass assembled string as `system` to Ollama

Also:
- `PATCH /api/chats/{id}` — accept `persona_id` and `daw_id` fields
- `GET /api/chats/{id}` — return `persona_id` and `daw_id` in response

Register all three new routers in `main.py`.

---

### Frontend — API layer

`frontend/src/api/personas.js` — CRUD matching endpoints above
`frontend/src/api/memory.js` — get, put, extract
`frontend/src/api/daws.js` — CRUD matching endpoints above

---

### Frontend — Zustand store additions (`store/index.js`)

```js
activePersonaId: null,          // globally selected persona id
setActivePersonaId: (id) => ...,
personas: [],
setPersonas: (list) => ...,
```

On app load (in `App.jsx` or `BooOpsShell`), fetch default persona for mode and set `activePersonaId`.

---

### Frontend — AI Settings page

New route/page: `frontend/src/pages/booops/AISettings.jsx`

Accessible from sidebar — add a brain/sparkle icon button in the sidebar (above or below the gear icon). `onClick` → navigate to `/ai` or show as a panel (same slide-in pattern as Settings).

Three tabs across the top: **Personas | Memory | DAWs**

#### Personas tab
- List all personas as cards: avatar emoji, name, system prompt preview, "Default" badge if is_default
- "New Persona" button → inline form: emoji picker (just text input for emoji), name, system prompt textarea
- Each card: Edit button (expand inline form), Set as Default button, Delete button (disabled if default)

#### Memory tab
- Large textarea showing full memory markdown content (headings + bullets)
- "Save" button → PUT /api/memory
- "Extract from recent chat" button → POST /api/memory/extract, show loading state, replace textarea content with result
- Last updated timestamp shown

#### DAWs tab
- List all DAWs: name, system prompt preview, associated persona name (or "Default persona")
- "New DAW" button → inline form: name, system prompt textarea, persona selector dropdown (plain React, position:fixed, getBoundingClientRect — NO Radix Portal)
- Each DAW: Edit, Delete buttons

---

### Frontend — Per-chat persona/DAW selector

In `ModelSelectorBar.jsx` (or the top bar area), add two small selector pills next to the model selector:
- Persona pill: shows active persona emoji + name, click → plain React dropdown listing all personas, select sets `persona_id` on current chat via PATCH
- DAW pill: shows DAW name or "No DAW", click → plain React dropdown listing all DAWs + "None" option

Both pills only show when a chat is active (`activeChatId` is set). Use `sortSelectedFirst` utility for both dropdowns.

---

### Constraints
- ALL dropdowns: plain React, `position: fixed`, `getBoundingClientRect()`. No Radix Portal.
- No hardcoded hex — CSS variables only.
- `ON CONFLICT DO NOTHING` on all seed inserts.
- Memory extraction is fire-and-forget from frontend — show spinner, update textarea on response.
- Persona delete must reject (400) if persona is the mode default.
- DAW persona_id is nullable — null means "use global default persona".
- System prompt assembly happens server-side in chats.py only — never on frontend.
```