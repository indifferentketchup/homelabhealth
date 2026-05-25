# Agent context — start here

One-page bootstrap for coding sessions. Updated at phase boundaries.

**Release:** `v0.26.0` (2026-05-25)  
**Ship-to-friend gate:** clear (A4 STT deferred 2026-05-25)  
**Active work:** friend onboarding; v1.0.0 prep (LICENSE, README final pass, THREATMODEL review)

---

## Doc hierarchy

| Read when… | File |
|------------|------|
| Every session | [AGENTS.md](../AGENTS.md) (hard rules) |
| System structure | [architecture.md](architecture.md) — containers, flows, data model |
| Planning a phase | [roadmap.md](roadmap.md) — dependency graph + ship-to-friend gate |
| Designing a feature | `docs/superpowers/specs/YYYY-MM-DD-<phase>-design.md` |
| Implementing step-by-step | `docs/superpowers/plans/` (local plans; specs are committed) |
| Shipping a release | [CHANGELOG.md](../CHANGELOG.md) — `[Unreleased]` → tag |

---

## Key files by area

| Area | Files |
|------|-------|
| App entry | `backend/main.py`, `frontend/src/components/AppRoutes.jsx` |
| Auth | `backend/deps.py`, `backend/services/auth.py`, `backend/routers/auth.py` |
| Chat + SSE | `backend/routers/chats.py` — **do not touch** `frontend/src/hooks/useStream.js` |
| RAG | `backend/services/rag.py`, `embeddings.py`, `chunking.py` |
| Sources / ingest | `backend/routers/sources.py`, `services/vision.py` |
| Providers | `backend/services/provider_client.py`, `bundled_providers.py` |
| Safeguards | `backend/services/safeguards.py`, `guard.py` |
| Crypto / de-id | `backend/services/crypto.py`, `deid.py` |
| Schema | `backend/schema.sql` |
| Doctor | `backend/hlh/doctor.py` |
| Settings UI | `frontend/src/components/settings/SystemTab.jsx` |

---

## RAG pipeline (short)

ingest → chunk → embed (1024-dim, bge-m3) → pgvector → retrieve → rerank → inject into system prompt.

Tuning thresholds live in `global_settings` with env fallbacks — read `rag.py` before changing retrieval.

---

## Verify (no pytest)

```bash
python -m py_compile $(find backend -name '*.py')
cd frontend && npm run build
docker compose build --no-cache hlh_api && docker compose up -d hlh_api
docker exec hlh_api python -m hlh.doctor
backend/scripts/verify_providers_crud.sh   # example
```

Existing harness: 22 scripts under `backend/scripts/verify_*.{sh,py}`. Add one per new endpoint or UI surface.

---

## Docker quirks (common agent mistakes)

- **`docker compose build --no-cache hlh_api`** after Python edits — BuildKit can cache stale `COPY . .`.
- **`docker cp` fails** into `read_only: true` containers (`hlh_api`, `hlh_chat`, `hlh_infer`).
- **`hlh_api` has no curl** — use Python + httpx inside the container.
- **Vite `VITE_*`** — baked at build time; requires `docker compose up --build -d` after changes.

---

## Phase status (2026-05-25)

```
A — Built-in AI:   A0–A3, A7 shipped │ A4 STT deferred │ A6 MLX deferred
B — Safeguards:    B0–B3 shipped      │ B4 deferred
C — Security:      C0–C7 shipped      │ C8, C9 deferred
```

Next public milestone: **v1.0.0** — see roadmap "Public-release-readiness".
