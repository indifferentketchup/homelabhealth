# BooLab (boolab)

Self-hosted AI chat platform with **Digital AI Workspaces (DAWs)**: scoped chats, personas, optional RAG over your sources, memory facts, a reusable skills library, branding, and multiple front-door SPAs from one codebase.

See [`CHANGELOG.md`](CHANGELOG.md) for recent changes.

## What’s in the repo

| Area | Stack |
|------|--------|
| **API** | Python [FastAPI](https://fastapi.tiangolo.com/), async PostgreSQL ([asyncpg](https://magicstack.github.io/asyncpg/)), schema applied on startup |
| **Database** | PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector) for embeddings and retrieval |
| **Web UI** | React 18, Vite, Tailwind, shadcn/ui, Zustand, TanStack Query — one `frontend/` tree, **three build modes** |
| **Inference** | Bifrost gateway → llama-swap → llama.cpp for local models; embeddings via infinity-emb + BAAI/bge-m3 (1024 dims); rerank via infinity-rerank with flashrank fallback; optional Anthropic Claude routes |

Three Docker images are built from the same frontend with different `VITE_APP_MODE`:

- **Boolab** (`boolab`) — hub / picker experience  
- **BooOps** (`booops`) — “corporate DAW” product face  
- **808notes** (`808notes`) — alternate product face, upload-scoped sources/RAG emphasis

Default compose publishes **API 9300**, **Boolab UI 9302**, **BooOps 9303**, **808notes 9304** (overridable via env).

## Documentation (RAG & memory overhaul)

The **master spec** is [`Docs/00_SPEC.md`](Docs/00_SPEC.md) (last updated **April 2, 2026**). It describes the move toward selective context: non-DAW chats without RAG/memory dump, DAW chats with similarity thresholds, intent gating, hybrid search, and embedded memory facts.

Phase implementation notes (read before changing those subsystems):

| Doc | Topic |
|-----|--------|
| [`Docs/01_similarity_threshold.md`](Docs/01_similarity_threshold.md) | RAG cosine distance cutoff |
| [`Docs/02_non_daw_rag_disable.md`](Docs/02_non_daw_rag_disable.md) | Gate memory/RAG on `daw_id` |
| [`Docs/03_intent_gate.md`](Docs/03_intent_gate.md) | When BooOps DAW skips RAG |
| [`Docs/04_memory_embeddings.md`](Docs/04_memory_embeddings.md) | Memory table embeddings + retrieval |
| [`Docs/05_hybrid_search.md`](Docs/05_hybrid_search.md) | pg_trgm + vector hybrid scoring |
| [`Docs/06_rag_ui.md`](Docs/06_rag_ui.md) | RAG mode UI, indicators, source embedding status |
| [`Docs/07_memory_ui.md`](Docs/07_memory_ui.md) | AI Settings memory tab + API |

Reference context for integrations lives under [`Docs/References/`](Docs/References/).

## Quick start (Docker)

1. Copy [`.env.example`](.env.example) to `.env` and set at least `BOOLAB_PUBLIC_HOST`, `DATABASE_URL` (if not using compose defaults), and `OLLAMA_URL` / model names for your machine.
2. From the repo root:

```bash
docker compose up -d
```

3. Health check: `GET http://localhost:9300/health` (or your `BOOLAB_PORT_API`).

Split deployments can use `docker-compose.core.yml` and `docker-compose.ui.yml`; see comments in the compose files.

## Local development (sketch)

- **API**: Python venv in `backend/`, install `backend/requirements.txt`, run uvicorn against `main:app` with the same env as production (DB, Ollama, etc.).
- **Frontend**: `cd frontend && npm install && npm run dev` — use the appropriate `frontend/.env.*` for the mode you’re testing; Vite can proxy `/api` to the API (see `.env.example` `BOOLAB_VITE_API_PROXY`).

The API applies [`backend/schema.sql`](backend/schema.sql) on startup; align DB changes with that file and any phase notes in `Docs/`.

## Configuration highlights

See [`.env.example`](.env.example) for the full list. Notable groups:

- **RAG / memory tuning** (when implemented per spec): `RAG_SIMILARITY_THRESHOLD`, `MEMORY_SIMILARITY_THRESHOLD`, `RAG_INTENT_GATE_ENABLED`, `RAG_MIN_WORDS_FOR_INTENT`
- **Models**: `OLLAMA_URL`, `DEFAULT_MODEL`, `EMBEDDING_MODEL`
- **CORS / cookies**: `FRONTEND_ORIGIN`, `BOOLAB_PUBLIC_HOST`, optional `VITE_AUTH_COOKIE_DOMAIN`

## Project layout

```
backend/          FastAPI app, routers, RAG services, schema
frontend/       React SPA (Boolab / BooOps / 808notes builds)
Docs/           Spec and phased implementation notes
docker-compose*.yml
.env.example    Template for secrets and service URLs
```

## License / ownership

Private project; no license file is asserted in this README. Use and deployment terms are whatever the repository owner defines.
