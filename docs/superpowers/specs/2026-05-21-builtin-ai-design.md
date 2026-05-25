# Built-in AI — Design

Spec: `docs/superpowers/specs/2026-05-21-builtin-ai-design.md`
Status: Shipped (v0.2.0–v0.4.0 era). Historical design reference.
Phase: A0
Owner: Sam

## Goal

Ship HomeLabHealth with AI that works out of the box. Operator installs the
stack, opens the setup page, picks a hardware tier, and HLH has working
chat, embedding, reranking, and (eventually) vision, STT, and OCR — without
the operator standing up llama-swap, Ollama, or anything else.

Non-goal: replace external providers. The `providers` table from phase 0
stays. Built-in AI is **one additional provider**, auto-seeded. Operators
can still wire HLH to OpenAI, Anthropic, an external llama-swap, or
anything else OpenAI-compatible.

## Why this is needed

Current state (after phase 0 — providers table, encrypted api_key column,
workspace binding):

- HLH is an HTTP client. No inference is built in.
- A self-hoster has to provision an OpenAI-compatible endpoint themselves
  before HLH does anything useful.
- “Easiest path” today is Ollama on the same box. That’s still a manual
  install, separate process, separate config, separate updates.
- Friend running HLH on her own infra will not provision an inference
  server. Either HLH ships with one or the project is dead-on-arrival
  for the actual user.

Built-in AI removes that gate.

## Scope

Six AI roles, six phases. Each phase is an independent compose profile
that can be enabled or left off. Nothing in this design forces all six
on a single host.

|Phase|Role                             |Sidecar     |Server                          |Default model                                          |
|-----|---------------------------------|------------|--------------------------------|-------------------------------------------------------|
|A1   |Chat                             |`hlh_chat`  |llama.cpp server                |Qwen2.5-3B-Instruct Q4_K_M (~2 GB)                     |
|A2   |Embed + Rerank                   |`hlh_embed` |infinity-emb                    |Harrier-OSS-0.6B Q8 (1024 dim) + Qwen3-Reranker-0.6B Q4|
|A3   |Hardware detection + setup wizard|(no sidecar)|—                               |—                                                      |
|A4   |Vision                           |`hlh_vlm`   |llama.cpp server with `--mmproj`|Qwen2.5-VL-3B Q4                                       |
|A5   |STT                              |`hlh_stt`   |whisper.cpp server              |whisper-base.en (~140 MB)                              |
|A6   |OCR (only if VLM insufficient)   |`hlh_ocr`   |Tesseract or PaddleOCR          |Tesseract 5 with eng traineddata                       |

All sidecars expose OpenAI-compatible HTTP endpoints. None of them load
their model from the image. **First-boot download** strategy: image
contains the server binary and a download script; models pull from
Hugging Face on first start, cached in a named Docker volume.

## Architecture

```
hlh_ui (browser)
    │
    ▼
hlh_api (FastAPI)  ────asyncpg────▶  hlh_db (Postgres + pgvector)
    │
    │   internal Docker network: hlh_inference
    │
    ├─▶ hlh_chat   :8001   /v1/chat/completions  /v1/models
    ├─▶ hlh_embed  :8002   /v1/embeddings  /v1/rerank  /v1/models
    ├─▶ hlh_vlm    :8003   /v1/chat/completions (multimodal)  /v1/models
    ├─▶ hlh_stt    :8004   /v1/audio/transcriptions
    └─▶ hlh_ocr    :8005   /v1/ocr  (custom shape — no OpenAI spec for OCR)

Volumes (named, persist across rebuilds):
  hlh_models_chat   → /models
  hlh_models_embed  → /models
  hlh_models_vlm    → /models
  hlh_models_stt    → /models
```

Public surface: only `hlh_ui` and `hlh_api` are exposed on the
ubuntu-homelab Tailscale IP. The five sidecars bind only to the
internal Docker network. No host port publish.

## Provider table integration

On first boot of each sidecar phase:

1. Sidecar reports ready (`/healthz` returns 200 with model loaded).
1. `hlh_api` startup script checks `providers` table for a row with
   `is_builtin=true AND role=<phase>`.
1. If absent, insert:
   
   ```sql
   INSERT INTO providers (name, role, base_url, api_key_enc, enabled, is_builtin, model)
   VALUES ('Built-in Chat', 'chat',
           'http://hlh_chat:8001/v1', NULL, true, true,
           'qwen2.5-3b-instruct-q4');
   ```
1. If `global_settings.embedding_provider_id` is NULL after A2 lands,
   bind it to the built-in embed provider automatically. Same for
   reranker, VLM, STT, OCR in their phases.

Schema additions to `providers`:

```sql
ALTER TABLE providers ADD COLUMN IF NOT EXISTS is_builtin BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE providers ADD COLUMN IF NOT EXISTS role TEXT;  -- chat, embed, rerank, vlm, stt, ocr
CREATE INDEX IF NOT EXISTS providers_builtin_role_idx ON providers (is_builtin, role) WHERE is_builtin = true;
```

Built-in providers cannot be deleted, only disabled. Frontend hides the
delete button when `is_builtin=true`.

## First-boot model download

Each sidecar image contains:

- Server binary (llama.cpp / infinity / whisper.cpp / tesseract).
- A `bootstrap.sh` entrypoint.
- `models.json` manifest: model ID, HF repo, filename, sha256, size.

`bootstrap.sh` flow:

1. Read `HLH_MODEL_ID` from env (default per role).
1. Look up entry in `models.json`.
1. If `/models/<filename>` exists and sha256 matches, skip download.
1. Otherwise, `huggingface-cli download <repo> <filename> --local-dir /models`.
1. Verify sha256. Refuse to start if mismatch.
1. Exec server binary pointing at `/models/<filename>`.

Network requirements:

- First boot needs outbound HTTPS to `huggingface.co` and the CDN.
  Document this. Operator behind a strict firewall must allow it or
  pre-populate the volume manually.
- Subsequent boots: no network required. Models cached in volume.

Failure modes:

- HF rate limit: retry with backoff (30s, 60s, 120s, give up).
- Disk full: bootstrap exits 1, logs clearly.
- sha256 mismatch: bootstrap exits 2, refuses to start. Operator must
  delete `/models/<filename>` and retry.
- HF outage: bootstrap retries on container restart loop. Health check
  reports `not_ready` until model lands.

`hlh_api` UI surface: settings page shows a “Built-in AI status” panel
with each sidecar’s state (downloading, ready, error). Progress bar
during download via `huggingface-cli`’s stderr parsed and exposed at
`/api/builtin/status`.

## Hardware tiers (phase A3)

Detection runs in `hlh_api` startup. Reads (host-mounted, read-only):

- `/proc/meminfo` → RAM
- `/proc/cpuinfo` → CPU cores
- `/sys/class/drm/card*/device/vendor` + `nvidia-smi` (if present) → GPU vendor
- `nvidia-smi --query-gpu=memory.total` → VRAM
- `df -h /` → disk free

Tiers:

|Tier     |RAM     |GPU   |VRAM    |Chat model     |Embed              |VLM             |
|---------|--------|------|--------|---------------|-------------------|----------------|
|CPU-tiny |<16 GB  |none  |—       |Qwen2.5-1.5B Q4|Harrier-OSS-0.6B Q8|none            |
|CPU-small|16-32 GB|none  |—       |Qwen2.5-3B Q4  |Harrier-OSS-0.6B Q8|none            |
|GPU-entry|any     |NVIDIA|4-8 GB  |Qwen2.5-3B Q4  |Harrier 0.6B FP16  |Qwen2.5-VL-3B Q4|
|GPU-mid  |any     |NVIDIA|12-16 GB|Qwen2.5-7B Q4  |Harrier 0.6B FP16  |Qwen2.5-VL-7B Q4|
|GPU-high |any     |NVIDIA|24 GB+  |Qwen2.5-14B Q4 |Harrier 0.6B FP16  |Qwen2.5-VL-7B Q4|

Manual override always available. Operator picks tier in setup page,
sees the model list, can substitute any HF GGUF before downloading.

## Compose profiles

Single `docker-compose.yml` with profiles:

```yaml
services:
  hlh_api:
    # always on
  hlh_ui:
    # always on
  hlh_db:
    # always on

  hlh_chat:
    profiles: ["builtin-chat", "builtin-all"]
    image: hlh/chat:cpu     # or hlh/chat:cuda, hlh/chat:rocm
    environment:
      HLH_MODEL_ID: ${HLH_CHAT_MODEL:-qwen2.5-3b-instruct-q4}
    volumes:
      - hlh_models_chat:/models
    networks: [hlh_inference]

  hlh_embed:
    profiles: ["builtin-rag", "builtin-all"]
    image: hlh/embed:cpu
    # ...

  hlh_vlm:
    profiles: ["builtin-vlm", "builtin-all"]
    # ...

  hlh_stt:
    profiles: ["builtin-stt", "builtin-all"]
    # ...

  hlh_ocr:
    profiles: ["builtin-ocr", "builtin-all"]
    # ...

networks:
  hlh_default:
    # api ↔ ui ↔ db
  hlh_inference:
    internal: true   # no egress
    # api ↔ inference sidecars
```

Operator activates with `COMPOSE_PROFILES=builtin-rag,builtin-chat`
in `.env`, or via the setup page which writes that env var and
reloads the stack.

Image tag axis: each `hlh/<role>` image is built three times — `cpu`,
`cuda`, `rocm`. Setup wizard picks based on detected GPU. CPU is the
default when detection fails.

## Image build strategy

Per-role multi-stage Dockerfile. Final image is small (binary +
bootstrap script + manifest, no model weights):

|Image           |Base                                                   |Approx size|
|----------------|-------------------------------------------------------|-----------|
|`hlh/chat:cpu`  |`debian:12-slim` + llama.cpp CPU build                 |~150 MB    |
|`hlh/chat:cuda` |`nvidia/cuda:12.6-runtime-ubuntu24.04` + llama.cpp CUDA|~2 GB      |
|`hlh/embed:cpu` |`python:3.12-slim` + infinity-emb                      |~800 MB    |
|`hlh/embed:cuda`|`nvidia/cuda:12.6-runtime-ubuntu24.04` + infinity-emb  |~3 GB      |
|`hlh/vlm:cpu`   |same as chat                                           |~150 MB    |
|`hlh/stt:cpu`   |`debian:12-slim` + whisper.cpp                         |~100 MB    |
|`hlh/ocr:cpu`   |`debian:12-slim` + tesseract                           |~200 MB    |

Total CPU profile: ~1.2 GB of images. Models add another ~3-5 GB on
disk in named volumes.

CI builds images on tag push to Gitea. Pushed to a public registry
(GHCR mirror if going public, or just `git.indifferentketchup.com`).

## Setup wizard (phase A3)

Single-page flow at `/setup` in `hlh_ui`. Triggered when
`global_settings.setup_complete = false`. Steps:

1. **Welcome.** Plain explanation: “HLH can run AI locally on this
   machine or talk to an external provider. Which would you like?”
1. **Hardware scan.** Backend reports detected tier. Shows: CPU model,
   RAM, GPU (if any), VRAM, disk free.
1. **Tier selection.** Recommended tier pre-selected. Operator can
   override. Shows estimated download size and disk usage.
1. **Profile activation.** Operator picks which roles to enable
   (chat, RAG, vision, STT, OCR). Backend writes `.env` with
   `COMPOSE_PROFILES` and reloads.
1. **Download progress.** Live status of model downloads.
1. **Smoke test.** Backend sends a test prompt to each enabled role,
   reports pass/fail.
1. **Done.** Sets `setup_complete = true`. User dropped into the app.

External provider path: skip steps 2-6. Show provider creation form
(name, base_url, api_key, role). Same flow as today’s settings UI.

## Configuration via env

`.env` additions (with sensible defaults so opt-in is one variable):

```
# Enable built-in AI roles
COMPOSE_PROFILES=                          # empty = external only
HLH_BUILTIN_TIER=cpu-small                 # see tier table
HLH_CHAT_MODEL=qwen2.5-3b-instruct-q4
HLH_EMBED_MODEL=harrier-oss-0.6b-q8
HLH_RERANK_MODEL=qwen3-reranker-0.6b-q4
HLH_VLM_MODEL=qwen2.5-vl-3b-q4
HLH_STT_MODEL=whisper-base.en
HLH_HF_MIRROR=                             # optional HF mirror URL
```

Env vars are advisory — the setup wizard writes them, and they can be
edited by hand. `hlh_api` reads them on startup and reconciles
`providers` table with what’s actually loaded.

## Status surface

Two new endpoints in `hlh_api`:

```
GET /api/builtin/status
  → [
      {"role": "chat",  "container": "hlh_chat",  "state": "ready",
       "model": "qwen2.5-3b-instruct-q4", "model_path": "/models/...",
       "vram_used_mb": null, "tokens_per_sec": 28.4},
      {"role": "embed", "container": "hlh_embed", "state": "downloading",
       "progress_pct": 47.2, "eta_sec": 84},
      {"role": "vlm",   "container": "hlh_vlm",   "state": "disabled"}
    ]

POST /api/builtin/restart/:role
  → triggers `docker compose restart hlh_<role>`. Wizard uses this.
```

State enum: `disabled | downloading | starting | ready | error`.

Frontend polls every 2s on the setup page, every 30s on the settings
page.

## Security implications

The security plan (`docs/security/SECURITY_PLAN.md`) lists “phase
S2 — Docker hardening” as `hlh_db on internal-only network`. Built-in
AI inherits the same posture:

- `hlh_inference` network has `internal: true`. No egress, no host
  port publish. Sidecars can be reached only by `hlh_api`.
- First-boot model download is the **only** outbound. Implemented in
  `bootstrap.sh` which has access to a separate `hlh_download_net`
  during download, dropped from network after model lands. Operator
  can pre-populate the volume to skip this entirely.
- Each sidecar runs as non-root (UID 1000 in image).
- `read_only: true` filesystem with `tmpfs` for `/tmp`.
- `cap_drop: [ALL]`. No `cap_add` needed; servers don’t need caps.
- `security_opt: [no-new-privileges:true]`.
- Resource limits: `mem_limit` per tier, prevents OOM-killing the
  whole stack.

PHI flow into sidecars:

- Chat: prompt may include record text. Stays on internal network.
- Embed: document chunks include record text. Stays on internal
  network.
- Rerank: same as embed.
- VLM: image bytes (may be photographed records). Stays internal.
- STT: audio (may be dictated PHI). Stays internal.
- OCR: image bytes. Stays internal.

No sidecar logs prompts or audio by default. Sidecar containers run
with `--log-disable` (llama.cpp) or equivalent. Configurable via env
for debugging.

## Failure scenarios

|Scenario                                  |Behavior                                                                                         |
|------------------------------------------|-------------------------------------------------------------------------------------------------|
|HF unreachable on first boot              |Sidecar restart-loops, status reports `error`, wizard surfaces it, suggests pre-populating volume|
|Disk fills during download                |Bootstrap exits 1 with clear message, sidecar restart-loops, wizard offers cleanup               |
|sha256 mismatch                           |Bootstrap exits 2, refuses to start                                                              |
|Model load OOM                            |Sidecar process dies, wizard suggests lower tier                                                 |
|Sidecar crashes mid-request               |`hlh_api` catches connection error, returns 503 with retry-after                                 |
|Operator deletes the built-in provider row|Row insert is idempotent on next `hlh_api` restart                                               |
|Operator picks wrong tier                 |Setup wizard reachable from settings, can re-run anytime                                         |

## Open questions (resolve before A1 starts)

1. **Model licensing.** Qwen2.5 is Apache-2.0 for ≤14B, custom license
   for ≥30B. Harrier-OSS is Apache-2.0. Whisper is MIT. VLM check
   pending. Compile license matrix and document per model in
   `docs/models.md`. Refuse to bundle any model whose license forbids
   redistribution via download script.
1. **CUDA vs ROCm image matrix.** Build both, or only CUDA + CPU?
   Decision deferred to A1. CPU + CUDA covers ~95% of operators.
   ROCm adds maintenance cost.
1. **Update flow.** When a new HLH version ships a better default
   model, what happens to the old one? Proposal: leave old model on
   disk, switch pointer. Operator can manually clean up old GGUFs.
1. **Disk usage caps.** Should HLH refuse to download a model that
   would leave less than N GB free? Default suggestion: refuse if
   <5 GB would remain post-download.
1. **Backup story for models.** Are model files in backrest? They
   shouldn’t be — they’re 2-15 GB each and reproducible from HF.
   Exclude `hlh_models_*` volumes from backrest by default.

## Out of scope for v1

- llama-swap front-end. Operators who want multi-model swap can layer
  it themselves.
- Fine-tuning UI.
- LoRA hot-swap.
- Multi-host inference (one HLH talking to another HLH’s sidecars).
- BYOM (bring your own model) file upload. v1 = HF only.
- Model library browser like LM Studio. Defer to A7 if ever.

## Implementation order

A1 → A2 → A3 → A4 → A5 → A6.

A3 (hardware detection) intentionally lands after A1 and A2 so that
A1/A2 can be tested manually via env vars before the wizard exists.
Wizard becomes the polish layer on top of working sidecars.

Each phase = its own spec + plan in `docs/superpowers/specs/`,
matching B.1/B.2/B.3 shape elsewhere in the repo.

## Cross-references

- Security plan: `docs/security/SECURITY_PLAN.md`. S2 (Docker
  hardening) applies to all sidecars. S5 (de-id pipeline) only
  needed if any sidecar ever talks out — current design keeps them
  internal.
- Existing crypto module from commit `8ec7dd7`. Not used here (no
  api_key needed for built-in providers) but the encryption-at-rest
  posture still applies to record data the sidecars touch.
- Embedding dim hard-locked at 1024 (schema constraint). A2’s default
  embed model must produce 1024-dim vectors. Harrier-OSS-0.6B does.

## Definition of done (per phase)

Each phase ships when:

1. Sidecar image builds in CI for at least `cpu` and `cuda` variants.
1. First-boot download works against HF.
1. Auto-seed of `providers` row works on fresh DB.
1. Smoke test passes (round-trip request through `hlh_api` to sidecar).
1. Setup page status panel shows correct state.
1. Docs updated: `docs/builtin-ai.md`, `docs/models.md`, README
   “Quick start” section.
1. Tagged release (`v0.1.0-A1`, `v0.1.0-A2`, etc.).
