# boolab — Cursor Starting Prompt
> Copy this into Cursor's system prompt or first message at the start of each session.

---

## Context
I'm building **boolab** — a unified AI workspace platform with two branded modes: **BooOps** (general AI chat) and **808notes** (NotebookLM-style notebook workspace). This is a self-hosted homelab project. I am the only user.

**Always read these files before writing any code:**
- `SPEC.md` — full product specification
- `boolab_context.md` — infrastructure, deploy patterns, env vars
- `DB_SCHEMA.md` — complete Postgres schema
- `IMPLEMENTATION_PLAN.md` — phased build plan with checkboxes

## Stack (non-negotiable)
- **Frontend**: React 18 + Vite + shadcn/ui + Tailwind CSS
- **Backend**: FastAPI + Python 3.12 + asyncpg
- **Database**: PostgreSQL 16
- **Vector DB**: ChromaDB
- **Embeddings**: qwen3-embedding:latest via Ollama
- **LLM**: Ollama (default) + Claude API (on-demand)

## Coding Standards

### General
- All IDs are UUIDs
- All DB queries use asyncpg (not SQLAlchemy ORM)
- FastAPI endpoints use `async def`
- Never use `SELECT *` — always name columns
- `ON CONFLICT DO NOTHING` on all seed inserts
- No hardcoded secrets — always from `.env` via `os.environ`

### Backend file structure
```
backend/
  main.py           # FastAPI app, lifespan, CORS
  db.py             # asyncpg pool, get_pool()
  schema.sql        # full schema, runs on startup
  routers/
    daws.py
    chats.py
    sources.py
    notes.py
    personas.py
    memory.py
    settings.py
    search.py
    rag.py
    ollama.py
    claude.py
    bourbites.py
  services/
    embedding.py    # chunking + Chroma ingestion
    reranking.py    # flashrank
    pruning.py      # summarize-and-compress
    parsing.py      # file type parsers
```

### Frontend file structure
```
frontend/
  src/
    main.jsx
    App.jsx
    mode.js         # subdomain detection → APP_MODE
    components/
      ui/           # shadcn/ui components
      layout/       # Sidebar, Header, Panel
      chat/         # ChatView, MessageList, MessageBubble, ChatInput
      daw/          # DAWCards, DAWCard, DAWPanel
      sources/      # SourcePanel, SourceList, UploadModal
      notes/        # NotePanel, NoteEditor, NoteList
      settings/     # SettingsPage, BrandingSection, ColorPicker
    pages/
      booops/       # BooOpsApp, NewChat, AllChats
      808notes/     # NotesApp, DAWLanding, DAWView
      boolab/       # BooLabLanding
    hooks/
      useChat.js
      useDAW.js
      useSources.js
      useSettings.js
      useStream.js  # SSE streaming hook
    api/
      index.js      # base fetch wrapper
      chats.js
      daws.js
      sources.js
      notes.js
      settings.js
    store/
      index.js      # Zustand store
    styles/
      globals.css   # CSS variables, base styles
      booops.css    # BooOps-specific vars
      808notes.css  # 808notes-specific vars
```

### React patterns
- Zustand for global state (not Redux, not Context for everything)
- React Query (TanStack Query) for server state / caching
- `useStream.js` hook handles SSE streaming from FastAPI
- shadcn/ui components are the base — always style via CSS variables, never override Tailwind classes inline
- Never use `localStorage` for anything that should persist — use the backend

### Styling
- CSS variables for all colors — never hardcode hex in components
- BooOps and 808notes palettes defined in `globals.css` as separate `:root[data-mode="booops"]` and `:root[data-mode="808notes"]` blocks
- `data-mode` attribute set on `<html>` by `mode.js` on load
- shadcn/ui maps to CSS variables — update variables, everything updates

### Streaming
- Backend: FastAPI `StreamingResponse` with SSE format (`data: ...\n\n`)
- Frontend: `EventSource` or `fetch` with `ReadableStream` — use the `useStream.js` hook
- Always handle: `[DONE]` signal, error states, abort on unmount

## Deploy Pattern (read boolab_context.md for details)
- Docker Compose at `/opt/boolab/docker-compose.yml`
- React requires build step — no live file edits unlike BourBites
- Backend changes: rebuild `boolab_api`
- Frontend changes: rebuild `boolab_ui`
- Never bind containers externally to `0.0.0.0`
- Tailscale handles all auth

## What NOT to build
- No auth / login system
- No podcast / audio / video generation
- No voice STT/TTS
- No image generation
- No web scraping (removed from scope)
- No GitHub repo ingestion (removed from scope)
- No multi-user features

## Current Phase
> Update this line at the start of each Cursor session with the current phase from IMPLEMENTATION_PLAN.md

**Currently working on: Phase 0 — Project Skeleton**

Specific task:
- [ ] Init repo structure
- [ ] docker-compose.yml
- [ ] FastAPI skeleton
- [ ] React + Vite + shadcn/ui init
- [ ] Mode detection
- [ ] CSS variable system

---

## Reference Apps (same developer, same patterns)
Study these for coding style, deploy patterns, and UI conventions:
- **BourBites** (`/opt/bourbites3/`) — FastAPI + asyncpg + vanilla JS. Best reference for backend patterns.
- **Impulse** (`/opt/impulse/`) — FastAPI + SQLite + vanilla JS. Good for simple CRUD patterns.
- **Dashgaard** (`/opt/dashgaard/`) — Node/Express + vanilla JS. Good for settings/config patterns.
