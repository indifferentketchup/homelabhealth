# boolab — Current State
Last updated: March 25, 2026

**Deeper tracking:** `IMPLEMENTATION_PLAN_2.md` (done/partial/gaps). **Session handoff:** `CONTINUE_PROMPT.md`.

## What boolab is
A unified AI workspace platform with two branded modes in one app:
- **BooOps** (`booops.boogaardmusic.com`) — general AI chat, replaces Open WebUI
- **808notes** (`808notes.boogaardmusic.com`) — NotebookLM-style notebook workspace (shell + branding today; RAG/notes UI not built)
- **boolab** (`boolab.boogaardmusic.com`) — landing page linking both (placeholder shell in `App.jsx`)

Single Docker deployment, mode detected by subdomain or `VITE_APP_MODE`.

## Infrastructure
- Repo: `https://github.com/indifferentketchup/boolab`
- Stack: React 18 + Vite + shadcn/ui + Tailwind, FastAPI + Python 3.12 + asyncpg, PostgreSQL 16, ChromaDB
- Containers: `boolab_api` (port 9300), `boolab_ui` (port 9301), `boolab_chroma`, `boolab_db`
- Deploy: `docker compose up --build` from `/opt/boolab/` on ubuntu-homelab (`100.114.205.53`)
- Currently developing locally on Windows (Cursor), deploying to homelab when ready
- Frontend requires build step (Vite) — no live file edits like BourBites

## What's built

### Phase 0–1 — Skeleton + BooOps core chat (done)
- Full Docker skeleton, Postgres schema (`backend/schema.sql` on API startup), ChromaDB container
- Streaming chat via SSE: Ollama + Claude (`routers/ollama.py`, `routers/claude.py`, `routers/chats.py`)
- Sidebar, recent chats, **All Chats** (`/chats`), New Chat, mobile drawer layout
- Model switcher and `+` menu: **plain React** dropdowns (`position: fixed` + `getBoundingClientRect()`); web search toggle on chat (Zustand + `PATCH` chat)
- Context pruning: `services/pruning.py` + `pruning_summary` on chats
- SSE helper: `frontend/src/hooks/useStream.js`

### Phase 2 — BooOps settings + branding (done for BooOps)
- Branding storage: DB + assets under `/data/branding`; **`GET/PATCH /api/branding`** and uploads (`routers/branding.py`, `frontend/src/api/branding.js`) — not legacy `/api/settings/booops`
- **Settings** UI: `SettingsPage.jsx` (colors, typography, layout, Ollama tooling, default/hidden models)
- **boolab** mode: still a minimal landing stub in `App.jsx` (no full global settings page)

### Phase 3 — DAWs, personas, memory, custom instructions (mostly done; two prompt gaps)
- **Personas** (`routers/personas.py`), **DAWs** (`routers/daws.py`, `daw_context_files.py`), **custom instructions** (`routers/custom_instructions.py`)
- **Memory:** `mode_memory` markdown blob injected in chat; **memory_entries** table + CRUD + UI in `AISettings.jsx` — *entries are not yet merged into `_assembled_system_prompt`* (only the blob is)
- **`daw_instructions`** (table/API in `daws.py`): *text not yet injected* after DAW `system_prompt` in `chats.py`
- **AI surface:** `/ai` → `AISettings.jsx`; `/daws` → `DawsPage.jsx`, `DawDetailPage.jsx`; DAW pins in sidebar; per-chat persona + DAW in `ModelSelectorBar.jsx`
- **Fork:** `POST .../messages/{id}/fork` + UI in `MessageBubble.jsx`
- IDs in the live schema are **UUIDs**; treat `DB_SCHEMA.md` + `schema.sql` as source of truth (older `phase3.md` notes may mention SERIAL)

### Phase 4 — Web search (done)
- SearX: `backend/services/searx.py`; per-chat `web_search_enabled`; SSE `search_sources`; collapsible **Web Sources** in `MessageList.jsx`
- Standalone **`POST /api/search`** (`routers/search.py`) — shape differs from older GET-in-docs notes
- Env: `SEARXNG` (or equivalent) must be reachable from the API container

### 808notes / boolab in the UI today
- **`808notes`:** `frontend/src/pages/notes808/Notes808App.jsx` — Phase 0.5 shell: router, fetches `/api/branding/808notes`, applies CSS variables; placeholder home copy (no sources/RAG/notes UI yet)
- **`boolab`:** centered placeholder in `App.jsx` when mode is neither `booops` nor `808notes`
- Backend includes **808notes-oriented tables** in `schema.sql`, but **no 808notes routers or RAG pipeline** wired like BooOps chat (`RAG_PIPELINE.md` describes intent)

### Phases 5–9
- **Not started** at product level: full 808notes ingestion/RAG UI, notes system, 808notes settings polish, BourBites, cross-app polish — see `IMPLEMENTATION_PLAN_2.md`

## Current chat input layout (reference)
Claude-style input box:
```
┌─────────────────────────────────────┐
│ textarea (auto-grows, transparent)  │
│                                     │
│ [+]                        [send ▶] │
└─────────────────────────────────────┘
```

## Known issues / polish
- Model selector may briefly show “Select model” until Ollama models load — auto-select of default on first paint is still polish
- **Radix Portal** and `overflow-clip` roots: keep **plain React** anchored popovers for layout-sensitive controls unless a file already standardizes otherwise
- **`+` menu:** web search is real; uploads / extra persona entry points may still be thin vs SPEC
- **Profile / icons:** branding + persona assets exist; confirm global profile upload matches SPEC everywhere
- **Tech debt:** inject `daw_instructions` and `memory_entries` (or document one path as deprecated); optional verification of persona seed SQL on fresh DBs

## Next slices (from implementation plan)
1. Close Phase 3 **prompt parity**: `daw_instructions` + `memory_entries` in `_assembled_system_prompt` (or explicit product decision)
2. **808notes vertical:** extend beyond shell — sources, chunk+embed to Chroma, RAG block in chat for `mode=808notes` (`RAG_PIPELINE.md`)
3. **Production:** optional versioned `Caddyfile` or deploy doc; SearX + Ollama URLs for compose

## Key technical decisions
- **No Radix Portal** for clipped layouts — use plain React dropdowns with `position: fixed` + `getBoundingClientRect()` where the codebase already does
- **Zustand** for UI globals, **React Query** for server state
- **SSE streaming** via `useStream`
- **CSS variables / branding API** for theme — avoid hardcoded hex in new components
- **Mode detection:** `frontend/src/mode.js` + `data-mode` on `<html>`; localhost/IP uses `VITE_APP_MODE`
- **System prompt assembly:** server-side in `chats.py` (`_assembled_system_prompt`); frontend selects persona, DAW, model, search flag

## Branding
- Defaults still described in `frontend/src/styles/globals.css` under `[data-mode="booops"]` and `[data-mode="808notes"]`
- **Runtime:** BooOps and 808notes shells load **`/api/branding/{mode}`** and apply tokens (see `applyBrandingCss` in `api/branding.js`)

## File structure (representative)
```
boolab/
  backend/
    main.py
    db.py
    schema.sql
    requirements.txt
    Dockerfile
    routers/
      chats.py
      ollama.py
      claude.py
      branding.py
      personas.py
      daws.py
      daw_context_files.py
      memory.py
      custom_instructions.py
      search.py
    services/
      pruning.py
      searx.py
  frontend/
    src/
      App.jsx
      mode.js
      store/index.js
      hooks/useStream.js
      api/
        chats.js, ollama.js, branding.js, personas.js, daws.js,
        memory.js, memoryEntries.js, customInstructions.js, index.js
      components/
        chat/       # ChatView, ChatInput, MessageList, MessageBubble, ModelSelectorBar, …
        layout/     # Sidebar, …
        ui/
      pages/
        booops/     # BooOpsApp, AllChats, SettingsPage, AISettings, DawsPage, DawDetailPage, ProfilePage, …
        notes808/   # Notes808App.jsx (shell)
      styles/globals.css
  docker-compose.yml
  .env
  SPEC.md
  DB_SCHEMA.md
  IMPLEMENTATION_PLAN.md
  IMPLEMENTATION_PLAN_2.md
  CONTINUE_PROMPT.md
  RAG_PIPELINE.md
  UI_DESIGN.md
  boolab_context.md
```

## Developer context
- Sam Kintop, homelab enthusiast, MSW grad student
- All other self-hosted apps follow same pattern: FastAPI + asyncpg + Docker + Caddy reverse proxy
- Direct, no fluff — commands first, no explanations unless asked
- Never provide SSH commands (uses Termius)
- Backup before any destructive step
