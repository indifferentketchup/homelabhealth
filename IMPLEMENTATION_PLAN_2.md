# boolab — Implementation Plan v2
Last updated: March 25, 2026

This plan **supersedes checkboxes in `IMPLEMENTATION_PLAN.md`** for tracking what actually exists in the repo today. Original phase numbers are kept for alignment with `SPEC.md` and team discussion.

---

## How to use this file
- Treat **Done / Partial / Not started** as ground truth from the codebase (FastAPI routers, `schema.sql`, `frontend/src`).
- When you finish a slice, update this file or fold changes back into `IMPLEMENTATION_PLAN.md`.
- **Schema and API paths diverged** from the March 2026 outline in places: IDs are UUIDs; branding lives under `/api/branding`, not `/api/settings/booops`; memory uses a **`mode_memory`** markdown blob for chat injection plus a separate **`memory_entries`** table.

---

## Phase 0 — Project skeleton
| Status | Item |
|--------|------|
| Done | `docker-compose.yml`: `boolab_api`, `boolab_ui`, `boolab_db`, `boolab_chroma`; uploads + branding volumes |
| Done | FastAPI app: lifespan DB pool, `apply_schema()`, CORS, `/health` |
| Done | Full Postgres schema in `backend/schema.sql` (wide surface area including future 808notes tables) |
| Done | React + Vite + Tailwind + shadcn/ui |
| Done | Subdomain / dev mode detection: `frontend/src/mode.js`, `data-mode` on `<html>` |
| Done | BooOps branding applied from API + CSS variables (`SettingsPage.jsx`, `api/branding.js`) |
| Partial | **808notes / boolab palettes**: mode detection exists; `App.jsx` still shows a **placeholder** for non-booops modes |
| Not in repo | **Caddy** (or reverse proxy) config for three hostnames — deploy step, not versioned here |
| Done | `.env` pattern for API (see `docker-compose` `env_file`) |

**Done when (adjusted):** Local Docker brings up API + UI + DB + Chroma; BooOps chat works at `VITE_APP_MODE=booops` or booops host. Production TLS/host routing is external to this repo unless you add a `Caddyfile`.

---

## Phase 1 — BooOps core chat
| Status | Item |
|--------|------|
| Done | Ollama: models + streaming chat (`routers/ollama.py`) |
| Done | Claude proxy + streaming (`routers/claude.py`); model routing in `chats.py` |
| Done | `chats` / `messages` schema, CRUD + list + delete patterns (`routers/chats.py`) |
| Done | Streaming `POST /api/chats/{id}/messages` with SSE; title updates |
| Done | Frontend: sidebar, `ChatView`, markdown (`react-markdown`), `ModelSelectorBar`, stop/send |
| Done | **Context pruning**: `services/pruning.py` + `pruning_summary` on chats |
| Done | **All Chats**: route `/chats` → `AllChats.jsx` |
| Partial | `+` menu: **web search toggle** implemented in `ChatInput.jsx`; upload/persona stubs may still be minimal |
| Partial | **User profile / AI icons**: branding + persona icons exist; confirm global profile upload matches SPEC everywhere |

**Done when (adjusted):** Streaming Ollama + Claude from BooOps UI; pruning runs; remaining gaps are polish and profile/icon parity with SPEC.

---

## Phase 2 — BooOps settings + branding
| Status | Item |
|--------|------|
| Done | Branding storage: `branding_config` + asset files under `/data/branding` |
| Done | `GET/PATCH` branding (`routers/branding.py`), asset upload/delete |
| Done | Settings UI: colors, typography, layout, Ollama tooling (`SettingsPage.jsx`) |
| Done | Default model / hidden models via Ollama settings API |
| Partial | **`boolab` landing/settings**: placeholder `App.jsx` shell only |
| N/A as named | Original plan’s `GET/PUT /api/settings/booops` — **implemented as `/api/branding/...`** |

**Done when (adjusted):** BooOps theming is end-to-end; boolab-specific global page still open.

---

## Phase 3 — DAWs + personas + memory (BooOps)
| Status | Item |
|--------|------|
| Done | DAWs: CRUD, `system_prompt`, `persona_id`, `mode`, pin flags, icon upload (`routers/daws.py`) |
| Done | `daw_context_files`: upload/list/delete, injection in **`_assembled_system_prompt`** (`chats.py`) |
| Done | Chat carries `daw_id`, `persona_id`; `PATCH` chat; assembly order: persona → DAW prompt → context files → custom instructions → **mode memory** |
| Done | Personas: CRUD, default per mode, emoji + icon (`routers/personas.py`) |
| Done | **Mode memory**: `mode_memory` table; GET/PUT + Ollama **extract** (`routers/memory.py`); injected in chat |
| Done | **Memory entries**: CRUD endpoints (`/api/memory/entries/...`); UI in `AISettings.jsx` |
| Done | **Custom instructions**: global + per-mode scope (`routers/custom_instructions.py`); editors in AI settings |
| Done | AI Settings page: personas, memory (blob + entries), DAWs, instructions (`/ai`, `AISettings.jsx`) |
| Done | DAW grid + detail (`DawsPage.jsx`, `DawDetailPage.jsx`); pins in sidebar |
| Done | Per-chat persona + DAW selectors (`ModelSelectorBar.jsx`) |
| Done | **Conversation fork**: `POST .../messages/{id}/fork` + UI (`MessageBubble.jsx`) |
| **Gap** | **`daw_instructions` table + API exist** (`daws.py`) **but instructions text is not merged into `_assembled_system_prompt`**. Either inject it after DAW `system_prompt` or document removal. |
| **Gap** | **`memory_entries` are not injected** into the system prompt today — only `mode_memory`. SPEC describes bullet memory entries; decide: merge entries into the blob at save time, or append a second block in `chats.py`. |

**Done when (adjusted):** DAW + persona + mode memory + context files + custom instructions behave as one coherent prompt; **close the two gaps above** to match product intent.

---

## Phase 4 — Web search (BooOps)
| Status | Item |
|--------|------|
| Done | SearX integration: `services/searx.py`; results merged into message path when `web_search_enabled` |
| Done | **`web_search_enabled` on chat**; toggle persists via API; `ChatInput` + store |
| Done | SSE event `search_sources`; collapsible **Web Sources** above assistant bubble (`MessageList.jsx`) |
| Done | Standalone **`POST /api/search`** (`routers/search.py`) — note: original plan said `GET ?q=`; current API is POST body |

**Env:** ensure `SEARXNG` (or equivalent) URL is set for Docker/network reachability.

**Done when:** Grounded answers with search on; citations visible.

---

## Phase 5 — 808notes core
**Not started** in the hosted UI: `App.jsx` returns a stub for `808notes` / `boolab`.

Backend **includes** tables for `sources`, `notes`, `source_groups`, etc., but there are no 808notes routers or RAG pipeline wired in the same way as BooOps chat yet (see `RAG_PIPELINE.md` for intended design).

---

## Phases 6–9
Unchanged from `IMPLEMENTATION_PLAN.md`: notes UI, 808notes branding, BourBites, polish/cross-links — **not started** at app level.

---

## Known inconsistencies to resolve (technical debt)
1. **`daw_instructions` vs prompt assembly** — see Phase 3 gap.
2. **`memory_entries` vs `mode_memory`** — two systems; PRODUCT spec reads like entries should affect the model.
3. **Search API shape** — POST `/api/search` vs documented GET; client only needs chat path today.
4. **`phase3.md` / Cursor prompt** assumed SERIAL ids and a smaller schema; **real DB is UUID + expanded `daws`**. Treat `DB_SCHEMA.md` + `schema.sql` as source of truth.
5. **Persona seed SQL** — `INSERT ... ON CONFLICT (mode) WHERE ...` in `schema.sql` may need verification on fresh DBs (run migrations/tests).

---

## Suggested order of work (next slices)
1. **Close Phase 3 prompts**: inject `daw_instructions`; unify or wire `memory_entries` into the assembled system prompt (or explicitly deprecate one path).
2. **808notes Phase 0.5**: second shell in `App.jsx` (router + placeholder layout), load `808notes` branding keys, reuse query client.
3. **Phase 5 vertical slice**: one DAW, upload source, chunk+embed to Chroma, inject RAG block in chat for `mode=808notes` (even before full three-panel UI).
4. **Production**: version a `Caddyfile` or deployment doc; SearX + Ollama URLs for compose.

---

## Reference docs (keep in Cursor context)
- `SPEC.md`, `DB_SCHEMA.md`, `boolab_context.md`, `UI_DESIGN.md`, `RAG_PIPELINE.md`
- `IMPLEMENTATION_PLAN.md` (historical checklist), `phase3.md` (design notes; validate against code)
