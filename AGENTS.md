# Agent guide — homelabhealth

Entry point for Cursor and other coding agents. Human operators: see [README.md](README.md).

## Project

Self-hosted RAG chat for personal health records. **Bundled AI by default**
(llama.cpp + infinity-emb + SearXNG + MedGemma vision). Built-in username/password
auth. One Docker Compose stack.

| Area | Path |
|------|------|
| API | `backend/` — FastAPI 3.12, asyncpg |
| UI | `frontend/` — React 18, Vite, Tailwind, shadcn/ui |
| Schema | `backend/schema.sql` — idempotent, applied on startup |
| Architecture | [docs/architecture.md](docs/architecture.md) — containers, flows, data model |
| Session bootstrap | [docs/CONTEXT.md](docs/CONTEXT.md) |
| Roadmap | [docs/roadmap.md](docs/roadmap.md) |
| Releases | [CHANGELOG.md](CHANGELOG.md) |

**Current release:** `v0.26.0` (2026-05-25). Ship-to-friend gate is **clear** (A4 STT deferred).

## Hard rules

1. **Check `frontend/src/components/ui/`** before importing shadcn primitives — only use what exists.
2. **Never modify `frontend/src/hooks/useStream.js`.** Fragile SSE path; breaks all chat streaming.
3. **Schema changes:** idempotent only (`ADD COLUMN IF NOT EXISTS`). Reason before renaming/dropping.
4. **`CREATE EXTENSION IF NOT EXISTS vector;`** must precede any `vector(N)` column in `schema.sql`.
5. **Python in Docker:** `docker compose build --no-cache hlh_api` after backend source changes — plain `--build` can serve stale code.
6. **Providers:** use `services/provider_client.py` (`resolve_provider_for_workspace`, `resolve_embedding_provider`, `resolve_reranker_provider`). Never reintroduce deprecated env vars (`INFERENCE_URL`, `EMBEDDING_URL`, `RERANKER_URL`, `DEFAULT_MODEL`, `OPENAI_API_KEY` in call sites).

## Conventions (high-signal)

- **asyncpg JSONB:** pass `json.dumps(dict)` strings, not raw dicts.
- **asyncpg pgvector:** pass `str(embedding_list)` with `::vector` cast, not Python lists.
- **Wire-contract error strings** — do not paraphrase:
  - `"No provider configured for this workspace. Open Settings → Workspace to pick one."`
  - `"Embedding model not configured. Set one in Settings → Embedding."`
  - `"embedding dimension mismatch: expected 1024, got <N>"`
- **Verify scripts:** `backend/scripts/verify_*.{sh,py}` — add `verify_<feature>` for new endpoints/surfaces. No pytest runner.
- **CHANGELOG:** accrue under `[Unreleased]`; flip to tagged section on release.
- **Ports:** API `9600`, UI `9604`. Do not reuse `9300`/`9304` (sibling projects on Sam's host).
- **`hlh_api` has no curl** — probe with `docker exec hlh_api python -c "import httpx; ..."`.
- **`docker exec -it` fails without TTY** — drop `-it` in scripts.

## Before coding

1. Read [docs/CONTEXT.md](docs/CONTEXT.md) for active work and key files.
2. Read [docs/architecture.md](docs/architecture.md) when changing flows, sidecars, or schema.
3. For phased features: design in `docs/superpowers/specs/`, plan in `docs/superpowers/plans/`.
4. Read the service file you are changing before editing (especially `rag.py`, `chats.py`, `provider_client.py`).

## After coding

```bash
python -m py_compile $(find backend -name '*.py')
cd frontend && npm run build
docker compose build --no-cache hlh_api && docker compose up -d hlh_api
docker exec hlh_api python -m hlh.doctor
# Run relevant verify_*.sh / verify_*.py
```

## Review focus

1. Security — auth bypass, secrets, SQL injection
2. Error handling — unhandled async exceptions
3. Data integrity — races, orphans, missing constraints
4. Frontend state — stale closures, missing cleanup, loading/error UI
5. Performance — N+1 queries, unnecessary re-renders

## Local-only docs

`CLAUDE.md`, `.cursor/` (rules, skills), and `.cursorignore` are **gitignored** — keep
copies on your machine. **Committed:** this file, `AGENTS.md`, `docs/architecture.md`,
`docs/superpowers/specs/`.
