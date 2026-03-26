# Continue work — copy-paste for the next session

Use this as the **opening message** (or paste into Cursor “custom instructions” for the session) so the agent picks up where boolab left off without re-discovering the repo.

---

## Context to attach in Cursor
Add these files to the chat context:
- `IMPLEMENTATION_PLAN_2.md` (current truth for done/partial/next)
- `SPEC.md` / `DB_SCHEMA.md` (product + schema)
- For the task at hand: e.g. `backend/routers/chats.py`, `backend/schema.sql`, relevant `frontend/src/pages/booops/...`

---

## Where the project is
- **BooOps is the live app**: `frontend/src/App.jsx` only mounts `BooOpsApp` when `APP_MODE === 'booops'` (`frontend/src/mode.js` handles subdomain / `VITE_APP_MODE`).
- **Stack**: FastAPI + asyncpg; Postgres schema from `backend/schema.sql` on API startup; React/Vite UI; Docker Compose (`boolab_api`, `boolab_ui`, `boolab_db`, `boolab_chroma`).
- **Chat**: Streaming messages, Ollama + Claude, pruning summary, fork at message, persona + DAW on chat, **mode memory** (`mode_memory`) + custom instructions + DAW context files in `_assembled_system_prompt`.
- **Web search**: Per-chat flag; SearX via `services/searx.py`; SSE `search_sources`; UI collapsible “Web Sources” in `MessageList.jsx`.
- **Settings**: Rich BooOps branding/settings in `SettingsPage.jsx` + `/api/branding` (not `/api/settings/booops`).
- **AI surface**: `/ai` → `AISettings.jsx` (personas, memory blob + entries, DAWs, custom instructions); DAW pages under `/daws`.

---

## Immediate priorities (do in order unless told otherwise)
1. **Finish Phase 3 prompt parity**
   - Inject **`daw_instructions`** content into `backend/routers/chats.py` → `_assembled_system_prompt` (after DAW `system_prompt`, consistent with SPEC).
   - Decide and implement how **`memory_entries`** should affect prompts (append to system text vs sync into `mode_memory` vs UI-only archive). SPEC implies user facts should reach the model.
2. **After that**, start **808notes vertically**: extend `App.jsx` for `808notes` with a minimal shell route (even placeholder) that still loads shared providers; then Phase 5 slice (sources + RAG) per `IMPLEMENTATION_PLAN_2.md`.

---

## Constraints (do not regress)
- Prefer **plain React dropdowns** with `position: fixed` + `getBoundingClientRect()` where the codebase already does (see `ModelSelectorBar`, `AISettings` patterns). Avoid Radix Portal for those menus unless a file already uses it consistently for that control.
- **No hardcoded theme hex in new UI** — use CSS variables / branding tokens.
- **System prompt assembly stays server-side** in `chats.py`; frontend only selects persona/DAW/model/search flag.
- Keep changes **focused**: avoid drive-by refactors and unrequested new markdown files.

---

## Quick verification commands
- From repo root with Docker: `docker compose up --build` (API `:9300`, UI `:9301` per `SPEC.md`).
- Local dev: set `VITE_APP_MODE=booops` if hostname is not booops.

---

## If stuck
- Re-read **`IMPLEMENTATION_PLAN_2.md`** “Known inconsistencies” and “Suggested order of work”.
- Compare **`phase3.md`** to current code — the Cursor prompt there is older than the UUID/`daws` schema; trust **`DB_SCHEMA.md`** + **`schema.sql`**.
