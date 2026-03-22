# boolab — Context
Last updated: March 2026

## What it is
Unified AI workspace platform. Two branded modes in one app:
- **BooOps** — general AI chat, replaces Open WebUI (booops)
- **808notes** — NotebookLM-style notebook workspace, replaces open-notebook

## Location
- Stack: `/opt/boolab/` on ubuntu-homelab (`100.114.205.53`)
- Public URLs:
  - `https://booops.boogaardmusic.com` → BooOps mode
  - `https://808notes.boogaardmusic.com` → 808notes mode
  - `https://boolab.boogaardmusic.com` → landing page
- API: `100.114.205.53:9300` (container: `boolab_api`)
- Frontend: `100.114.205.53:9301` (container: `boolab_ui`)
- ChromaDB: internal only (container: `boolab_chroma`)
- Database: `boolab_db` (Postgres 16, internal Docker network)

## Docker
- Compose: `/opt/boolab/docker-compose.yml`
- Network: `boolab_net` (internal bridge)
- Env: `/opt/boolab/.env`
- Volumes:
  - `boolab_db_data` — Postgres data
  - `boolab_chroma_data` — ChromaDB vector store
  - `boolab_uploads` — uploaded source files
  - `boolab_branding` — branding assets (banners, logos, icons)

## Key env vars
```
DATABASE_URL=postgresql+asyncpg://...
CHROMA_HOST=boolab_chroma
CHROMA_PORT=8000
OLLAMA_URL=http://100.101.41.16:11434
EMBEDDING_MODEL=qwen3-embedding:latest
SEARXNG_URL=http://100.114.205.53:8888
ANTHROPIC_API_KEY=...
BOURBITES_CONTEXT_URL=http://100.114.205.53:8600/context
FRONTEND_ORIGIN=https://booops.boogaardmusic.com,https://808notes.boogaardmusic.com,https://boolab.boogaardmusic.com
```

## Frontend
- React 18 + Vite + shadcn/ui + Tailwind CSS
- Build output: `/opt/boolab/frontend/dist/`
- Mode detection: `window.location.hostname` → sets `APP_MODE` to `booops` | `808notes` | `boolab`
- Branding CSS vars swapped on mode change
- All shadcn/ui components styled via CSS variables — no Tailwind theme config required

## Backend
- FastAPI + asyncpg, Python 3.12
- Source: `/opt/boolab/backend/`
- Schema auto-runs on startup from `schema.sql`
- Requires rebuild for Python changes: `docker compose build boolab_api && docker compose up -d`
- Frontend changes: `docker compose build boolab_ui && docker compose up -d` (Vite build step required)

## RAG Pipeline
- Embeddings: `qwen3-embedding:latest` via Ollama on sam-desktop
- Vector store: ChromaDB collections namespaced by DAW ID
- Chunking: configurable chunk size (default 512 tokens, 64 overlap)
- Reranking: flashrank cross-encoder second pass
- Top-k: configurable per 808notes settings (default 6)

## Deploy Pattern
```bash
# Full deploy (backend + frontend changes):
sudo tar -xzf /tmp/boolab_vN.tar.gz -C /opt/boolab
cd /opt/boolab && docker compose build && docker compose up -d

# Backend only:
sudo tar -xzf /tmp/boolab_vN.tar.gz -C /opt/boolab
cd /opt/boolab && docker compose build boolab_api && docker compose up -d

# Frontend only (still requires build):
sudo tar -xzf /tmp/boolab_vN.tar.gz -C /opt/boolab
cd /opt/boolab && docker compose build boolab_ui && docker compose up -d
```
Note: Unlike BourBites (vanilla JS), React requires a build step — no live file edits.

## Caddy (on droplet `/opt/caddy/Caddyfile`)
All three subdomains proxy to `100.114.205.53:9301`. Mode is handled client-side.
```
booops.boogaardmusic.com {
    reverse_proxy 100.114.205.53:9301
}
808notes.boogaardmusic.com {
    reverse_proxy 100.114.205.53:9301
}
boolab.boogaardmusic.com {
    reverse_proxy 100.114.205.53:9301
}
```
API calls from frontend go to `booops.boogaardmusic.com/api/*` → Caddy strips and proxies to `:9300`.

## Key API Modules
```
/api/daws/          DAW CRUD, icon upload, context files
/api/chats/         Chat CRUD, message streaming, forking, pruning
/api/sources/       Source upload, embedding, deletion, grouping
/api/notes/         Note CRUD, embed-as-source conversion
/api/personas/      Persona CRUD
/api/memory/        Memory CRUD
/api/settings/      Branding config (per mode), global settings
/api/search/        SearXNG proxy
/api/rag/           Query endpoint (retrieval + reranking)
/api/ollama/        Ollama proxy (model list, chat)
/api/claude/        Claude API proxy
/api/bourbites/     BourBites /context fetch + cache
```

## Branding System
- Stored in Docker volume `boolab_branding` at `/data/branding/`
- Three config files: `booops.json`, `808notes.json`, `boolab.json`
- CSS variables injected at runtime based on active mode
- Assets: banners, logos, favicons served from `/api/branding/assets/`

## Linked Apps (sidebar)
- BourBites: `https://bourbites.boogaardmusic.com`
- boolab landing: `https://boolab.boogaardmusic.com` (bottom-left nav button, new tab)

## Known Patterns from Other Apps
- All file uploads via multipart to backend, stored in volume
- `ON CONFLICT DO NOTHING` on all seed inserts
- Never bind containers to 0.0.0.0 externally — internal network only, Caddy terminates TLS
- Tailscale handles all auth for now
- Context pruning: summarize-and-compress via Ollama after configurable message threshold
