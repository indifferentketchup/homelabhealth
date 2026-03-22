# boolab — Product Specification
> Last updated: March 2026

## Overview
boolab is a unified AI workspace platform consisting of two branded modes — **BooOps** and **808notes** — sharing a single backend, database, and deployment. It replaces Open WebUI (booops) and the existing 808notes (open-notebook) with a fully custom, fully brandable application built to the same standards as BourBites, Impulse, DubDrive, and Dashgaard.

## URLs
| URL | Mode |
|---|---|
| `booops.boogaardmusic.com` | BooOps — general AI chat |
| `808notes.boogaardmusic.com` | 808notes — NotebookLM-style workspace |
| `boolab.boogaardmusic.com` | boolab landing page |

Mode is detected by subdomain on the frontend. Same Docker deployment serves all three.

## Stack
| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + shadcn/ui + Tailwind CSS |
| Backend | FastAPI + Python 3.12 + asyncpg |
| Database | PostgreSQL 16 |
| Vector DB | ChromaDB (Docker container) |
| Embeddings | `qwen3-embedding:latest` via Ollama on sam-desktop (`100.101.41.16:11434`) |
| LLM | Ollama (default) + Claude API (on-demand) |
| Web Search | SearXNG (already running on ubuntu-homelab `:8888`) |
| File Parsing | pypdf, python-docx, unstructured |
| Reranking | flashrank |
| Ports | `9300` (API), `9301` (UI) |

## Containers
```
boolab_api      FastAPI backend         100.114.205.53:9300
boolab_ui       nginx + React build     100.114.205.53:9301
boolab_chroma   ChromaDB                internal only
```
Shared Postgres instance with BourBites OR dedicated — configurable via `.env`.

---

## Core Concepts

### DAWs (Digital AI Workspaces)
The fundamental organizational unit. A single DB object used by both modes.

**Fields:** `id`, `name`, `description`, `icon_url`, `color`, `created_at`, `shared` (bool — whether it appears in both modes)

- In **BooOps**: a DAW is a project container. Chats can be assigned/removed. DAW has context files + instructions always injected into system prompt. Embeddable checkbox per context file.
- In **808notes**: a DAW is a notebook container. Has sources, notes, and chats scoped exclusively to it.
- **Shared DAWs**: appear in both modes with a 2-tab switcher (BooOps | 808notes) under the top banner.

### Personas
Named AI configurations. Chosen like a model.

**Fields:** `id`, `name`, `icon_url`, `system_prompt`, `default_model`, `web_search_enabled`, `rag_enabled`, `created_at`

- Global library, assigned to a DAW as default or overridden per chat
- Default AI icon per mode (westie = BooOps, 808 speaker = 808notes)

### Memory
Same pattern as Tweak bot. AI adds automatically when relevant or when asked. User can review and edit entries in settings.

**Fields:** `id`, `content`, `source` (auto/manual), `created_at`

### Custom Instructions
Global → per-mode override. Injected into every system prompt.

---

## BooOps Mode

### Layout
- **Desktop**: collapsible left sidebar + full-width chat area (two-panel)
- **Mobile**: chat screen by default, left panel slides in on tap

### Left Navigation Panel
```
[BooOps banner/logo]          ← clicks to new chat landing page
[BooOps | 808notes tabs]      ← only on shared DAWs
─────────────────────────
[New Chat button]
[Search]
─────────────────────────
[Pinned DAWs]                 ← collapsible section
[Recent Chats]                ← collapsible, paginated
                              ← "All Chats" page for overflow
─────────────────────────
[boolab banner]               ← bottom-left, opens boolab.boogaardmusic.com in new tab
```

### DAW Behavior in BooOps
- Chats show a subtle DAW badge indicator when assigned
- Chats assignable/removable from DAWs via `+` menu or right-click
- DAW context panel: uploaded files + written instructions, always injected into system prompt. Each file has optional "embed as source" checkbox.
- DAW cards page: grid of cards with icon, name, description, customizable bg/border/glow

### Chat Features
- Model: Ollama default, Claude API (Sonnet/Haiku/Opus) on-demand per conversation
- Personas: assigned per DAW or overridden per chat
- Markdown rendered by default, toggle to plain text
- Conversation forking
- Context pruning: summarize-and-compress after configurable threshold, manual clear
- Streaming responses

### Chat Input `+` Menu
- Upload files
- Web search toggle
- Persona picker
- Add chat to DAW / remove from DAW
- Change model

---

## 808notes Mode

### Layout
- **Desktop**: dynamic three-panel — left (chats) + center (main chat) + right (sources/notes)
- **Mobile**: DAW cards landing page by default. Inside a DAW: bottom nav with chats (left), new chat (center), sources (right) — emoji icon + label text

### Navigation
- Top-left: 808notes banner/logo → clicks to DAW cards landing page
- Bottom-left: boolab button (same as BooOps)
- Left panel: chats for current DAW only (collapsible)
- To switch DAWs: go back to landing page

### DAW Behavior in 808notes
- DAW is self-contained. When you're in it, you're in it.
- Chats are scoped to the DAW only
- Shared DAW switcher tabs appear under banner if DAW is shared with BooOps

### Right Panel — Sources (top 2/3)
- Add Sources button (top-right) → center modal: drag+drop + file browser, multi-file, multi-type
- Per-file: upload progress bar → embedding progress bar
- Supported types: PDF, DOCX, TXT, CSV, XLSX, HTML, MD, URLs, code files
- Select individual sources, groups, or all — selection persists until changed, applies to next message
- Source grouping, rename, delete, bulk delete
- BourBites `/context` endpoint available as a toggleable source per DAW

### Right Panel — Notes (bottom 1/3, collapsible)
- Create manually: markdown editor with split-pane live preview
- Save full AI response as note (editable after save)
- Paste-from-rich-text auto-converts to markdown (critical for Brightspace content)
- Rename, delete, bulk delete, group
- Searchable + embeddable as RAG sources
- Convert note → source (saved as markdown file, fed into embedding pipeline)

### RAG Behavior
- RAG on by default when sources exist
- Reranking enabled (flashrank second-pass scoring)
- Toggleable per chat: RAG only → web search → general knowledge (no grounding)
- Context pruning: same as BooOps

### Chat Structure
- One main chat per DAW (persistent, pruned)
- Additional focused chats spawnable within the DAW
- Mobile bottom nav center button = new chat

---

## boolab Landing Page
- Two large cards: BooOps + 808notes
- Each card: icon, name, short description
- Customizable per card: background color, border color, glow intensity
- Clicking a card navigates to respective mode
- Controlled from boolab settings page

---

## Settings Architecture

### boolab Settings (global/structural)
- Panel widths, font sizes, banner/logo/icon sizes
- Landing page card customization
- Memory manager (view, edit, delete entries)
- Custom instructions (global)
- API keys (Ollama URL, Claude API key)
- Default model config

### BooOps Settings (mode-specific)
- Full branding: colors (CSS vars), fonts, banner, logo, icons, accent palette
- Custom instructions override (BooOps-specific)
- Personas manager
- Context pruning threshold
- User profile icon upload (global, overridable here)

### 808notes Settings (mode-specific)
- Full branding: separate palette, fonts, banner, logo, icons
- Custom instructions override (808notes-specific)
- Personas manager
- RAG settings: chunk size, top-k, reranking toggle
- Embedding model config

---

## BourBites Integration
- BourBites `/context` endpoint (`http://100.114.205.53:8600/context`) available as a toggleable knowledge source per DAW in 808notes
- Not on by default — explicitly toggled per chat
- Always available when enabled, no manual import needed

---

## Profile & Identity
- User profile icon: global upload, overridable per mode (not per DAW)
- AI icon: per persona, defaults to mode mascot (westie/808 speaker)
- Memory: global + per-mode additive

---

## What Is NOT Being Built (v1)
- Podcast / audio / video generation
- Voice STT / TTS
- Image generation
- Web scraping
- GitHub repo ingestion
- Auth / multi-user
- Deep research mode (BooOps — later)
- Cross-DAW notebook sharing (later)
- code-server integration (later)
- Mobile PWA install (later)
