> **Historical (2026-05-22):** Superseded by bundled-system-takes-everything (v0.7.0) and subsequent phases through v0.25.0. Do not implement from this doc without checking [roadmap.md](roadmap.md) and [CONTEXT.md](CONTEXT.md).

> **Note (2026-05-22):** The Phase 1 design's deferral of embed/rerank bundling has been superseded by [`2026-05-22-bundled-system-takes-everything-design.md`](superpowers/specs/2026-05-22-bundled-system-takes-everything-design.md). The `bundled-chat` provider has been renamed `HomeLab Health AI · Chat` (UUID preserved), and two sibling rows now exist for embed + rerank.

# HLH Bundled-AI — Phase 1 Design

Chat sidecar + model puller. Auto-seed bundled chat provider on tier confirm.

---

## Goals

1. Ship the first inference container (chat) inside HLH's docker-compose stack.
2. Download model weights on demand to a shared Docker volume, not baked into images.
3. Auto-seed a `bundled-chat` provider row on tier save so it's immediately usable.
4. Surface pull progress + license issues in the existing `Settings → System` tab.
5. Existing external-provider flow untouched.

## Non-goals (Phase 1)

- Embedding sidecar (Phase 2).
- Reranker sidecar (Phase 2).
- Vision / VLM (Phase 3).
- MedSigLIP (Phase 3).
- STT (Phase 4).
- OCR (Phase 5).
- Apple MLX tier (deferred to Phase 6).
- Hybrid retrieval modes for bge-m3 (Phase 3+ retrieval upgrade).
- Auto-binding workspaces to bundled-chat (operator picks explicitly).

---

## Tier model defaults (locked)

| Tier | Chat model | Quant | VRAM/RAM | Disk |
|---|---|---|---|---|
| `cpu-min` | Qwen3 1.7B | Q4_K_M | 2 GB RAM | ~1.2 GB |
| `cpu-std` | MedGemma 4B | Q4_K_M | 4 GB RAM | ~2.8 GB |
| `gpu-8gb` | MedGemma 4B | Q8_0 | 6 GB VRAM | ~4.5 GB |
| `gpu-16gb` | MedGemma 27B Text | Q4_K_M | 16 GB VRAM | ~16 GB |
| `gpu-24gb+` | MedGemma 27B Multimodal | Q4_K_M | 18 GB VRAM | ~18 GB |
| `apple-mlx` | MedGemma 4B MLX | — | unified | — |
| `external` | (no bundled pull) | — | — | — |

**MedGemma is gated on HuggingFace.** Operator needs `HF_TOKEN` set AND to accept the Gemma License at https://huggingface.co/google/medgemma-* before download. The model puller's error handling surfaces this explicitly on 401.

`apple-mlx` deferred to Phase 6. Detection still fires; recommendation falls back to `cpu-std` at runtime on darwin/arm64.

---

## Schema additions

```sql
CREATE TABLE IF NOT EXISTS bundled_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role            TEXT NOT NULL CHECK (role IN ('chat', 'embed', 'rerank', 'vision', 'medsiglip', 'stt', 'ocr')),
    tier            TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    quant           TEXT,
    repo            TEXT NOT NULL,
    filename        TEXT NOT NULL,
    expected_bytes  BIGINT,
    sha256          TEXT,
    license         TEXT,
    license_url     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'pulling', 'ready', 'failed', 'skipped'))
                    DEFAULT 'pending',
    pulled_bytes    BIGINT NOT NULL DEFAULT 0,
    error_message   TEXT,
    pull_started_at TIMESTAMPTZ,
    pull_finished_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role, tier, model_id, quant)
);
```

Idempotent. Re-applies are no-ops. Existing `providers` and `system_profile` tables unchanged.

---

## Backend services

### `services/model_puller.py`

`MODEL_REGISTRY` — Python dict mapping `(role, tier) -> ModelSpec`. Phase 1 entries cover chat only; other roles get `None` placeholders so the schema is exercised but no pulls happen.

```python
MODEL_REGISTRY = {
    "chat": {
        "cpu-min":   ModelSpec(repo="Qwen/Qwen3-1.7B-GGUF", filename="qwen3-1.7b-q4_k_m.gguf", ...),
        "cpu-std":   ModelSpec(repo="google/medgemma-4b-it", filename="medgemma-4b-q4_k_m.gguf", license="gemma", license_url="https://huggingface.co/google/medgemma-4b-it"),
        "gpu-8gb":   ModelSpec(repo="google/medgemma-4b-it", filename="medgemma-4b-q8_0.gguf", license="gemma", license_url="..."),
        "gpu-16gb":  ModelSpec(repo="google/medgemma-27b-text-it", filename="medgemma-27b-text-q4_k_m.gguf", license="gemma", license_url="..."),
        "gpu-24gb+": ModelSpec(repo="google/medgemma-27b-it", filename="medgemma-27b-mm-q4_k_m.gguf", license="gemma", license_url="..."),
        "apple-mlx": None,  # Phase 6
        "external":  None,
    },
    "embed":     {tier: None for tier in ALL_TIERS},  # Phase 2
    "rerank":    {tier: None for tier in ALL_TIERS},  # Phase 2
    "vision":    {tier: None for tier in ALL_TIERS},  # Phase 3
    "medsiglip": {tier: None for tier in ALL_TIERS},  # Phase 3
    "stt":       {tier: None for tier in ALL_TIERS},  # Phase 4
    "ocr":       {tier: None for tier in ALL_TIERS},  # Phase 5
}
```

### Pull mechanics

- Streaming download via `huggingface_hub.hf_hub_download` or direct HTTP GET. Do NOT load full file into memory.
- Write to `<filename>.partial`, fsync, rename to final filename on success.
- Update `pulled_bytes` every ~5 MB chunk boundary.
- sha256 verified after rename. On mismatch: delete file, status=`failed`, error_message="sha256 mismatch".
- 401 from HuggingFace → status=`failed`, error_message="License acceptance required. Visit <license_url> and click Agree, then retry."
- Concurrency: single asyncio.Lock at module level. One pull at a time globally.
- Cancellation: shared event flag, checked at chunk boundary. On cancel: delete `.partial`, status=`failed`, error_message="cancelled".

### `services/bundled_providers.py`

`ensure_bundled_chat_provider(conn)`:
- Idempotent upsert by name.
- `name='bundled-chat'`, `base_url='http://hlh_chat:9610'`, `enabled=TRUE`, `api_key=NULL`.
- Only runs if `system_profile.setup_complete=TRUE` AND tier ≠ `external`.
- Called from lifespan on app start AND from PUT `/api/system/profile` after a successful tier save.

---

## API endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/models` | List `bundled_models` rows. |
| GET | `/api/models/:id` | Single row detail. |
| POST | `/api/models/:id/pull` | Background-task trigger. 202 + row. |
| POST | `/api/models/pull-for-tier` | Body `{tier}`. Pulls every role with a spec. 202 + queued ids. |
| POST | `/api/models/:id/cancel` | Sets cancel flag for active pull. 200. |

All admin-only.

---

## Docker compose changes

Volume:
```yaml
volumes:
  hlh_models:
    driver: local
```

Service:
```yaml
hlh_chat:
  image: ghcr.io/ggerganov/llama.cpp:server-<pinned-tag>
  volumes:
    - hlh_models:/models:ro
  environment:
    - HLH_CHAT_MODEL_PATH=${HLH_CHAT_MODEL_PATH}
    - HLH_CHAT_PORT=${HLH_CHAT_PORT:-9610}
    - HLH_CHAT_NGL=${HLH_CHAT_NGL:-0}
  command: >
    --model ${HLH_CHAT_MODEL_PATH}
    --host 0.0.0.0
    --port ${HLH_CHAT_PORT}
    --n-gpu-layers ${HLH_CHAT_NGL}
    --jinja
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://localhost:9610/v1/models"]
    interval: 30s
    timeout: 5s
    retries: 3
  profiles: [chat]
  depends_on:
    - hlh_api
```

`hlh_api` mounts `hlh_models:/models:rw` so the puller can write.

Chat sidecar is NOT exposed on host. Internal Docker network only. `hlh_api` proxies to it via the provider URL `http://hlh_chat:9610`.

Profile `chat` is added to default `COMPOSE_PROFILES` in `.env` once Phase 1 lands. Operators on `external` tier omit the profile to skip the sidecar.

---

## Frontend changes

### `SystemTab.jsx` additions

1. **Models sub-section** below the tier picker.
   - Title: "Models for this tier"
   - Table polling `GET /api/models` filtered to current tier every 2s while any row is `pulling`.
   - Columns: Role | Model | Status badge | Progress bar | License | Action
   - Action buttons: Pull (if status=pending/failed), Cancel (if status=pulling), View on HF (always — link to license_url).
   - Inline error on license-acceptance failure.

2. **Tier string update** (Phase 0 deferred work).
   - `cpu-std` label: "MedGemma 4B (cpu-std)"
   - `gpu-8gb`: "MedGemma 4B Q8 (gpu-8gb)"
   - `gpu-16gb`: "MedGemma 27B Text (gpu-16gb)"
   - `gpu-24gb+`: "MedGemma 27B Multimodal (gpu-24gb+)"
   - etc.

3. **Advanced toggle for external tier.**
   - Wrap external radio in `<details>` element.
   - Summary: "Advanced: bring your own inference"
   - Body: external radio + one-line copy "You'll need to configure providers in Settings before HLH can chat or embed records."
   - Collapsed by default. No persistence.

### `api/models.js`

5 wrappers: `listModels()`, `getModel(id)`, `pullModel(id)`, `pullForTier(tier)`, `cancelPull(id)`.

---

## Lifespan ordering

In `backend/main.py` `lifespan()`:

```
1. init_pool()
2. apply_schema()
3. seed_default_assets()         # existing
4. _warn_deprecated_env_vars()    # existing
5. model_puller.seed_registry()   # NEW Phase 1
6. ensure_bundled_chat_provider() # NEW Phase 1, conditional on setup_complete
```

---

## License surface (operator-facing copy)

| Component | License | Operator action |
|---|---|---|
| Qwen3 | Apache-2.0 | None |
| MedGemma 4B/27B | Gemma License | Set `HF_TOKEN`, accept license at HF page |
| bge-m3 (Phase 2) | MIT | None |
| bge-reranker family (Phase 2) | MIT | None |
| Qwen3-Reranker (Phase 2) | Apache-2.0 | None |
| MedSigLIP (Phase 3) | HAI-DEF terms | Review at implementation time |
| Whisper (Phase 4) | MIT | None |
| Tesseract (Phase 5) | Apache-2.0 | None |
| PaddleOCR (Phase 5) | Apache-2.0 | None |

Wizard shows license + action for the current-tier-recommended model before pull triggers.

---

## Tests

`verify_model_puller.py`:
- MODEL_REGISTRY shape valid (every key resolves to ModelSpec or None).
- seed_registry idempotent (2 runs, same row count).
- Streaming download of a tiny public artifact (1 KB-ish) lands at expected path with status=ready.

`verify_model_endpoints.sh`:
- GET /api/models 200 array.
- GET /api/models/:id 200, 404.
- POST pull-for-tier with bad tier → 400.
- POST :id/pull queues background task, status flips to pulling.
- POST :id/cancel sets failed + cancelled.
- After tier save: bundled-chat provider exists in /api/providers.

`verify_models_ui.py`:
- Models sub-section renders, polls, shows progress.
- External hidden by default; visible after Advanced expand.
- Tier strings show MedGemma names per the table.

Regression: all prior 236 assertions stay green.

---

## Out of scope / open questions

- **Model versioning** — MODEL_REGISTRY is a static dict in code. Future phase: surface model updates without code change. Phase 1 keeps it simple.
- **Disk pre-flight check** — wizard could refuse a tier if disk_free_gb < expected_bytes. Phase 1 reports the download size on Pull click; no hard gate.
- **Multi-machine inference** — if operator has a separate GPU box, they pick `external` tier and point at it. Bundled-AI is single-host only.
- **MedGemma license acceptance flow** — currently surfaced as an error after a 401. Future polish: detect gated repos at registry-seed time and require acceptance in the wizard before pull-for-tier is offered.

---

## Phase 1 — As shipped

Phase 1 landed on branch `feat/phase-1-chat-sidecar` in 7 commits (`371594d` schema → `15264c0` E2E test). Final verification: **393 assertions PASS** — 381 across 12 regression verify scripts plus 12 in the new `verify_phase1_e2e.py`. The shipped surface matches the design above with the deviations and gaps recorded below — kept in-spec so what's-in-the-box and what's-still-open are both visible.

### Deviations from the design

**Qwen3 1.7B quant is Q8_0, not Q4_K_M.** The design specifies Q4_K_M for the `cpu-min` chat tier, but the official `Qwen/Qwen3-1.7B-GGUF` HuggingFace repo only ships Q8_0. Picked the available quant — ~1.8 GB on disk instead of the design's ~1.2 GB target, still well within the cpu-min 2 GB RAM ceiling. Reflected in `MODEL_REGISTRY['chat']['cpu-min']` (`backend/services/model_puller.py`), `.env.example` default, `docker-compose.yml` default command, and the `cpu-min` tier card in `SystemTab.jsx`. Operator can override at runtime.

### Known gaps (deferred)

| Gap | Detail | Future tidy |
|---|---|---|
| MedGemma filenames are unverified placeholders | `MODEL_REGISTRY` carries `medgemma-4b-it-Q4_K_M.gguf`, `medgemma-4b-it-Q8_0.gguf`, `medgemma-27b-text-it-Q4_K_M.gguf`, and `medgemma-27b-it-Q4_K_M.gguf` straight from the design. Each repo is gated, so a real pull needs `HF_TOKEN` + license acceptance — none were smoke-tested during Phase 1. Operator hits a clear 404 with retry instructions if any filename is wrong. | Confirm each Phase 1 chat tier's GGUF filename and pin a revision before public release. |
| `hlh_chat` image tag is unpinned | `docker-compose.yml` uses the floating `ghcr.io/ggml-org/llama.cpp:server`. Pinning deferred until the model file format / API contract is stable for this stack. | Pin to a specific build (`server-bNNNN`) once the format/API is stable. |
| No sha256 pinning in `MODEL_REGISTRY` | `ModelSpec.sha256` is `None` for every Phase 1 entry. The puller correctly verifies integrity when a value is set; values were not collected in Phase 1. | Add expected sha256s alongside the filename pins above. |
| No container hardening on `hlh_chat` | Runs on the default bridge network with no `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, `mem_limit`, or non-root `user`. Phase 1 prioritized happy-path round-trip. | Hardening pass: split inference onto an internal-only network; add `read_only: true` + `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges:true`, per-tier `mem_limit`, `user: 1000:1000`. |
