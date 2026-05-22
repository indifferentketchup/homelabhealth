# HLH Bundled-AI — Phase 0 Design

Hardware detection + tier picker UI. No inference containers in this phase.

---

## Goals

1. Detect what the host machine can run.
2. Recommend an AI tier.
3. Persist operator's chosen tier so later phases (1-6) can read it.
4. Web UI on first login. No SSH required for the operator.

## Non-goals (Phase 0)

- Pulling models.
- Starting inference containers.
- Changing embedding dim (locked at 1024).
- Changing existing external-provider flow (untouched).

---

## Tier definitions

Embedding dim locked at 1024 across all tiers.

| Tier | Detect rule | Chat default | Embed default | Rerank default | Vision | STT |
|---|---|---|---|---|---|---|
| `cpu-min` | <16 GB RAM, no GPU | Qwen3 1.7B Q4 | bge-large-en-v1.5 Q4 | flashrank | — | whisper tiny |
| `cpu-std` | >=16 GB RAM, no GPU | Qwen3 4B Q4 | bge-large-en-v1.5 Q8 | bge-reranker-base CPU | — | whisper base |
| `gpu-8gb` | 6-10 GB VRAM | Qwen3 8B Q4 | bge-large-en-v1.5 FP16 | bge-reranker-v2-m3 | — | whisper small |
| `gpu-16gb` | 12-18 GB VRAM | Qwen3 14B Q4 | Harrier-0.6B Q8 | Qwen3-Reranker-0.6B | Qwen2.5-VL-3B | whisper medium |
| `gpu-24gb+` | >=24 GB VRAM | Qwen3 32B Q4 | Harrier-0.6B Q8 | Qwen3-Reranker-0.6B | Qwen2.5-VL-7B | whisper large |
| `apple-mlx` | Apple Silicon, >=16 GB unified | Qwen3 MLX | bge-large-en-v1.5 MLX | bge-reranker-v2-m3 MLX | Qwen2.5-VL MLX | whisper.cpp Metal |
| `external` | operator chose external only | — | — | — | — | — |

`external` is always selectable. Disables Phases 1-6 sidecars entirely.

---

## Sysinfo collection

New backend module: `backend/services/sysinfo.py`

Detection sources (graceful fallback if any fail):

| Field | Source | Notes |
|---|---|---|
| `os` | `platform.system()` | linux / darwin / windows |
| `arch` | `platform.machine()` | x86_64 / arm64 |
| `cpu_model` | `/proc/cpuinfo` (linux), `sysctl machdep.cpu.brand_string` (darwin) | string |
| `cpu_cores` | `os.cpu_count()` | physical preferred via psutil |
| `ram_total_gb` | `psutil.virtual_memory().total` | rounded |
| `disk_free_gb` | `shutil.disk_usage` on the volume containing model cache | |
| `gpus[]` | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` | parsed; empty if no nvidia-smi |
| `apple_silicon` | `arch == arm64 and os == darwin` | unified memory inferred from `ram_total_gb` |

All subprocess calls are wrapped: 2s timeout, log on failure, return null for that field. Detection failure never blocks the operator — they get the manual picker.

### Tier recommendation

`recommend_tier(sysinfo) -> tier_id` is pure-function logic over the table above. Picks the most capable tier the hardware can sustain. Returns `cpu-min` as the floor.

---

## Schema

New table: `system_profile`. One row (singleton, `id = 1`).

```sql
CREATE TABLE system_profile (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tier            TEXT NOT NULL DEFAULT 'external',
    tier_source     TEXT NOT NULL CHECK (tier_source IN ('auto', 'manual')) DEFAULT 'manual',
    sysinfo_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    detected_at     TIMESTAMPTZ,
    chosen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    setup_complete  BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO system_profile (id) VALUES (1) ON CONFLICT DO NOTHING;
```

`setup_complete = FALSE` triggers the first-boot wizard. Set to `TRUE` after operator confirms tier.

---

## API endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/system/hardware` | Run sysinfo collection live, return JSON. Does not write to DB. |
| GET | `/api/system/profile` | Return current `system_profile` row + computed `recommended_tier`. |
| PUT | `/api/system/profile` | Body: `{tier, tier_source}`. Validate tier in allowed set. Set `chosen_at = NOW()`, `setup_complete = TRUE`. |
| POST | `/api/system/redetect` | Re-run sysinfo, store under `sysinfo_json`, update `detected_at`. Does not change tier. |

All admin-only. Existing auth middleware.

---

## Frontend

New page: `Settings -> System` (admin-only).

Layout:

1. **Detected hardware** — read-only card showing CPU, RAM, GPU(s), disk free. "Re-detect" button.
2. **Recommended tier** — badge with the auto-recommendation and a one-line rationale ("16 GB GPU detected -> gpu-16gb").
3. **Tier selector** — radio group of all tiers including `external`. Pre-selected to recommended. Each option shows: chat model, embed model, rerank model, vision/STT availability, approx VRAM/RAM footprint, approx disk required.
4. **Save** — `PUT /api/system/profile`. Disabled until selection differs from current or `setup_complete = FALSE`.

First-boot gate: if `setup_complete = FALSE`, redirect any post-login navigation to `Settings -> System` until saved.

---

## Migration / upgrade behavior

- Migration adds `system_profile` table, inserts singleton row with `tier = 'external'`, `setup_complete = FALSE`.
- Existing installs: operator sees the wizard on next login, can confirm `external` to dismiss.
- No existing data is touched.

---

## Tests

1. `sysinfo` collection on linux + no GPU returns valid JSON, `gpus = []`.
2. `recommend_tier` for each detection profile returns the expected tier.
3. `recommend_tier` on missing data returns `cpu-min`.
4. PUT `/api/system/profile` with invalid tier -> 400.
5. PUT with valid tier sets `setup_complete = TRUE`.
6. Wizard redirect logic: `setup_complete = FALSE` + admin login -> redirected. After PUT -> no redirect.

---

## Out of scope, deferred to later phases

- Pulling model weights (Phase 1+).
- Starting inference containers (Phase 1+).
- Auto-seeding `providers` rows for bundled inference (Phase 1).
- Re-tiering after data exists (re-embed cost: documented in Phase 2).
- Disk-space pre-flight check before model pull (Phase 1).

---

## Risks / open questions

- **`nvidia-smi` in container.** Detection must run with GPU passthrough or read host info. Phase 0 reads `/proc/driver/nvidia/version` and `/dev/nvidia*` first, falls back to `nvidia-smi` only if available. If neither, GPU is reported as absent. Document that operators with GPUs must ensure passthrough is configured before relying on auto-detect.
- **Detection lies on shared hosts.** A VPS with 64 GB RAM advertised but heavily oversubscribed will recommend `cpu-std` and underperform. Mitigation: rationale string + "you can change this anytime" copy.
- **Tier change after data exists.** Changing embedder = re-embed everything. Phase 2 must hard-warn before allowing the change. Phase 0 doesn't gate this; just record `chosen_at` for later phases to reason about.
