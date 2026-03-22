# boolab — Implementation Plan
Last updated: March 2026

## Guiding Principles
- Build vertically, not horizontally — one working slice beats five half-built features
- Backend API first, then wire frontend to it
- Test each phase end-to-end before moving to next
- Don't build 808notes until BooOps Phase 1 is solid — shared infra must be proven first
- React component library (shadcn/ui) configured once in Phase 0, never revisited

---

## Phase 0 — Project Skeleton
**Goal:** Repo structure, Docker, DB connection, React app loads in browser. Nothing functional yet.

### Tasks
- [ ] Init repo: `/opt/boolab/` structure
- [ ] `docker-compose.yml` — `boolab_api`, `boolab_ui`, `boolab_chroma`, `boolab_db`
- [ ] FastAPI app skeleton — health endpoint, CORS, DB pool
- [ ] Postgres schema skeleton — run on startup
- [ ] React + Vite init, Tailwind + shadcn/ui configured
- [ ] Mode detection by subdomain (`booops` | `808notes` | `boolab`)
- [ ] CSS variable system — BooOps palette + 808notes palette, swaps on mode
- [ ] Caddy blocks for all three subdomains
- [ ] `.env` wired for all services

**Done when:** `booops.boogaardmusic.com` and `808notes.boogaardmusic.com` load a blank React app with correct branding colors per subdomain.

---

## Phase 1 — BooOps Core Chat
**Goal:** Working general chat with Ollama. No DAWs, no RAG, no personas yet.

### Backend
- [ ] Ollama proxy endpoint (`/api/ollama/models`, `/api/ollama/chat` streaming)
- [ ] Claude API proxy (`/api/claude/chat` streaming)
- [ ] Chat schema: `chats`, `messages` tables
- [ ] `POST /api/chats/` — create chat
- [ ] `GET /api/chats/` — list chats
- [ ] `POST /api/chats/{id}/messages` — send message, stream response
- [ ] `GET /api/chats/{id}/messages` — load history
- [ ] `DELETE /api/chats/{id}` — delete chat
- [ ] Context pruning: message count threshold → summarize-and-compress via Ollama

### Frontend
- [ ] BooOps left sidebar — collapsible, new chat button, recent chats list
- [ ] Chat view — message list, streaming render, markdown rendering
- [ ] Model switcher — Ollama models dropdown + Claude API options
- [ ] Chat input — textarea, send, stop generation
- [ ] `+` menu stub (upload, web search toggle placeholder, persona placeholder)
- [ ] User profile icon (global, uploadable in settings)
- [ ] AI icon (BooOps default: westie)
- [ ] Chat bubbles — user/AI with icons
- [ ] Mobile layout — chat default, sidebar slides in
- [ ] "All Chats" page — paginated full chat list

**Done when:** You can have a streaming conversation with qwen3.5:35b or Claude Sonnet from `booops.boogaardmusic.com` on desktop and mobile.

---

## Phase 2 — BooOps Settings + Branding
**Goal:** Full branding control for BooOps from a settings page.

### Backend
- [ ] Branding config schema + volume storage
- [ ] `GET/PUT /api/settings/booops` — branding config
- [ ] `POST /api/settings/booops/upload/{banner|logo|favicon|icon}` — asset upload
- [ ] Global settings endpoint (panel widths, font sizes, structural layout)
- [ ] User profile icon upload endpoint

### Frontend
- [ ] BooOps Settings page
  - [ ] Colors section (CSS var pickers)
  - [ ] Typography (font family, sizes)
  - [ ] Layout (sidebar width, panel widths, banner height)
  - [ ] Assets (banner upload, logo upload, favicon)
  - [ ] User profile icon
  - [ ] API keys (Ollama URL, Claude API key)
  - [ ] Default model config
- [ ] Branding applied live from config on load
- [ ] boolab global settings page (structural/layout only)

**Done when:** BooOps looks exactly how you want it — cyberpunk palette, westie banner, your fonts.

---

## Phase 3 — DAWs + Personas + Memory (BooOps)
**Goal:** Full DAW system, personas, memory, custom instructions in BooOps.

### Backend
- [ ] DAW schema: `daws`, `daw_context_files`, `daw_chat_assignments` tables
- [ ] Full DAW CRUD + icon upload
- [ ] `POST /api/daws/{id}/context-files` — upload context file (with embed checkbox)
- [ ] `DELETE /api/daws/{id}/context-files/{file_id}`
- [ ] `POST /api/chats/{id}/assign-daw` / `remove-daw`
- [ ] Context file injection into system prompt on chat load
- [ ] Persona schema: `personas` table
- [ ] Full persona CRUD + icon upload
- [ ] Memory schema: `memory_entries` table
- [ ] Memory CRUD + auto-add logic (detect "remember this" patterns + AI-triggered)
- [ ] Custom instructions schema: `custom_instructions` table (global + per-mode)
- [ ] Instructions injected into system prompt

### Frontend
- [ ] DAW cards page — grid, icon, name, description, customizable card bg/border/glow
- [ ] DAW detail / settings panel — context files, instructions, assigned persona
- [ ] Pin DAWs to left nav — pinned section collapsible
- [ ] DAW badge indicator on chat items
- [ ] Persona picker in `+` menu and DAW settings
- [ ] Personas manager in settings
- [ ] Memory viewer/editor in settings
- [ ] Custom instructions editor in settings (global + BooOps override)
- [ ] Conversation forking UI

**Done when:** You have a "SWK 6382" DAW in BooOps, a custom persona, memory working, and chats assignable to DAWs.

---

## Phase 4 — Web Search (BooOps)
**Goal:** Toggle web search on/off per chat, SearXNG results injected into context.

### Backend
- [ ] `GET /api/search?q=` — SearXNG proxy, returns cleaned results
- [ ] Web search injection into chat context when enabled
- [ ] Web search state persisted per chat

### Frontend
- [ ] Web search toggle in `+` menu (active state indicator)
- [ ] Search results shown as collapsible context citations above AI response

**Done when:** You can ask BooOps "what happened in the news today" with web search on and get grounded results.

---

## Phase 5 — 808notes Core
**Goal:** DAW cards landing page, source ingestion pipeline, basic RAG chat.

### Backend
- [ ] Source schema: `sources`, `source_groups`, `source_chunks` tables
- [ ] Source upload endpoint — multipart, multi-file
- [ ] File parsers: PDF (pypdf), DOCX (python-docx), TXT/MD/HTML/CSV/XLSX (unstructured)
- [ ] URL ingestion — fetch + parse HTML content
- [ ] Chunking pipeline — configurable chunk size + overlap
- [ ] Embedding pipeline — `qwen3-embedding` via Ollama → ChromaDB
- [ ] Reranking — flashrank second pass on retrieved chunks
- [ ] `GET /api/sources/` — list sources for DAW
- [ ] `DELETE /api/sources/{id}` — delete + remove from Chroma
- [ ] `POST /api/rag/query` — retrieve + rerank + return context
- [ ] Source selection state — which sources/groups active per chat
- [ ] RAG injection into chat when sources selected

### Frontend
- [ ] 808notes DAW cards landing page
- [ ] 808notes three-panel layout (left chats, center chat, right sources/notes)
- [ ] Right panel — sources section (top 2/3)
  - [ ] Source list with selection checkboxes
  - [ ] Source groups — create, rename, delete, bulk delete
  - [ ] Add sources button → center modal (drag+drop + file browser)
  - [ ] Upload progress bar + embedding progress bar per file
  - [ ] Active source selection indicator (persists until changed)
- [ ] RAG-grounded chat — same chat component as BooOps, different defaults
- [ ] Source toggle: RAG only → web search → general
- [ ] Mobile bottom nav for 808notes DAW view

**Done when:** You can drop your SWK 6575 PDF readings into an 808notes DAW and chat with them grounded in those sources.

---

## Phase 6 — 808notes Notes
**Goal:** Full notes system — create, save AI responses, convert to sources.

### Backend
- [ ] Notes schema: `notes`, `note_groups` tables
- [ ] Notes CRUD + grouping
- [ ] `POST /api/notes/from-message` — save AI response as note
- [ ] `POST /api/notes/{id}/to-source` — convert note to markdown source, embed it
- [ ] Notes search (full-text via Postgres `tsvector`)
- [ ] Notes embeddable as RAG sources (Chroma)

### Frontend
- [ ] Right panel — notes section (bottom 1/3, collapsible)
  - [ ] Note list — rename, delete, bulk delete, group
  - [ ] "Save response" button on every AI message
  - [ ] Note editor — markdown, split-pane live preview
  - [ ] Paste-from-rich-text → auto-convert to markdown
  - [ ] "Convert to source" button per note
  - [ ] Notes search

**Done when:** You paste your Brightspace course content, it converts to clean markdown, you save an AI summary as a note, and that note becomes a searchable source.

---

## Phase 7 — 808notes Settings + Branding
**Goal:** 808notes has its own full branding identical in scope to BooOps settings.

### Tasks
- [ ] `GET/PUT /api/settings/808notes` — separate branding config
- [ ] 808notes settings page (same structure as BooOps settings)
- [ ] RAG settings section: chunk size, top-k, reranking toggle
- [ ] Embedding model config

**Done when:** 808notes has its deep purple 808 branding fully applied and controllable.

---

## Phase 8 — BourBites Integration
**Goal:** BourBites `/context` available as a toggleable source in 808notes DAWs.

### Backend
- [ ] `GET /api/bourbites/context` — fetch + cache BourBites context
- [ ] BourBites source type in source schema
- [ ] Embed BourBites context into Chroma on demand (per DAW)
- [ ] Refresh endpoint — re-fetch and re-embed on demand

### Frontend
- [ ] BourBites toggle in 808notes sources panel (special source entry, always at top)
- [ ] "Refresh BourBites" button
- [ ] BourBites link in both sidebars

**Done when:** You're in your SWK 6382 808notes DAW, toggle BourBites on, and can ask questions that pull from both your uploaded PDFs and your BourBites notes simultaneously.

---

## Phase 9 — Polish + Cross-App Links
**Goal:** Everything connected, boolab landing page, sidebar links, mobile polish.

### Tasks
- [ ] boolab landing page — two cards, customizable, links to each mode
- [ ] boolab settings page — structural/global controls
- [ ] Bottom-left boolab button in both sidebars
- [ ] Sidebar links: BourBites ↔ BooOps ↔ 808notes
- [ ] Shared DAW switcher tabs (BooOps | 808notes tabs under banner)
- [ ] Mobile polish pass — BooOps and 808notes
- [ ] Error states, loading skeletons, empty states
- [ ] Toast notifications
- [ ] Keyboard shortcuts (new chat, toggle sidebar, send message)

**Done when:** All three URLs work, all cross-app links work, mobile is solid, and the whole thing feels finished.

---

## Later (Post-v1)
- Deep research mode (BooOps)
- Cross-DAW notebook sharing
- code-server integration
- Mobile PWA install
- Auth / multi-user
- Conversation export (PDF, markdown)
- DAW templates
- Bulk chat operations

---

## Recommended Cursor Workflow
1. Open Cursor in `/opt/boolab/` (or local clone)
2. Add to Cursor context on every session: `SPEC.md`, `boolab_context.md`, `DB_SCHEMA.md`
3. Add BourBites/Impulse context docs as style reference
4. Work one phase at a time — complete and test before moving on
5. When Cursor goes off-rails architecturally, come back to Claude to realign
6. Use `IMPLEMENTATION_PLAN.md` checkboxes to track progress
