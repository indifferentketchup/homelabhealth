# HLH Built-in AI — Roadmap & Design

Canonical spec for HLH’s bundled inference stack. Supersedes
`hlh_phase1_design.md` and `2026-05-21-builtin-ai-design.md`. Those two
files are deleted on the same commit that lands this one.

Owner: Sam
Status: Phase 0 merged on `main`. Phase 1 on branch
`feat/phase-1-chat-sidecar` (7 commits, 393 assertions passing,
unmerged at time of writing).

-----

## Goal

Ship HomeLabHealth with AI that works out of the box. Operator runs
`docker compose up`, opens the setup page, picks a hardware tier, and
HLH has working chat, embedding, reranking, and (eventually) vision,
STT, and OCR — without standing up llama-swap, Ollama, or anything
else.

**Non-goal:** replace external providers. The `providers` table from
phase 0 stays. Built-in AI is **one additional provider**, auto-seeded
by tier. Operators can still wire HLH to OpenAI, Anthropic, an
external llama-swap, or anything else OpenAI-compatible — that path is
the “external” tier.

-----

## Phase map

|Phase|Role                                            |Status                        |Branch / commit                        |Sidecar                                |
|-----|------------------------------------------------|------------------------------|---------------------------------------|---------------------------------------|
|0    |Hardware detect + tier picker + system_profile  |**Merged on main** (`d173e1f`)|—                                      |(none)                                 |
|1    |Chat                                            |**Built, unmerged**           |`feat/phase-1-chat-sidecar` (7 commits)|`hlh_chat`                             |
|1.5  |Hardening + pinning                             |Planned                       |TBD                                    |(modifies Phase 1 sidecar)             |
|2    |Embed + Rerank                                  |Planned                       |TBD                                    |`hlh_embed`, `hlh_rerank`              |
|3    |Vision (VLM) + MedSigLIP                        |Planned                       |TBD                                    |`hlh_vlm`                              |
|4    |STT (whisper.cpp)                               |Planned                       |TBD                                    |`hlh_stt`                              |
|5    |OCR (only if VLM in Phase 3 proves insufficient)|Conditional                   |TBD                                    |`hlh_ocr`                              |
|6    |Apple MLX backend variant                       |Deferred                      |TBD                                    |(architecture variant, not new sidecar)|

Each phase = one branch, one merge, one tag (`v0.1.0-phase-1`,
`v0.1.0-phase-2`, …). Phases are independently shippable. The setup
wizard from Phase 0 surfaces whichever roles are currently profiled in
`docker-compose.yml`.

-----

## Architecture (final shape, all phases)

```
hlh_ui (browser, Tailscale-exposed via :9402)
    │
    ▼
hlh_api (FastAPI, Tailscale-exposed via :9400)
    │   asyncpg ─▶ hlh_db (Postgres 16 + pgvector, internal only)
    │
    │   internal Docker network: hlh_inference  ← Phase 1.5 lands this
    │
    ├─▶ hlh_chat   :9610  /v1/chat/completions  /v1/models    (Phase 1)
    ├─▶ hlh_embed  :9620  /v1/embeddings        /v1/models    (Phase 2)
    ├─▶ hlh_rerank :9621  /v1/rerank            /v1/models    (Phase 2)
    ├─▶ hlh_vlm    :9630  /v1/chat/completions (multimodal)   (Phase 3)
    ├─▶ hlh_stt    :9640  /v1/audio/transcriptions            (Phase 4)
    └─▶ hlh_ocr    :9650  /v1/ocr (custom — no OpenAI shape)  (Phase 5)

Shared named volume: hlh_models (rw on hlh_api, ro on every sidecar)
  Layout: /models/<role>/<tier>/<filename>
```

Public surface: only `hlh_ui` and `hlh_api` bind on the Tailscale IP
`100.114.205.53`. Every sidecar is internal-network-only and is
reachable solely by `hlh_api`.

**Architecture choice (locked):** centralized download path. `hlh_api`
runs the puller (`services/model_puller.py`); each sidecar mounts
`/models:ro` and serves whatever’s there. This is a deliberate
divergence from the older spec’s per-sidecar `bootstrap.sh` pattern.
Reasons:

- One pull queue, one progress surface, one license-acceptance UX.
- Sidecars are stock upstream images (`ghcr.io/ggml-org/llama.cpp:server`,
  etc.) — no custom Dockerfile per role to maintain.
- License gating happens in the wizard before a download starts, not
  as a 401 inside a restart-looping container.
- Re-pulling a model for a different tier doesn’t require rebuilding
  an image.

-----

## Tier model defaults (locked, Phase 1 chat; Phase 2+ TBD)

|Tier       |Chat (P1)                               |Embed (P2)                    |Rerank (P2)           |VLM (P3)        |
|-----------|----------------------------------------|------------------------------|----------------------|----------------|
|`cpu-min`  |Qwen3 1.7B Q8_0 (~1.75 GB)¹             |Harrier-OSS-0.6B Q8 (1024-dim)|Qwen3-Reranker-0.6B Q4|(none)          |
|`cpu-std`  |MedGemma 4B Q4_K_M (~2.8 GB)²           |Harrier-OSS-0.6B Q8           |Qwen3-Reranker-0.6B Q4|(none)          |
|`gpu-8gb`  |MedGemma 4B Q8_0 (~4.5 GB)²             |Harrier 0.6B FP16             |Qwen3-Reranker-0.6B Q8|Qwen2.5-VL-3B Q4|
|`gpu-16gb` |MedGemma 27B Text Q4_K_M (~16 GB)²      |Harrier 0.6B FP16             |Qwen3-Reranker-0.6B Q8|Qwen2.5-VL-3B Q4|
|`gpu-24gb+`|MedGemma 27B Multimodal Q4_K_M (~18 GB)²|Harrier 0.6B FP16             |Qwen3-Reranker-0.6B Q8|Qwen2.5-VL-7B Q4|
|`apple-mlx`|MedGemma 4B MLX (deferred Phase 6)      |TBD                           |TBD                   |TBD             |
|`external` |— (operator brings own)                 |—                             |—                     |—               |

¹ Q8_0 shipped instead of design’s Q4_K_M because the official
`Qwen/Qwen3-1.7B-GGUF` repo only ships Q8_0. Still under the cpu-min
2 GB RAM ceiling. Documented in `feat/phase-1-chat-sidecar` E2E commit.

² MedGemma filenames in `MODEL_REGISTRY` are unverified placeholders
as of Phase 1 ship. They may 404 against current HF artifacts.
Operator hits a clear “License acceptance required” or “404 not found”
error with retry instructions. **Phase 1.5 pins these explicitly.**

**Embedding dim hard-locked at 1024** (schema constraint). Any Phase 2
embed model must produce 1024-dim vectors. Harrier-OSS-0.6B does.

**MedGemma is gated on HuggingFace.** Operator needs `HF_TOKEN` set
AND must accept the Gemma License at the relevant HF page before
download. The model puller’s error handling surfaces this explicitly
on 401.

-----

## Phase 0 — Hardware detect + tier picker (merged)

Shipped on `main` at `d173e1f`. Not re-documented here. Surfaces:

- `system_profile` table with `tier`, `setup_complete`, detection JSON.
- `GET /api/sysinfo` — read-only host introspection (CPU/RAM/GPU/disk).
- `PUT /api/system/profile` — operator confirms tier; sets
  `setup_complete=true`.
- Setup gate on the frontend: if `setup_complete=false`, every route
  redirects to `/settings?tab=system`.
- `SystemTab.jsx` renders tier cards with Phase 1 model labels.

Phase 1+ hooks into this. The puller, the bundled-provider seed, and
every future sidecar all key off `system_profile.tier`.

-----

## Phase 1 — Chat sidecar (built, unmerged)

Branch `feat/phase-1-chat-sidecar`. 7 commits. 393 assertions passing
across 13 verify scripts (including a 12-step E2E that resets the DB,
runs the tier wizard, pulls Qwen3 1.7B from HF, starts the chat
container, and round-trips an SSE chat through it).

### Schema

```sql
CREATE TABLE bundled_models (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  role            TEXT CHECK (role IN ('chat','embed','rerank','vision','medsiglip','stt','ocr')),
  tier            TEXT NOT NULL,
  model_id        TEXT NOT NULL,
  quant           TEXT,
  repo            TEXT NOT NULL,
  filename        TEXT NOT NULL,
  expected_bytes  BIGINT,
  sha256          TEXT,
  license         TEXT,
  license_url     TEXT,
  status          TEXT CHECK (status IN ('pending','pulling','ready','failed','skipped')) DEFAULT 'pending',
  pulled_bytes    BIGINT NOT NULL DEFAULT 0,
  error_message   TEXT,
  pull_started_at  TIMESTAMPTZ,
  pull_finished_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (role, tier, model_id, quant)
);
```

### Backend

- `services/model_puller.py` — `MODEL_REGISTRY` dict keyed
  `(role, tier) -> ModelSpec | None`. Streaming HTTP pull via httpx
  (not huggingface-hub). `<file>.partial` → fsync → rename pattern.
  Module-level `asyncio.Lock` enforces one-pull-at-a-time globally.
  Per-id cancel events checked at 5 MB chunk boundaries. sha256
  verified post-rename when the spec sets one (today none do — Phase 1.5).
  Gated-repo 401 → status=`failed` + license-acceptance message
  pointing at `license_url`.
- `services/bundled_providers.py` —
  `ensure_bundled_chat_provider(conn)`. Idempotent upsert by
  `name='bundled-chat'`, `base_url='http://hlh_chat:9610'`,
  `api_key=NULL`, `enabled=true`. No-op when `setup_complete=false`
  or `tier='external'`. ON CONFLICT preserves any operator-set
  `api_key`.
- `routers/models.py` — 5 admin-only endpoints:
  - `GET /api/models`
  - `GET /api/models/{id}`
  - `POST /api/models/{id}/pull` (202, background task)
  - `POST /api/models/pull-for-tier` (202, body `{tier}`)
  - `POST /api/models/{id}/cancel` (200)
- Lifespan ordering in `main.py`:
  
  ```
  1. init_pool()
  2. apply_schema()
  3. seed_default_assets()
  4. _warn_deprecated_env_vars()
  5. model_puller.seed_registry()         # Phase 1
  6. ensure_bundled_chat_provider()       # Phase 1, conditional
  ```
- `PUT /api/system/profile` calls `ensure_bundled_chat_provider()` in
  the same conn after setting `setup_complete=true`, so the provider
  row appears the moment the operator confirms a tier.

### Docker

- New named volume `hlh_models` (materializes as
  `homelabhealth_hlh_models` per the existing project prefix).
- `hlh_api` mounts `hlh_models:/models:rw` (puller writes here).
- New service `hlh_chat`:
  - Image: `ghcr.io/ggml-org/llama.cpp:server` (unpinned — Phase 1.5).
  - Mounts `hlh_models:/models:ro`.
  - Env: `HLH_CHAT_MODEL_PATH`, `HLH_CHAT_PORT=9610`,
    `HLH_CHAT_NGL=0` (CPU default).
  - Command: `--model $PATH --host 0.0.0.0 --port $PORT --n-gpu-layers $NGL --jinja`.
  - Healthcheck: `curl -fsS http://localhost:9610/v1/models`.
  - Compose profile: `chat` (default-on; operator opts out with
    `COMPOSE_PROFILES=` or `external-only`).
  - No host port publish.
  - `depends_on: hlh_api` (chat restart-loops until the puller lands a
    model file in `/models/chat/<tier>/`).

### Frontend

- `api/models.js` — 5 wrappers matching the router.
- `SystemTab.jsx`:
  - Tier labels updated to MedGemma names per the table above.
  - `ModelsPanel` sub-component below the tier picker. Polls
    `GET /api/models` every 2s while any row is `pulling`; idle
    otherwise. Filters to the currently selected tier. Columns: Role,
    Model, Status, Progress, License, Action. License-acceptance
    errors rendered inline with a “Visit and accept here” link.
  - External tier hidden behind `<details>` collapsed-by-default.
    Summary: “Advanced: bring your own inference.”

### Known gaps (deferred to Phase 1.5)

1. `hlh_chat` is on `hlh_default` (the shared network), not an
   internal-only `hlh_inference` net.
1. No container hardening: no `read_only`, no `tmpfs`, no
   `cap_drop:[ALL]`, no `no-new-privileges`, no `mem_limit`, no
   non-root user.
1. `ghcr.io/ggml-org/llama.cpp:server` tag is unpinned.
1. No `sha256` in `MODEL_REGISTRY` entries.
1. No disk pre-flight check before kicking off a multi-GB pull.
1. MedGemma `filename` fields in `MODEL_REGISTRY` are placeholders
   from the design doc, not confirmed against current HF artifacts.
1. No protection against `DELETE /api/providers/<bundled-chat-id>`.
   Re-runs of `ensure_bundled_chat_provider` on lifespan recreate the
   row, but a delete mid-session leaves a window where bound
   workspaces fail.
1. No `/api/builtin/status` aggregate endpoint. Today’s UI polls
   `GET /api/models`, which covers download/ready state but not
   container health. Sufficient for Phase 1.

-----

## Phase 1.5 — Hardening + pinning

Branch from `main` *after* Phase 1 merges. Scope:

### Docker hardening

- New network `hlh_inference` with `internal: true`. `hlh_api` joins
  both `hlh_default` and `hlh_inference`. `hlh_chat` moves off
  `hlh_default` and onto `hlh_inference` only.
- `hlh_chat` service additions:
  - `user: "1000:1000"`
  - `read_only: true`
  - `tmpfs: [/tmp]`
  - `cap_drop: [ALL]`
  - `security_opt: [no-new-privileges:true]`
  - `mem_limit` per tier (cpu-min: 3g, cpu-std: 5g, gpu-8gb: 8g,
    gpu-16gb: 18g, gpu-24gb+: 22g). Read from env, defaulted from
    `system_profile.tier`.
- Pin `ghcr.io/ggml-org/llama.cpp:server-<digest>` to a specific
  build. Document the upgrade procedure.

### MODEL_REGISTRY pinning

For every chat tier shipped in Phase 1:

- Confirm the `filename` resolves against the current HF artifact.
- Pin a `revision` (HF commit hash).
- Compute and pin `sha256` after a clean pull.
- Verify `expected_bytes` matches reality.

### Puller hardening

- Disk pre-flight: refuse pull if free space minus
  `expected_bytes` would leave < 5 GB. Status=`failed`,
  error_message=“insufficient disk”.
- sha256 mismatch already handled in code; now actually exercised
  because pinning lands here.
- Drop `huggingface-hub>=0.24.0` from `requirements.txt` if still
  unused (puller uses httpx directly).

### Provider delete guard

- Add `is_bundled` boolean column to `providers` (additive ALTER,
  default false). `ensure_bundled_*` sets it true on insert.
- `DELETE /api/providers/{id}` returns 409 when `is_bundled=true`
  with body `{"error": "bundled provider cannot be deleted, only disabled"}`.
- Frontend hides the delete button (or disables with tooltip “Bundled
  provider — disable instead of deleting”) for `is_bundled` rows.

### Acceptance

- All Phase 1 verify scripts still pass (393 assertions).
- New `verify_phase_1_5_hardening.sh`:
  - `docker inspect hlh_chat` shows `ReadonlyRootfs: true`,
    `CapDrop: [ALL]`, `SecurityOpt` contains `no-new-privileges`.
  - `docker network inspect hlh_inference` shows `Internal: true`.
  - `docker port hlh_chat` returns empty.
  - `curl -X DELETE /api/providers/<bundled-id>` returns 409.
  - Manual sha256 corrupt-and-restart test: flip a byte in the
    cached gguf, restart pull → status=`failed`,
    error_message contains `sha256 mismatch`.
  - Disk pre-flight: synthetic test pinning expected_bytes >
    available space → status=`failed`, error_message contains
    `insufficient disk`.

-----

## Phase 2 — Embed + Rerank

Two sidecars, separate compose profiles (`embed`, `rerank`). Both
ride the same shared `hlh_models` volume and the same puller. Both
on `hlh_inference` from the start (Phase 1.5 lands the network).

### Sidecars

|Service     |Image                                     |Port|Endpoint                      |
|------------|------------------------------------------|----|------------------------------|
|`hlh_embed` |`michaelf34/infinity:latest` (pin at impl)|9620|`/v1/embeddings`, `/v1/models`|
|`hlh_rerank`|`michaelf34/infinity:latest` (pin at impl)|9621|`/v1/rerank`, `/v1/models`    |

`infinity-emb` handles both roles; running two instances (one per
role) keeps memory predictable and lets tier scaling differ.

### Backend additions

- `MODEL_REGISTRY` rows for `embed` and `rerank` per tier (replacing
  the Phase 1 `None` placeholders).
- `ensure_bundled_embed_provider()` and
  `ensure_bundled_rerank_provider()` in
  `services/bundled_providers.py`. Same idempotent-upsert shape as
  Phase 1’s chat.
- Auto-bind on first ready: if `global_settings.embedding_provider_id`
  is NULL when embed sidecar reports ready, set it to the bundled
  embed provider. Same for reranker.

### Constraint

Embedding dim **must** be 1024 (schema constraint, pgvector HNSW dim
limit is 2000 but our column is fixed at 1024 to match Harrier-OSS).
Any model swap in this phase or later requires a migration plan
first. Document this in the manifest comment.

### Acceptance

- Bundled embed provider auto-seeds on tier confirm (same path as
  chat).
- `POST /v1/embeddings` through `hlh_embed` returns 1024-dim vectors.
- `POST /v1/rerank` through `hlh_rerank` returns scored results.
- RAG pipeline indexes a synthetic document end-to-end through the
  bundled embed+rerank pair (existing RAG tests, repointed).
- `verify_phase_2_e2e.py`: tier → pull → index → retrieve → rerank.

-----

## Phase 3 — Vision (VLM) + MedSigLIP

VLM sidecar `hlh_vlm` running llama.cpp server with `--mmproj`.
MedSigLIP is a separate model for medical-image embedding, kept on
the same VLM container or a fourth sidecar depending on inference
cost (decide at impl).

### MTP/mmproj gotcha (locked)

Per project_context: **MTP variants + mmproj cause fatal n_embd
mismatch** in llama.cpp. VLM model configs must NOT include
`--mmproj` with an MTP variant. Only ship VLMs whose base model has
no MTP equivalent in `MODEL_REGISTRY`.

### Vision flow

- Frontend image upload → record attachment.
- “Extract from image” action on a record → backend POSTs to
  `hlh_vlm` `/v1/chat/completions` with image bytes + prompt.
- Streaming reply rendered in chat.

### MedSigLIP

License is HAI-DEF terms — review at impl. If the license forbids
redistribution via download script, bundle the embed code and surface
a manual-download flow instead of an auto-pull.

### Acceptance

- VLM round-trip: upload an image, ask “what’s in this,” get a
  reply.
- MedSigLIP embed of a medical image landing in pgvector
  successfully retrievable.

-----

## Phase 4 — STT (whisper.cpp)

Sidecar `hlh_stt`. whisper.cpp server. Default model: tier-keyed
(`whisper-tiny.en` for cpu-min through `whisper-large-v3-turbo` for
gpu-24gb+).

### Backend additions

- New `POST /api/transcribe` endpoint. Proxies to
  `hlh_stt:9640/v1/audio/transcriptions`. Returns transcript +
  per-segment timestamps.
- **STT is NOT a `providers` row.** Single internal endpoint, not
  user-configurable per workspace. Operator gets one bundled STT or
  nothing.

### Frontend additions

- Mic button on chat input. Web Audio API records, POSTs to
  `/api/transcribe`, inserts result at cursor.
- Mic button on record-notes editor (same flow).
- Recording UI: waveform, timer, stop/cancel.

### Acceptance

- Click mic, speak 5 sec, see transcript appear in the chat input
  within 2 sec of stopping (on cpu-std tier).
- Offline after first pull.

-----

## Phase 5 — OCR (conditional)

Only if Phase 3 VLM proves insufficient on real medical documents.
Eval: 5+ representative photographed records, judged for readability
on the VLM extract path. If VLM handles them well enough, skip
Phase 5 entirely.

If needed: Tesseract 5 or PaddleOCR. Custom HTTP shape (no OpenAI
spec for OCR). New `POST /api/ocr` endpoint. New
“Extract text from image” action on record uploads, parallel to the
VLM action.

-----

## Phase 6 — Apple MLX backend variant

Deferred. Detection in Phase 0 already flags `apple-mlx`; the tier
falls back to `cpu-std` at runtime on darwin/arm64 until this lands.

When prioritized: swap the llama.cpp sidecar for an MLX-backed
server on macOS hosts. Architecture split adds a `:mlx` image tag
axis alongside the future `:cuda` / `:rocm` variants.

-----

## Image build strategy (forward plan)

Phase 1 ships using upstream images directly
(`ghcr.io/ggml-org/llama.cpp:server`,
`michaelf34/infinity:latest`). No custom Dockerfiles, no per-role
build pipeline.

If/when CUDA or ROCm variants become necessary (likely Phase 3 for
VLM throughput), the matrix becomes:

|Image                                            |Pin   |Notes                             |
|-------------------------------------------------|------|----------------------------------|
|`ghcr.io/ggml-org/llama.cpp:server-<digest>`     |CPU   |Phases 1, 3                       |
|`ghcr.io/ggml-org/llama.cpp:server-cuda-<digest>`|NVIDIA|Phases 1, 3 (when GPU tier active)|
|`michaelf34/infinity:<tag>`                      |CPU   |Phase 2                           |
|`michaelf34/infinity:<tag>-cuda`                 |NVIDIA|Phase 2 (when GPU tier active)    |
|`ghcr.io/ggerganov/whisper.cpp:server-<digest>`  |CPU   |Phase 4                           |

Tier detection from Phase 0 picks the image tag. CPU is fallback when
detection fails or operator overrides.

**ROCm support is deferred indefinitely.** CPU + CUDA covers ~95% of
operators. ROCm adds maintenance cost without a clear user.

-----

## License matrix

|Component                            |License                    |Operator action                          |
|-------------------------------------|---------------------------|-----------------------------------------|
|Qwen3 1.7B (chat, cpu-min)           |Apache-2.0                 |None                                     |
|MedGemma 4B / 27B (chat, cpu-std+)   |Gemma License              |Set `HF_TOKEN`, accept at HF page        |
|Harrier-OSS-0.6B (embed, Phase 2)    |Apache-2.0                 |None                                     |
|Qwen3-Reranker-0.6B (rerank, Phase 2)|Apache-2.0                 |None                                     |
|Qwen2.5-VL (vision, Phase 3)         |Apache-2.0 (verify at impl)|None                                     |
|MedSigLIP (Phase 3)                  |HAI-DEF terms              |Review at impl; may forbid redistribution|
|Whisper (STT, Phase 4)               |MIT                        |None                                     |
|Tesseract (OCR, Phase 5)             |Apache-2.0                 |None                                     |
|PaddleOCR (OCR alt, Phase 5)         |Apache-2.0                 |None                                     |

Setup wizard surfaces license + required action for the
currently-selected tier’s models *before* the pull triggers. Pull
button disabled until license accepted (where applicable).

-----

## Security posture (cross-phase)

Lands incrementally — most of this is Phase 1.5 for chat, mirrored
for each subsequent sidecar at its phase.

- `hlh_inference` network: `internal: true`. No egress, no host port
  publish. Only `hlh_api` reaches sidecars.
- First-boot model download is the **only** outbound. Done by
  `hlh_api` (which is on `hlh_default` and can egress), not by
  sidecars (which can’t).
- Each sidecar: non-root (UID 1000), `read_only: true`,
  `tmpfs: [/tmp]`, `cap_drop: [ALL]`,
  `security_opt: [no-new-privileges:true]`, `mem_limit` per tier.
- sha256 verification on every pull. Bundled provider rows protected
  by `is_bundled` delete guard.
- No sidecar logs prompts, audio, or image bytes by default.
  llama.cpp servers run with `--log-disable` (or equivalent per
  sidecar). Debug logging gated behind an env var.
- PHI flow: every byte that enters a sidecar (prompt text, document
  chunks, image bytes, audio) stays on `hlh_inference`. The
  internal-only network is the trust boundary; no app-layer auth
  between `hlh_api` and sidecars.

-----

## Failure scenarios

|Scenario                              |Behavior                                                                                        |
|--------------------------------------|------------------------------------------------------------------------------------------------|
|HF unreachable on first pull          |Puller retries with backoff, status=`failed`, wizard surfaces it, suggests pre-populating volume|
|Disk fills mid-pull                   |Puller exits with `insufficient disk`, status=`failed`, wizard offers cleanup                   |
|sha256 mismatch                       |Puller deletes file, status=`failed`, error_message names mismatch                              |
|Model load OOM in sidecar             |Sidecar restart-loops, healthcheck never green, wizard suggests lower tier                      |
|Sidecar crashes mid-request           |`hlh_api` catches connection error, returns 503 to UI                                           |
|Operator deletes bundled provider     |Phase 1.5 guard blocks with 409. Pre-1.5: lifespan recreates row on next restart                |
|Operator picks wrong tier             |`/settings?tab=system` always reachable; tier change re-runs puller                             |
|Gated repo (MedGemma) without HF_TOKEN|Puller surfaces 401 with license_url + retry instructions                                       |

-----

## Configuration surface

`.env` variables introduced by built-in AI (defaults are sane; opt-in
to a phase is one variable):

```
# Phase 0 (tier picker) — automatic on first boot, written by wizard.
# system_profile.tier holds the source of truth.

# Phase 1 (chat sidecar)
COMPOSE_PROFILES=chat                            # add embed,rerank,vlm,stt,ocr as phases land
HLH_CHAT_MODEL_PATH=/models/chat/cpu-min/...     # written by wizard from MODEL_REGISTRY
HLH_CHAT_PORT=9610
HLH_CHAT_NGL=0                                   # n-gpu-layers; bumped when tier is GPU
HF_TOKEN=                                        # required for gated repos (MedGemma)

# Phase 1.5
HLH_CHAT_MEM_LIMIT=3g                            # bumped per tier

# Phase 2 (embed + rerank)
HLH_EMBED_MODEL_PATH=/models/embed/<tier>/...
HLH_EMBED_PORT=9620
HLH_RERANK_MODEL_PATH=/models/rerank/<tier>/...
HLH_RERANK_PORT=9621

# Phase 3+ added at their respective phases.
HLH_HF_MIRROR=                                   # optional HF mirror URL, all phases
```

Env vars are advisory — the setup wizard writes them, and they can be
edited by hand. `hlh_api` reconciles `providers` table with what’s
actually loaded.

-----

## Definition of done (per phase)

A phase ships when:

1. Sidecar(s) run from a pinned upstream image (Phase 1 ships
   unpinned, Phase 1.5 fixes this; every subsequent phase ships
   pinned from day one).
1. First-boot pull works against HF (license-gated paths surface
   the right error).
1. `MODEL_REGISTRY` covers every tier that’s not deferred.
1. Auto-seed of the bundled provider row works on a fresh DB.
1. E2E smoke test passes (round-trip through `hlh_api` to sidecar).
1. Setup tab shows correct state during pull and after.
1. Hardening posture matches Phase 1.5 baseline (internal network,
   read_only, cap_drop, sha256, disk pre-flight).
1. Docs updated in `docs/builtin-ai/` (this directory).
1. Tagged release (`v0.1.0-phase-N`).

-----

## Out of scope for v1 (all phases)

- llama-swap front-end. Operators who want multi-model swap can layer
  it themselves on top of the `external` tier.
- Fine-tuning UI.
- LoRA hot-swap.
- Multi-host inference (one HLH talking to another HLH’s sidecars).
  Multi-host = pick `external` tier and point at the other host.
- BYOM (bring your own model) file upload. v1 = HF-pull only.
- Model library browser like LM Studio. Defer indefinitely.
- Hybrid retrieval modes for bge-m3 (would require dim-lock change).
- Auto-binding workspaces to the bundled chat provider. Operator
  picks explicitly per workspace. (Embed + rerank auto-bind at the
  global level — different concern.)

-----

## Open questions (resolve before the relevant phase starts)

- **Q1 (Phase 2):** infinity-emb vs llama.cpp embedding server.
  infinity wins on multi-model concurrency; llama.cpp wins on
  uniformity with chat/VLM sidecars. Decide at Phase 2 kickoff.
- **Q2 (Phase 3):** MedSigLIP license terms. HAI-DEF may forbid
  redistribution via download script — would require a manual
  download flow distinct from the puller.
- **Q3 (Phase 4):** STT input format. Web Audio API gives webm/opus
  by default; whisper.cpp wants wav/mp3. Transcode in browser
  (smaller upload) or in `hlh_api` (simpler frontend)?
- **Q4 (Phase 5):** OCR-only path needed? Run the eval at end of
  Phase 3 before committing engineering time.
- **Q5 (Phase 6):** MLX backend feasibility on the friend’s actual
  hardware. If she’s not on Apple silicon, Phase 6 stays deferred
  indefinitely.
- **Q6 (cross-phase):** Update flow when a tier’s default model
  bumps version. Proposal: leave old gguf on disk, switch the
  `MODEL_REGISTRY` pointer, operator manually clears old artifacts
  from the volume. Revisit if disk usage becomes a real complaint.
- **Q7 (cross-phase):** Exclude `hlh_models` volume from backrest by
  default. Models are 2-15 GB each and reproducible from HF; backups
  are wasted bytes. Confirm at backrest config time.

-----

## Cross-references

- Repo: `ssh://git@git.indifferentketchup.com:2222/indifferentketchup/homelabhealth.git`
- Stack: `/opt/homelabhealth/`
- Existing crypto module (`8ec7dd7`) — not used by built-in providers
  (no `api_key` to encrypt) but applies to record data the sidecars
  touch.
- pgvector dim lock at 1024 — Phase 2 embed model must match.
- Project context — `cd /opt/homelabhealth` operational rules apply
  (Tailscale binding, no commits on Sam’s behalf without explicit
  opt-in, backups before destructive ops).
