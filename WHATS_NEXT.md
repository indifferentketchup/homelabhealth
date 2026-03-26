# boolab — What’s left & what’s next

Last updated: March 2026

This file complements `IMPLEMENTATION_PLAN.md`: that document is the full vision; this one tracks **remaining work**, **known gaps**, and a **phased order** for what to do next. BooOps (Phases 0–4) is largely in place; the big unfinished slice is **808notes + RAG** and **cross-app polish**.

---

## Snapshot — where things stand

| Area | Status |
|------|--------|
| Docker, API, DB schema on startup, Vite UI | Done |
| BooOps chat (Ollama + Claude), CRUD, streaming, fork, pruning | Done |
| BooOps branding & settings (BooOps-focused) | Largely done |
| DAWs, personas, context files, custom instructions, mode memory blob | Largely done |
| Web search (SearXNG), per-chat toggle, citations in UI | Largely done |
| `memory_entries` CRUD + UI vs **injection into system prompt** | Gap — entries are not merged into `_assembled_system_prompt` (only `mode_memory` is) |
| Search API shape vs doc | `POST /api/search/` body, not `GET ?q=` — optional doc alignment |
| 808notes mode UI, RAG, sources, notes APIs | Not built (schema anticipates some tables) |
| boolab landing, sidebar cross-links, BourBites | Not built |
| `IMPLEMENTATION_PLAN.md` checkboxes | Stale — consider syncing when milestones close |

---

## Phase A — Close BooOps gaps (short horizon)

**Goal:** No loose ends on the path you already use daily.

1. **Memory model** — Decide and implement one of: inject `memory_entries` into the system prompt (e.g. append after mode memory), or merge them into the markdown blob on save and keep a single injection path. Update AI Settings copy if behavior changes.
2. **Plan / API consistency** — Optionally align `WHATS_NEXT` + `IMPLEMENTATION_PLAN` search endpoint description with `POST /api/search/`.
3. **UX polish from Phase 1–3 checklists** — Confirm pinned DAWs, DAW badges on chat rows, and mobile sidebar behavior match the plan; fix any drift.
4. **Documentation** — Refresh `IMPLEMENTATION_PLAN.md` checkboxes for Phases 0–4 when you accept them as done.

**Done when:** Memory behavior matches your mental model; BooOps checklist items you care about are either implemented or explicitly deferred.

---

## Phase B — 808notes shell + routing

**Goal:** `808notes` host loads a real app shell (not the Phase 1 placeholder), shared layout patterns, mode-correct branding.

1. **`App.jsx` (or route tree)** — Mount 808notes routes when `APP_MODE === '808notes'`.
2. **Branding** — 808notes palette and `branding_config` for mode `808notes` (backend may need parity with BooOps branding routes).
3. **Navigation** — Skeleton for three-panel layout (chats | chat | sources/notes) even if panels are empty.

**Done when:** You can open 808notes on the right subdomain and see the correct mode, shell, and empty panels without errors.

---

## Phase C — RAG pipeline (backend-first)

**Maps to implementation plan Phase 5 (backend portions).**

1. **Routers** — `/api/sources/` (upload, list, delete, groups), embedding pipeline, Chroma namespacing by DAW, `/api/rag/query` (retrieve + optional rerank).
2. **Parsers & chunking** — PDF, DOCX, text-like formats, URL fetch, configurable chunk size/overlap.
3. **Chat integration** — When RAG is enabled and sources are selected, inject retrieved context into the same chat streaming path used by BooOps (808notes mode).

**Done when:** A document uploaded to a DAW embeds and returns chunks from `/api/rag/query` in isolation; then wired into chat.

---

## Phase D — 808notes UI (sources + RAG chat)

**Maps to implementation plan Phase 5 (frontend).**

1. DAW cards landing for 808notes, three-panel layout, sources panel with upload, progress, selection persistence.
2. RAG-grounded chat using the shared chat component with 808notes defaults.
3. Source / web / general toggles and mobile nav as in the plan.

**Done when:** “Drop a PDF into an 808notes DAW and chat grounded in it” works end-to-end.

---

## Phase E — Notes (Phase 6)

1. Backend: notes CRUD, groups, `from-message`, `to-source`, search, Chroma for embedded notes if required.
2. Frontend: bottom panel, editor, save-from-message, convert to source.

**Done when:** Save AI reply as note, convert note to source, search notes.

---

## Phase F — 808notes settings + branding depth

**Maps to implementation plan Phase 7.**

1. `GET/PUT` settings for 808notes branding (parity with BooOps scope).
2. RAG settings: chunk size, top-k, rerank toggle, embedding model.

---

## Phase G — BourBites integration

**Maps to implementation plan Phase 8.**

1. `GET /api/bourbites/context` (or equivalent), cache, optional embed path per DAW.
2. Special source row + refresh in 808notes UI.

---

## Phase H — Polish & cross-app (Phase 9)

1. boolab landing (two cards), boolab global settings page.
2. Sidebar links: BourBites ↔ BooOps ↔ 808notes; shared DAW switcher tabs under banner.
3. Toasts, skeletons, empty/error states, keyboard shortcuts, mobile pass.

---

## Later (post–v1)

As in `IMPLEMENTATION_PLAN.md`: deep research mode, cross-DAW sharing, code-server, PWA, auth, export, templates, bulk chat ops.

---

## Suggested order

1. **Phase A** if memory semantics or small BooOps gaps block you.  
2. **Phase B** then **C** then **D** for the core 808notes product.  
3. **E → F → G → H** in order unless BourBites is urgently needed earlier (then G after D).

---

## Related docs

- `IMPLEMENTATION_PLAN.md` — full phased feature list and “done when” criteria  
- `boolab_context.md` — deploy URLs, env, stack  
- `phase3.md` — historical Phase 3 Cursor prompt (schema/API may have evolved; prefer code + `schema.sql`)
