# Agent context — start here

One-page bootstrap for coding sessions. Keep this aligned with the live branch,
not just the latest tag.

**Latest tagged release:** `v1.2.16` (2026-06-08)  
**Main branch state:** 2026-06-12 behavioral fixes, dead code cleanup, and memory wiring landed on `main` after `fork-lift-wave-1`; not tagged yet  
**Active work:** stack smoke test (`docker compose build --no-cache hlh_api`), `single-patient-demo` admin-CTA hiding + end-to-end verification

---

## Doc hierarchy

| Read when… | File |
|------------|------|
| Every session | [CLAUDE.md](../CLAUDE.md) |
| System structure | [architecture.md](architecture.md) |
| Release state / history | [CHANGELOG.md](../CHANGELOG.md) |
| Long-range shipped roadmap | [roadmap.md](roadmap.md) |
| Active batch work | `openspec/changes/<slug>/` |
| Archived completed batches | `openspec/archived/<slug>/` |

---

## Key files by area

| Area | Files |
|------|-------|
| App entry | `backend/main.py`, `frontend/src/components/AppRoutes.jsx` |
| Auth | `backend/deps.py`, `backend/services/auth.py`, `backend/routers/auth.py`, `backend/routers/profile.py` |
| Chat orchestration | `backend/routers/chats.py`, `backend/services/inference_job.py`, `backend/services/approval_gate.py`, `backend/services/conductor.py` |
| Frontend streaming | `frontend/src/hooks/useStreamOrchestrator.js`, `frontend/src/hooks/useDurableChat.js`, `frontend/src/hooks/useStream.js` |
| RAG | `backend/services/rag.py`, `backend/services/embeddings.py`, `backend/services/chunking.py` |
| Sources / ingest | `backend/routers/sources.py`, `backend/services/vision.py`, `backend/routers/demo.py` |
| Memory | `backend/services/memory/`, `backend/services/memory_tools.py`, `backend/routers/memory.py` |
| Providers / models | `backend/services/provider_client.py`, `backend/services/bundled_providers.py`, `backend/services/model_puller.py`, `backend/routers/models.py` |
| Eval / analytics | `backend/routers/eval.py`, `backend/routers/analytics.py`, `frontend/src/pages/workspace/AnalyticsPage.jsx` |
| Safeguards | `backend/services/safeguards.py`, `backend/services/safeguards_engine.py`, `backend/services/guard.py` |
| Schema | `backend/schema.sql` |

---

## Current architecture in one line

`hlh_ui` → `hlh_api` → PostgreSQL + bundled `hlh_chat` router for chat/embed/rerank/vision, plus bundled `hlh_search` for web search.

---

## Verify (no pytest)

```bash
python3 -m py_compile $(find backend -name '*.py')
cd frontend && npm run build
docker compose build --no-cache hlh_api && docker compose up -d hlh_api
docker exec hlh_api python -m hlh.doctor
backend/scripts/verify_providers_crud.sh
```

Current harness: 26 scripts under `backend/scripts/verify_*.{sh,py}`. Add one
per new endpoint or major UI surface.

---

## Docker quirks

- `docker compose build --no-cache hlh_api` after Python edits. BuildKit can cache stale `COPY . .`.
- `docker cp` fails into `read_only: true` containers such as `hlh_api` and `hlh_chat`.
- `hlh_api` has no `curl`. Use Python + `httpx` inside the container.
- `VITE_*` values are baked at build time. Frontend changes need `docker compose up --build -d`.

---

## Current focus

- **Behavioral fixes + cleanup** (2026-06-12): approval gate (A1), source-selection position (A2), provider bypass removal (A3), BM25 partitioning (A4), flush failure surfacing (A6), model_puller races (C4/C9), chat-switch resume (C7), dead code (S4/S8/S10), memory hook wiring -- all implemented; stack smoke test still needed.
- **`single-patient-demo`**: demo data + atomic loader + Try Demo button all done. Remaining: non-admin CTA hiding (Task 4) and end-to-end stack verification (Tasks 6-7).
- **A9 (hook context reset)** is explicitly deferred: the `try/finally reset_hook_context` wrapper around the 730-line `post_messages` handler is too risky to add without a dedicated smoke test pass.
