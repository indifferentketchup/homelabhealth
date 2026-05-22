# homelabhealth

Self-hosted, single-user RAG chat app for personal records. Upload documents to a workspace, ask questions, get answers grounded in your sources via pgvector retrieval. Bring your own inference and embedding endpoints — anything OpenAI-compatible.

Roadmap (built-in AI, safeguards, security): see [docs/roadmap.md](docs/roadmap.md) — the source of truth for both AI and security plans.

## Quickstart

```bash
git clone <repo>
cd homelabhealth
cp .env.example .env
# Edit .env: set INFERENCE_URL, DEFAULT_MODEL, EMBEDDING_URL
docker compose up --build -d
# Open http://localhost:<port>  (port set in .env / docker-compose.yml)
```

The schema applies on startup; no manual migrations.

**First boot:** the embedding sidecar (`hlh_infer`) downloads model weights from HuggingFace on first start — `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`, ~1–2 GB total. Expect **5–15 minutes** before chat works end-to-end; the container restart-loops as `unhealthy` until the pull finishes. After first boot, weights are cached in the `hlh_models` Docker volume — subsequent boots are instant.

## Required env vars

| Var | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string. Default points at the `db` service in compose. |
| `INFERENCE_URL` | Base URL of an OpenAI-compatible chat completions endpoint. The API hits `${INFERENCE_URL}/v1/chat/completions` and `/v1/models`. |
| `DEFAULT_MODEL` | Model id served by `INFERENCE_URL`. Required — the API raises if unset. |
| `EMBEDDING_URL` | Base URL of an OpenAI-compatible `/embeddings` endpoint. Embeddings must produce 1024-dim vectors (default model: `BAAI/bge-m3`). |
| `EMBEDDING_MODEL` | Model id served by `EMBEDDING_URL`. Default `BAAI/bge-m3`. |
| `RERANKER_URL` | Optional. Rerank server for retrieved chunks. Falls back to in-process `flashrank` (CPU) if unset or unreachable. |
| `SEARXNG_URL` | Optional. SearXNG instance for web search. Empty = web search disabled. |
| `FRONTEND_ORIGIN` | Comma-separated extra CORS origins. |

See `.env.example` for the full list with comments.

## Bring your own inference

`INFERENCE_URL` points at any OpenAI-compatible chat completions server:

- [llama-swap](https://github.com/mostlygeek/llama-swap) — multi-model swap proxy on top of llama.cpp.
- [llama.cpp server](https://github.com/ggerganov/llama.cpp) — `llama-server -m <model.gguf> --host 0.0.0.0 --port 8080`.
- [Ollama](https://ollama.com/) — set `INFERENCE_URL=http://localhost:11434`.
- [vLLM](https://github.com/vllm-project/vllm) — `--api-server` mode with OpenAI compatibility.
- Any server implementing `POST /v1/chat/completions` (streaming, SSE) and `GET /v1/models`.

If your endpoint requires a bearer token, set `OPENAI_API_KEY` and the API forwards it as `Authorization: Bearer …`.

## Bring your own embeddings

`EMBEDDING_URL` points at any OpenAI-compatible `/embeddings` server. The schema is fixed at 1024-dimension vectors (pgvector column type). Match it with `BAAI/bge-m3` or any other 1024-dim model.

- [infinity](https://github.com/michaelfeil/infinity) — fast embedding + rerank server with OpenAI API.
- Hosted: any provider whose `POST /v1/embeddings` returns the OpenAI shape.

## Auth

Single-user app — every request is treated as the owner. For real authentication, put a reverse proxy in front of the API container: [oauth2-proxy](https://oauth2-proxy.github.io/), [Authelia](https://www.authelia.com/), nginx basic auth, etc. The principal returned to handlers is the seeded owner row from the `users` table.

## Stack

| Area | Tech |
|---|---|
| API | FastAPI (Python 3.12), asyncpg |
| Database | PostgreSQL 16 + pgvector |
| Web | React 18, Vite, Tailwind, shadcn/ui, Zustand, TanStack Query |
| Embeddings | OpenAI-compatible `/embeddings`; pgvector storage (1024 dim) |
| Rerank | OpenAI-compatible `/rerank` with `flashrank` CPU fallback |

## License

TBD
