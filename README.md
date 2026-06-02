# In development, not meant for public use. Will have bugs.
# homelabhealth

Self-hosted RAG chat app for personal health records. Upload medical documents (PDFs, images, lab reports), ask questions, get answers grounded in your sources via pgvector retrieval. Built-in AI with bundled llama.cpp inference, MedGemma vision for document understanding, and automatic safeguards.

One `docker compose up` to run. Built-in username/password auth. Encryption keys auto-generate on first launch. No reverse proxy required.

**Current release:** `v1.0.0` (2026-05-28). See [CHANGELOG.md](CHANGELOG.md) for the full history.

Roadmap: [docs/roadmap.md](docs/roadmap.md). Architecture: [docs/architecture.md](docs/architecture.md). Session bootstrap: [docs/CONTEXT.md](docs/CONTEXT.md).

## Quickstart

**Option A: One command (smart bootstrap — recommended)**

```bash
curl -fsSL https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/install.sh | bash
# Open http://localhost:9604
```

This installer brings the whole stack up — creates networks/volumes/secrets,
generates encryption keys, pulls every image, and starts everything in
dependency order (auto-detecting GPU) — **and** installs the `hlhstart` /
`hlhupdate` commands so you can start/update later without the long command. The
orchestra bootstraps once and exits; the stack keeps running on its own
(`restart: unless-stopped`) and comes back after a reboot.

Afterwards:
- `hlhstart` — start (or restart) the stack.
- `hlhupdate` — pull the latest images and recreate the stack (keeps your data + secrets).

<details><summary>Prefer the raw command / install the launchers by hand</summary>

```bash
# Start the stack without the installer:
docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/indifferentketchup/hlh_orchestra:latest

# Install the launchers manually:
sudo curl -fsSL -o /usr/local/bin/hlhstart  https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/hlhstart
sudo curl -fsSL -o /usr/local/bin/hlhupdate https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/hlhupdate
sudo chmod +x /usr/local/bin/hlhstart /usr/local/bin/hlhupdate
```
</details>

**Option B: Compose (clone + edit config)**

```bash
git clone https://git.indifferentketchup.com/indifferentketchup/homelabhealth.git
cd homelabhealth
cp .env.example .env
docker compose up -d
# Open http://localhost:9604
```

**Option C: Build from source (contributors)**

```bash
cd homelabhealth
cp .env.example .env
docker compose up --build -d
```

The frontend build needs ~1.5 GB RAM. Use Option A or B on low-memory hosts.

First launch walks you through setup: create your account, pick a hardware tier, and the system pulls the right models automatically.

**First boot:** the chat router (`hlh_chat`) loads model weights on demand. Embedding (bge-m3) and reranking (bge-reranker-v2-m3) GGUFs are included in the models volume. Expect the first chat message to take 30-60 seconds while the model loads. After first load, models stay cached.

**Doctor check:** `docker exec hlh_api python -m hlh.doctor` — shows DB, schema, sidecars, disk, encryption, vision, and more. Also at Settings → System → Pre-flight in the UI.

## What's included

See [docs/architecture.md](docs/architecture.md) for container topology, request flows, and data model.

| Feature | Details |
|---------|---------|
| **Bundled AI** | llama.cpp chat sidecar with MedGemma (4B or 27B by tier). No external API needed. |
| **Vision** | MedGemma multimodal — PDFs via page rendering + text extraction; standalone images get two-pass extraction (visible text + clinical interpretation). Falls back to pdfplumber/Tesseract. |
| **RAG** | Upload documents → chunk → embed (1024-dim, bge-m3) → pgvector → retrieve → rerank → inject into prompt. |
| **Auto-compaction** | Long conversations auto-summarize at 85% context usage. Older messages collapsed in UI, summary preserved for model. |
| **Safeguards** | Tiered refusal system prompt, I/O guard scanner (PII, medical advice, crisis, prompt injection), audit-logged refusals. |
| **Security** | Column encryption (AES-256-GCM), de-identification pipeline, container hardening, hash-chained audit log. |
| **Auth** | Built-in username/password. Sessions via `hlh_session` cookie. Setup wizard on first launch. |
| **Web search** | Bundled SearXNG meta-search for grounding against current web results. |

## Hardware tiers

The setup wizard detects your hardware and recommends a tier:

| Tier | Hardware | Chat model | Context | Vision |
|------|----------|-----------|---------|--------|
| cpu-min | <16 GB RAM, no GPU | Qwen3.5 0.8B | 8K | — |
| cpu-std | ≥16 GB RAM, no GPU | MedGemma 4B Q4 | 8K | MedGemma 4B |
| gpu-4gb | 4-5 GB VRAM | MedGemma 4B Q4 + offload | 32K | MedGemma 4B |
| gpu-8gb | 6-11 GB VRAM | MedGemma 4B Q8 | 32K | MedGemma 4B |
| gpu-16gb | 12-23 GB VRAM | MedGemma 27B Q4 | 32K | MedGemma 27B |
| gpu-24gb+ | ≥24 GB VRAM | MedGemma 27B Q4 | 64K | MedGemma 27B |
| external | Manual | Bring your own | Varies | Varies |

Tiers are set at first launch and can be changed in Settings → System.

## Stack

| Area | Tech |
|------|------|
| API | FastAPI, Python 3.12, asyncpg |
| Database | PostgreSQL 16 + pgvector (1024-dim vectors) |
| Frontend | React 18, Vite, Tailwind, shadcn/ui, Zustand, TanStack Query |
| Inference | llama.cpp (bundled) or any OpenAI-compatible endpoint |
| Embeddings | infinity-emb (bundled) with bge-m3, or any OpenAI-compatible `/embeddings` |
| Rerank | bge-reranker-v2-m3 (bundled) with flashrank CPU fallback |
| Vision | MedGemma multimodal (mmproj), pdf2image + Poppler |
| OCR fallback | pdfplumber (PDF tables), Tesseract (images) |
| Search | SearXNG meta-search (bundled) |
| Auth | argon2-cffi (password hashing), session cookies |
| Encryption | HKDF-derived per-record DEKs, AES-256-GCM column encryption |
| De-identification | Regex-based PHI redaction with configurable policy levels |

## Configuration

All configuration is via environment variables in `.env`. See `.env.example` for the full list with comments. Key vars:

| Var | Purpose | Default |
|-----|---------|---------|
| `HLH_CHAT_CTX` | Context window size (tokens); set per tier at save time | `32768` |
| `HLH_CHAT_TIMEOUT` | llama.cpp server request timeout (seconds); vision ingest can be slow | `300` |
| `HLH_CHAT_MEM` | Memory limit for chat sidecar | `6g` |
| `HLH_CHAT_NGL` | GPU layers to offload | `0` |
| `HLH_MASTER_KEY` | Encryption master key (auto-generated on first launch) | — |
| `HLH_REDACTION_POLICY` | De-id policy: `strict`, `standard`, `permissive` | `standard` |

Provider configuration (inference, embedding, reranker) is managed through the UI via Settings, not env vars. The five legacy env vars (`OPENAI_API_KEY`, `INFERENCE_URL`, `EMBEDDING_URL`, `RERANKER_URL`, `DEFAULT_MODEL`) are deprecated — the lifespan hook warns at startup if any are set.

## Security posture

homelabhealth is a single-user homelab tool for personal medical records, MIT-licensed. Not HIPAA-certified. Current defenses:

- **Container hardening:** `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, internal inference network, pinned image tags
- **Column encryption:** AES-256-GCM with HKDF-derived per-record DEKs from `HLH_MASTER_KEY`
- **De-identification:** Regex-based PHI redaction on ingest (birthdate, SSN, MRN, NPI, DEA)
- **I/O guard:** Input scanner (prompt injection, banned substrings), output scanner (PII leak, medical advice, crisis, hallucinated IDs)
- **Audit log:** Hash-chained, insert-only (via restricted Postgres role), tamper-evident
- **Safeguards:** Tiered refusal system prompt on every request, audit-logged refusals, crisis card
- **Auth:** Built-in username/password with argon2 hashing, session management

See [`SECURITY.md`](SECURITY.md), [`THREATMODEL.md`](THREATMODEL.md), [`docs/safe-harbor.md`](docs/safe-harbor.md), [`docs/breach-response.md`](docs/breach-response.md).

Last reviewed: 2026-05-28.

## License

MIT
