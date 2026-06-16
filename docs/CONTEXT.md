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

> **In flight (boofinity inference split, see `docs/adr/0001`–`0003`):** embed/rerank/VL move off the `hlh_chat` llama.cpp router onto **boofinity**, with **llama-swap** as the front-door that swaps the two backends per a VRAM budget. The "one line" above describes the pre-split state until that change lands.

---

## Domain glossary — inference & retrieval

Canonical terms for the boofinity split. Glossary only; the "how" lives in `openspec/changes/` and the "why" in `docs/adr/`.

| Term | Meaning |
|------|---------|
| **boofinity** | First-party fork of `michaelfeil/infinity` (repo `indifferentketchup/boofinity`). The embed/rerank/VL inference server. Always call it *boofinity*, never *infinity*. Ships as `ghcr.io/indifferentketchup/boofinity:<ver>-{cpu,cuda}`. |
| **`hlh_infer`** | The boofinity container (the long-scaffolded "ghost" service: pinned in `image_config.py`, checked by `doctor.py`, asserted by verify scripts, but never added to `docker-compose.yml` until this change). Serves text embed + text rerank on all bundled tiers; VL embed + VL rerank on GPU tiers only. |
| **llama-swap front-door** | llama-swap (v226+) as the single inference entry point. Lazily starts/stops the **llama.cpp** process (chat/tasks/vision-mmproj) and the **boofinity** process (embed/rerank/VL) so they don't both pin VRAM. Replaces direct `hlh_chat:9610` router access. |
| **resource policy** | HLH-side, tier-aware rules (a module beside `image_config.py`) deciding which models may coexist and, under VRAM pressure, whether **Gemma** *offloads to CPU* (slow) or goes *unavailable + warning*. llama-swap performs the mechanical swap; HLH owns the policy and surfaces state via `pipeline_status.py`. |
| **text-embedding space** | The existing `source_chunks.embedding vector(1024)` index, produced by the text embedder (Qwen3-Embedding-0.6B). Unchanged by this work, on every tier. |
| **image-embedding space** | New, separate `vector(1024)` space produced by **Qwen3-VL-Embedding-2B** at ingestion (gpu-24gb+ only). NOT cosine-comparable to the text-embedding space — a distinct model. Queries embed into both spaces; candidates fuse and are ordered by the **Qwen3-VL reranker**. |
| **dual-space retrieval** | The additive retrieval topology: text path unchanged on all tiers; native image retrieval added on top, on GPU tiers only. Images on lesser tiers keep the MedGemma-read-to-text fallback (`services/vision.py`). |

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
