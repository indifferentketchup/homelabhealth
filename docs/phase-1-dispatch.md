#careful

> **Note (2026-05-30):** MedSigLIP (the standalone `medsiglip` / `vision_embed` image-embedding sidecar) was removed from the product. The `medsiglip` role and the `hlh_vision_embed` sidecar no longer exist. References below are historical. MedGemma vision (chat/ingestion) is unaffected.

# HLH Bundled-AI — Phase 1: Chat Sidecar + Model Puller

Branch off `v1.11.0`: `feat/phase-1-chat-sidecar`.

Repo: `/opt/homelabhealth` on ubuntu-homelab.
Live ports: API `9600`, UI `9604`. DB user/db both `hlh`.
Deploy: `docker compose up --build -d`. Backend rebuild: `docker compose build --no-cache hlh_api`.

## Hard rules

1. **Commits at subphase checkpoints, same pattern as Phase 0.** One commit per subphase, per-step messages, no squash. No tag — I drive the tag.
2. **No merge to main.** Stay on `feat/phase-1-chat-sidecar` until I merge.
3. **Backup before any destructive edit:** `cp file file.bak-phase1-$(date +%Y%m%d)`.
4. **Run `ls frontend/src/components/ui/` before importing primitives.** Import only what exists.
5. **Never modify `frontend/src/hooks/useStream.js`.**
6. **Schema changes must be idempotent** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, guarded constraints).
7. **Stop and report** on any ambiguity, pre-existing state mismatch, test failure, or design conflict.
8. **No edits outside the file list** at the end of this prompt. If you need to touch something not listed, stop and report.

## Scope (this phase only)

Ship the first bundled-AI inference container: chat. A separate model-puller init container downloads weights on first boot to a Docker volume. HLH auto-seeds the bundled chat provider into the `providers` table. The Settings → System tab gets a "Models" sub-panel showing pull status. Existing external-provider flow stays unchanged.

**Out of scope (Phase 2+):**
- Embedding sidecar (bge-m3).
- Reranker sidecar.
- Vision (VLM).
- MedSigLIP.
- STT.
- OCR.
- Workspace UI tier-name string updates (those fold in here as a side-job, see §1.G).

## Design source of truth

`/tmp/hlh_phase1_design.md` (I will place this file before you start). Read it first. If anything in this prompt conflicts with the design doc, the design doc wins — stop and report.

## Tier model defaults (locked, do not re-derive)

| Tier | Chat model | Quant | Approx VRAM/RAM | Disk |
|---|---|---|---|---|
| `cpu-min` | Qwen3 1.7B | Q4_K_M | 2 GB RAM | 1.2 GB |
| `cpu-std` | MedGemma 4B | Q4_K_M | 4 GB RAM | 2.8 GB |
| `gpu-8gb` | MedGemma 4B | Q8_0 | 6 GB VRAM | 4.5 GB |
| `gpu-16gb` | MedGemma 27B Text | Q4_K_M | 16 GB VRAM | 16 GB |
| `gpu-24gb+` | MedGemma 27B Multimodal | Q4_K_M | 18 GB VRAM | 18 GB |
| `apple-mlx` | MedGemma 4B | MLX | unified | varies |
| `external` | (no bundled pull) | — | — | — |

Chat sidecar serves OpenAI-compatible `/v1/chat/completions` and `/v1/models`. llama.cpp-server is the implementation. The Apple `apple-mlx` tier is **out of scope for Phase 1** — flag as "deferred to Phase 6" and skip; cpu-std fallback for any darwin/arm64 detection at runtime.

## Plan (subphases, gate between each)

### Subphase 1.A — Inventory (read-only)

1. `git status` clean; branch off `v1.11.0` as `feat/phase-1-chat-sidecar`; confirm.
2. `grep -rn 'hlh_chat\|model_pull\|model_puller\|bundled' backend/ frontend/ docker-compose*.yml 2>/dev/null | grep -v node_modules | grep -v __pycache__` — confirm zero pre-existing references.
3. Confirm `docker-compose.yml` is the live deploy file. Note any other compose files.
4. Inspect `system_profile` table state: `SELECT id, tier, tier_source, setup_complete FROM system_profile;`. Report current row.
5. `ls /var/lib/docker/volumes/ 2>/dev/null | grep -i hlh || echo "no hlh volumes yet (sudo may be required)"` — for context only, do not require sudo.

Stop. Report. Wait for "continue."

### Subphase 1.B — Schema

Append to `backend/schema.sql`:

```sql
-- Bundled-AI: model artifacts and pull tracking (added Phase 1).
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

CREATE INDEX IF NOT EXISTS bundled_models_role_tier_idx ON bundled_models (role, tier);
CREATE INDEX IF NOT EXISTS bundled_models_status_idx ON bundled_models (status);
```

Apply via:
```
docker exec -i hlh_db psql -U hlh -d hlh < backend/schema.sql
```

Verify schema is idempotent (second apply prints "already exists, skipping").

Stop. Report. Wait for "continue."

### Subphase 1.C — Backend: model-puller service

Create `backend/services/model_puller.py`:

- `MODEL_REGISTRY: dict[str, dict[str, ModelSpec]]` — maps `(role, tier)` → `ModelSpec(repo, filename, quant, expected_bytes, sha256, license, license_url)`. Hard-code Phase 1 chat entries per the tier table above. The other roles get `None` placeholders so the schema is exercised but no pulls happen.
- `seed_registry(conn) -> None` — idempotent upsert from `MODEL_REGISTRY` into `bundled_models`. Skip rows where the spec is `None`.
- `async pull_model(role, tier) -> None` — looks up the row, streams from HuggingFace to the shared model volume at `/models/<role>/<tier>/<filename>`, updates `pulled_bytes` every ~5 MB, verifies sha256, sets status `ready` on success or `failed` with error_message. Handles gated-repo 401s with a clear `error_message`: "License acceptance required. Visit <license_url> and click Agree, then retry."
- `async pull_for_tier(tier) -> dict[str, str]` — pulls every role that has a spec for this tier. Returns `{role: status}`.
- Reads `HF_TOKEN` from env if present (passed via `huggingface_hub.hf_hub_download` or direct HTTP `Authorization: Bearer …`).
- Streaming downloader. Do NOT load entire file into memory. Write to `<filename>.partial`, fsync, rename on success.
- Concurrency: one pull at a time globally (asyncio.Lock at module level). Pull queue is fine for Phase 1 — single chat model, no parallelism gain.

Add `huggingface-hub>=0.24.0` to `backend/requirements.txt` if not present.

Create `backend/scripts/verify_model_puller.py`:
- Smoke test of `MODEL_REGISTRY` shape (every role/tier key has a valid spec or None).
- `seed_registry()` upsert idempotency (run twice, row count unchanged).
- Mock HF response: download a tiny known artifact (use a public Hello-World repo or a hash file ~1 KB) to confirm the streaming + sha256 path end-to-end without pulling multi-GB weights. Path: pick `hf-internal-testing/tiny-random-bert` or similar; the test asserts the file lands at the expected path with non-zero bytes and status=`ready`.
- Skip the real MedGemma pull in this script (gated, license; not a smoke).

Stop. Report. Wait for "continue."

### Subphase 1.D — Backend: model-pull endpoints

Create `backend/routers/models.py`:

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/models` | List all `bundled_models` rows. Returns `[{role, tier, model_id, status, pulled_bytes, expected_bytes, error_message, license, license_url}, ...]` |
| GET | `/api/models/:id` | Single row detail. |
| POST | `/api/models/:id/pull` | Triggers `pull_model()` as a background task. Returns 202 with the row. |
| POST | `/api/models/pull-for-tier` | Body: `{tier}`. Triggers `pull_for_tier()`. Returns 202 with `{queued: [model_ids]}`. |
| POST | `/api/models/:id/cancel` | If status=`pulling`, cancels (sets status=`failed`, error_message="cancelled"). |

All admin-only via existing `require_admin`.

Mount in `backend/main.py`: add `models` to imports, `api.include_router(models.router, prefix="/models", tags=["models"])`. Match the pattern from providers/system mounts.

Background task pattern: use `asyncio.create_task(...)` with a module-level set to track running pulls; on cancel, set a flag the task checks at the next chunk boundary.

Auto-seed: on app startup, after `apply_schema()`, call `model_puller.seed_registry()` so `bundled_models` is always populated with the current registry. Mirrors the existing `seed_default_assets()` pattern.

Create `backend/scripts/verify_model_endpoints.sh`:
- GET `/api/models` → 200, JSON array, contains the seeded chat rows.
- GET `/api/models/:id` → 200 for a valid id, 404 for unknown.
- POST `/api/models/pull-for-tier` with invalid tier → 400.
- POST `/api/models/:id/pull` queues, status flips to `pulling` (eventually to `ready` or `failed` — the verify script tolerates either, doesn't wait for full download).
- POST `/api/models/:id/cancel` while pulling → 200, status=`failed` with error_message="cancelled".

Build: `docker compose build --no-cache hlh_api` then `up -d`.

Stop. Report. Wait for "continue."

### Subphase 1.E — Docker compose: chat sidecar + model volume

Modify `docker-compose.yml`:

- Add named volume `hlh_models` (or whatever convention matches the existing volume names; check pgdata volume naming first).
- Add service `hlh_chat`:
  - Image: `ghcr.io/ggerganov/llama.cpp:server` (or the pinned tag the project already uses elsewhere; check `inference_stack_context.md` if referenced).
  - Mounts: `hlh_models:/models:ro`.
  - Command: parameterized by env `HLH_CHAT_MODEL_PATH`, `HLH_CHAT_PORT` (default 9610), `HLH_CHAT_NGL` (gpu offload layers).
  - Port: bind only to internal Docker network. Do NOT publish on host except in a dev override.
  - Profile: `chat`. Default profile in `.env` should include `chat` once Phase 1 is wired.
  - Healthcheck: `curl -fsS http://localhost:9610/v1/models || exit 1`, interval 30s.
  - depends_on: `hlh_api` (api seeds the volume path and confirms model is ready).
- `hlh_api` service: add `hlh_models:/models:ro` mount so the puller can write (downgraded to `rw` on the api side; chat reads `ro`).
- Optional: add a one-shot `hlh_model_puller` service that exits 0 once the chat model for the chosen tier is ready. Implementation detail: this can be a Python entrypoint that calls `pull_for_tier` and exits, OR the api can handle it on first lifespan start. **Pick one and report which.**

`.env` updates:
- `HLH_CHAT_MODEL_PATH` (default `/models/chat/cpu-min/Qwen3-1.7B-Q4_K_M.gguf`).
- `HLH_CHAT_PORT=9610`.
- `HLH_CHAT_NGL=0` (cpu default; gpu tiers override).
- `HF_TOKEN=` (empty default; operator fills in if needed for MedGemma).

Update `.env.example` to match.

Stop. Report. Wait for "continue."

### Subphase 1.F — Auto-seed bundled chat provider

In `backend/services/model_puller.py` or a new `backend/services/bundled_providers.py`:

- `async ensure_bundled_chat_provider(conn) -> None` — idempotent. Inserts (or updates by name) a row in `providers` named `bundled-chat` with `base_url=http://hlh_chat:9610`, `enabled=TRUE`, `api_key=NULL`. The api_key field is nullable in v1.10.0 schema (confirm).
- Called from lifespan AFTER schema apply, AFTER `seed_registry()`, AFTER `setup_complete` is true. If `setup_complete=false`, no-op.
- Also called from the PUT `/api/system/profile` handler after a successful tier save, so the bundled provider exists as soon as the operator confirms a tier.
- After insert/update, if `global_settings.embedding_provider_id` is null AND tier ≠ `external`, DO NOT auto-bind chat to workspaces. Operator picks per-workspace explicitly. (Embedding/reranker auto-binding is Phase 2.)

Add to `backend/scripts/verify_model_endpoints.sh`:
- After saving a tier, GET `/api/providers` includes a row with name=`bundled-chat`, enabled=true.
- Re-running the seed is idempotent (no duplicate rows, no error).

Stop. Report. Wait for "continue."

### Subphase 1.G — Frontend: Models pull panel + tier-string update

1. Create `frontend/src/api/models.js`: 5 wrappers for the endpoints in 1.D.
2. Add a "Models" sub-section inside `SystemTab.jsx` (do NOT create a new top-level tab):
   - Table of rows from `GET /api/models` filtered to the current tier.
   - Columns: role, model_id, status, progress bar (pulled_bytes / expected_bytes), license link, action (Pull / Cancel).
   - Polls every 2s while any row is `pulling`. Stops polling when no rows are `pulling`.
   - License acceptance error surfaces inline: "License acceptance required. <a href=license_url>Visit and accept here.</a>"
3. **Tier-string update (fold-in from Phase 0):** rewrite the tier display strings in `SystemTab.jsx` to match the locked tier table. Qwen3 → MedGemma for cpu-std and up, etc. Same table as the top of this prompt.
4. **External tier handling (also fold-in):** wrap the `external` radio in an `<details>` element labeled "Advanced: bring your own inference" with a warning copy: "You'll need to configure providers in Settings before HLH can chat or embed records." Collapsed by default; state does not persist across reloads.
5. Honor `?tab=system` URL param (already wired in Phase 0; just confirm).
6. `ls frontend/src/components/ui/` first. If you need a primitive not present, stop and report.

Deploy: `docker compose up --build -d`.

Create `backend/scripts/verify_models_ui.py` (Playwright):
- Navigate to `/settings?tab=system`.
- Confirm Models sub-section is present with rows for the current tier.
- Confirm tier-string update: cpu-std radio label includes "MedGemma 4B".
- Confirm external radio is hidden by default; expand "Advanced" → external becomes visible.
- Trigger a pull on the smallest tier's chat row (or a mocked HF endpoint, since real MedGemma requires `HF_TOKEN`). Confirm status flips to `pulling`, progress bar renders, polling fires.
- Trigger cancel. Confirm status flips to `failed` with error_message visible.

Stop. Report. Wait for "continue."

### Subphase 1.H — E2E + regression sweep

1. Run `verify_models_ui.py` clean from `setup_complete=true` AND from `setup_complete=false`.
2. Full regression sweep of all prior verify scripts. Expected: 236 + new Phase 1 assertions, all PASS.
   - `verify_providers_crud.sh`
   - `verify_providers_live.sh`
   - `verify_embedding_reranker_settings.sh`
   - `verify_providers_ui.py`
   - `verify_embedding_reranker_ui.py`
   - `verify_workspace_provider_picker.py`
   - `verify_sysinfo.py`
   - `verify_system_endpoints.sh`
   - `verify_system_ui.py`
   - `verify_model_puller.py` (new)
   - `verify_model_endpoints.sh` (new)
   - `verify_models_ui.py` (new)
3. End-to-end chat test: after pulling the smallest tier's chat model and the bundled-chat provider auto-seed, bind a test workspace to `bundled-chat` + the chat model, send a real message, assert a non-empty streamed reply. This replaces the v1.10.0 step-8 "OK" test using the bundled chat instead of external llama-swap.
4. Confirm `setup_complete=false` on exit so the next consumer sees fresh-first-boot state.

Stop. Report final assertion counts + diff stat + screenshots from `/tmp/phase1-evidence/`.

## File list (everything this phase may touch)

NEW:
- `backend/services/model_puller.py`
- `backend/services/bundled_providers.py` (or fold into model_puller.py — pick one)
- `backend/routers/models.py`
- `backend/scripts/verify_model_puller.py`
- `backend/scripts/verify_model_endpoints.sh`
- `backend/scripts/verify_models_ui.py`
- `frontend/src/api/models.js`

MODIFIED:
- `backend/schema.sql`
- `backend/main.py` (models router mount + lifespan seed_registry + ensure_bundled_chat_provider call; do NOT touch deprecated-env block or system router mount from Phase 0)
- `backend/requirements.txt` (huggingface-hub)
- `backend/routers/system.py` (call ensure_bundled_chat_provider after PUT /profile)
- `docker-compose.yml`
- `.env` and `.env.example`
- `frontend/src/components/settings/SystemTab.jsx` (Models sub-section + tier-string update + external Advanced toggle)
- `frontend/src/api/system.js` (if any wrapper changes needed)

If you need to touch anything else, stop and report.

## Commit pattern (same as Phase 0)

Commit at subphase checkpoints, one commit per subphase (1.B, 1.C, 1.D, 1.E, 1.F, 1.G, 1.H). 1.A is read-only, no commit. **No merge to main. No tag.** I drive both.

Commit messages: same shape as Phase 0 — `feat(scope): one-line summary` then bulleted body, then `Spec:` line if applicable.

## Report format (per subphase)

1. **Diff stat (this subphase only).**
2. **Files touched** — must match expected set for this subphase.
3. **Build/verify output** — full pass count.
4. **Skipped (per scope discipline)** — things you noticed but didn't fix.
5. **Open question / blocker** (if any).
6. **Next-step preview.**
