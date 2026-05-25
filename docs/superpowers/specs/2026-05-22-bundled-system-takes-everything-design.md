# Bundled-AI: system takes everything — Design

**Date:** 2026-05-22
**Status:** Shipped (v0.7.0). Historical design reference.
**Owner:** samkintop

## Goal

Eliminate model pickers from the user-facing UI. The hardware tier picked in Settings → System fully determines chat + embedding + reranker. The single visible default provider is "HomeLab Health AI"; it is immutable. External providers remain reachable only via an explicit "Change chat provider (advanced)" flow that swaps the **chat** binding (embed/rerank stay bundled). The HF token moves from `.env` to a DB-backed config with a UI input field.

This accelerates the embedding + reranker portions of Phase 2 (originally placeholders in `MODEL_REGISTRY`) so the bundled stack is self-sufficient end-to-end.

## Non-goals (v1)

- Per-tier embedding or reranker variants. One embedding model (`bge-m3`, 1024-dim) and one reranker model (`bge-reranker-v2-m3`) across every tier — bge-m3 is the only 1024-dim embedding the schema accepts, so per-tier variation is pointless until the vector dim becomes parameterized.
- External overrides for embedding or reranker. Only chat is overridable.
- Re-embedding existing data on tier change.
- Vector dimension migration.
- Apple MLX sidecar (still Phase 6).
- A unified "virtual provider" abstraction (single provider row with multiple roles). Three separate provider rows is sufficient and avoids a routing-layer rewrite.

## §1 — Architecture

### Sidecars (docker-compose.yml)

| Service | Image | Role | Internal port | Notes |
|---|---|---|---|---|
| `hlh_chat` | `ghcr.io/ggml-org/llama.cpp:server` (existing) | chat completions | 9610 | One chat model per tier (Qwen3 / MedGemma). |
| `hlh_infer` | `michaelfeil/infinity` (new) | embeddings + rerank | 9611 | Loads `BAAI/bge-m3` AND `BAAI/bge-reranker-v2-m3` in one process. Tag pinned during implementation. |

Both sidecars sit behind the `chat` compose profile (renamed to `bundled` for clarity in this change), unreachable from the host network, reachable inside `hlh_default` only.

`hlh_infer` reads weights from the shared `hlh_models` volume just like `hlh_chat`. The model puller writes `embed/<tier>/bge-m3.gguf` and `rerank/<tier>/bge-reranker-v2-m3.gguf` under `/models`.

### Bundled provider rows (DB)

Three rows in `providers`, all seeded at startup:

| `name` | `base_url` | Role |
|---|---|---|
| `HomeLab Health AI · Chat` | `http://hlh_chat:9610` | chat |
| `HomeLab Health AI · Embed` | `http://hlh_infer:9611` | embed |
| `HomeLab Health AI · Rerank` | `http://hlh_infer:9611` | rerank |

The UI shows these grouped as one logical "HomeLab Health AI" entity (see §6) but the DB has three distinct rows so the existing `providers` resolver code path doesn't change shape.

`api_key` stays `NULL`; bundled sidecars don't require auth on the internal network.

## §2 — Data model

### Provider rename + immutability

In `bundled_providers.py`:

- `BUNDLED_CHAT_NAME = "bundled-chat"` → `BUNDLED_CHAT_NAME = "HomeLab Health AI · Chat"`.
- New constants `BUNDLED_EMBED_NAME`, `BUNDLED_RERANK_NAME`, `BUNDLED_EMBED_BASE_URL`, `BUNDLED_RERANK_BASE_URL`.
- `ensure_bundled_chat_provider` becomes `ensure_bundled_providers(conn)` and seeds all three rows.
- Idempotent in-place rename:
  ```sql
  UPDATE providers SET name = 'HomeLab Health AI · Chat' WHERE name = 'bundled-chat';
  ```
  This preserves the existing UUID, so any workspace already bound by `provider_id` keeps working.

### Immutability flag + role + bundle group

Three new columns on `providers`:

```sql
ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS is_bundled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS role TEXT;       -- 'chat' | 'embed' | 'rerank' | NULL (NULL = general-purpose external)

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS bundle_group TEXT;  -- 'homelab-health-ai' for bundled rows; NULL for external. Free-text tag, not an FK.
```

Column choices:
- **`is_bundled`** — boolean immutability marker. Routers reject PATCH/DELETE on `is_bundled=TRUE`.
- **`role`** — what the provider can serve. Bundled rows get the specific role (`'chat'`, `'embed'`, `'rerank'`). External rows default to `NULL` meaning general-purpose (the existing assumption that one external base URL can serve any role). Workspace chat-provider picker filters with `is_bundled = FALSE OR role = 'chat'`.
- **`bundle_group`** — tag-style grouping label, not a `bundle_id` FK to a `bundles` table. The Providers list groups rows where `bundle_group IS NOT NULL` by that value and renders one logical entry that expands to show the three internal rows (chat/embed/rerank). External rows have `bundle_group = NULL` and render as individual entries.

Backfill on first apply (handles the existing `bundled-chat` row already living in the DB):
```sql
UPDATE providers
   SET is_bundled = TRUE,
       role = 'chat',
       bundle_group = 'homelab-health-ai'
 WHERE is_bundled = FALSE
   AND name IN ('bundled-chat', 'HomeLab Health AI · Chat');
```

**Ordering:** this backfill lives in `schema.sql` and runs during `apply_schema()` — before `ensure_bundled_providers` runs later in the lifespan path. On a fresh upgrade boot, the existing row is still named `bundled-chat`; the IN-clause catches it. On every subsequent boot the row is named `HomeLab Health AI · Chat` AND `is_bundled=TRUE`, so the WHERE doesn't match and the UPDATE is a no-op. The `is_bundled = FALSE` guard makes the statement idempotent regardless of which name is current, so the rename UPDATE in `bundled_providers.py` can safely run before or after this backfill on any given boot.

The embed and rerank rows are seeded fresh by `ensure_bundled_providers` with those three columns set.

### HF token singleton

```sql
CREATE TABLE IF NOT EXISTS hf_token_config (
    id INT PRIMARY KEY DEFAULT 1,
    token_encrypted BYTEA,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS hf_token_config_singleton_idx
    ON hf_token_config ((1));
```

Reuses the Fernet key from `services/crypto.py` (same machinery as `providers.api_key`). Falls back to cleartext if no key configured — consistent with the existing provider-key posture.

## §3 — Embedding + reranker model loading

The existing `model_puller.pull_model` is built around single-file GGUF downloads for llama.cpp. Embedding and reranker models are multi-file HF-safetensors repositories — they don't fit the puller's shape without significant rework.

**Decision: infinity-emb loads its own models from HuggingFace on first sidecar boot.** This means:
- `hlh_infer` runs with `MODEL_NAMES="BAAI/bge-m3;BAAI/bge-reranker-v2-m3"` (infinity's multi-model env contract; exact var name confirmed in implementation).
- On first start the sidecar pulls from HF directly into the shared `hlh_models` volume (mounted at `/app/models` inside the infinity container).
- If HF token is configured (§5), it's passed to the sidecar as `HF_TOKEN` env. bge-m3 and bge-reranker-v2-m3 are NOT gated, so token isn't strictly required — but plumbing it in costs nothing and future-proofs the design.

`MODEL_REGISTRY['embed']` and `MODEL_REGISTRY['rerank']` stay `None` in this spec. Pre-pull integration with the Models panel (so operators can see embed/rerank pull progress in the UI like they do for chat) is a follow-up — **Phase 2.B**. The trade-off accepted here: first sidecar boot blocks on model download (~1-2 GB for bge-m3), surfacing only as "infinity unhealthy" in `docker ps`. Acceptable for v1; UX gap documented in §10.

If, during implementation, infinity's multi-model loader proves unreliable or its model layout conflicts with the shared volume mount, fall back to **two infinity sidecars** (`hlh_embed` + `hlh_rerank`, one model each) — same image, different env. Document the choice in §10 follow-ups.

## §4 — Auto-binding (lifespan + tier change)

A single helper `apply_bundled_bindings(conn, tier)` handles all of this. It is called from two places:
- **`main.py` lifespan**, after `ensure_bundled_providers(conn)` (i.e. every boot)
- **`PUT /api/system/profile`** in `routers/system.py`, after a successful tier save (so the rewrite happens immediately when the operator changes tier — not deferred to the next boot)

The helper's body (tier ≠ external):

1. **Global embedding binding** (always rewrite — embedding is never overridable per non-goals):
   ```sql
   INSERT INTO global_settings (key, value) VALUES ('embedding_provider_id', :embed_provider_id)
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
   INSERT INTO global_settings (key, value) VALUES ('embedding_model', 'BAAI/bge-m3')
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
   ```
   The model id `BAAI/bge-m3` is what infinity advertises and what the embedding probe sends as the `model` field.

2. **Global reranker binding** — same pattern: `reranker_provider_id` + `reranker_model = 'BAAI/bge-reranker-v2-m3'`. Always rewritten.

3. **Workspace chat binding** — rewrite all bundled-chat-bound workspaces, not just the initial-migration case:
   ```sql
   UPDATE workspaces
      SET model = :tier_chat_model
    WHERE provider_id = :chat_provider_id;

   UPDATE workspaces
      SET provider_id = :chat_provider_id, model = :tier_chat_model
    WHERE provider_id IS NULL;
   ```
   Mental model: **a workspace bound to the bundled chat provider is choosing the *bundle*, not a specific *current model*.** When the tier rolls the bundle's chat model, the binding follows. Workspaces bound to an external (non-bundled) provider keep their explicit model — the operator picked specifically; respect that.

   **Both UPDATEs are required.** A consolidated single-statement form using `provider_id IN (SELECT id FROM providers WHERE is_bundled = TRUE AND role = 'chat')` does NOT subsume the `IS NULL` case — `provider_id IN (…)` evaluates to NULL (treated as false) when `provider_id IS NULL`. If you want one statement, the predicate must be explicitly `provider_id IN (…) OR provider_id IS NULL`, but then the SET clause needs to conditionally set `provider_id` only when it's currently NULL (otherwise the IN-matched rows get their FK rewritten to the same UUID for no reason — harmless but wasteful, and harder to read). The two back-to-back UPDATEs as written above are the simpler implementation.

4. **External tier**: helper is a no-op. Bundled providers aren't seeded; legacy embedding/reranker pickers remain accessible (see §6).

The exact "tier chat model" written into `workspaces.model` is whatever the `hlh_chat` server advertises at `/v1/models`. Implementation step: after `hlh_chat` is healthy, fetch `/v1/models`, take the first id, write that. If `hlh_chat` is unhealthy when `apply_bundled_bindings` runs, the workspace UPDATE is skipped for this invocation (no row gets a stale value); the next boot's lifespan call retries.

### Boundary cases pinned

- **Custom `workspaces.model` override on a bundled-chat-bound workspace.** The schema's `workspaces_provider_model_paired` CHECK constraint permits a non-NULL `model` whenever `provider_id` is non-NULL, regardless of whether the provider is bundled. So nothing prevents an operator from PATCHing a custom model name while still pointing at the bundled chat provider. **On tier change, that override is reset to the new tier's chat model.** Rationale: override-on-bundled is a corner case, and "I switched tiers and my model didn't update" is more surprising than "I switched tiers and my override got blown away" — especially since the operator can re-set the override after the fact.
- **Tier change while a chat is mid-stream.** The bound `workspaces.model` updates atomically when the tier-save handler runs. An in-flight chat completion request already has the model name baked in at request time (it was resolved from the workspace row when `routers/chats.py` initiated the upstream stream) — that stream finishes on whatever model it started with. Subsequent new chats use the new model. No special handling required; documented here so it's not filed as a bug.

## §5 — HF token service + API

### Service (`backend/services/hf_token.py`)

```python
async def get(conn) -> str | None: ...           # decrypts; returns None if no row
async def set(conn, token: str) -> None: ...     # encrypts; upserts single row
async def clear(conn) -> None: ...               # DELETE
async def masked(conn) -> str | None: ...        # returns 'hf_…XXXX' (last 4) or None
```

### API (`backend/routers/system.py`)

```
GET    /api/system/hf-token  → { configured: bool, masked: str | null, updated_at: iso | null }
PUT    /api/system/hf-token  body { token: string }  → 204
DELETE /api/system/hf-token                          → 204
```

Validates token shape (`hf_` prefix, alphanumeric, length within HF norm) before storing — rejects empty / whitespace-only.

### Model puller integration

`_hf_headers()` becomes `async def _hf_headers(pool_or_conn) -> dict[str, str]`. Signature matches the existing helpers in `model_puller.py` (`_read_row`, `_mark_pulling`, `_update_bytes`, `_mark_finished`) that accept either a pool or a bare connection via the module's `_get_conn` async-context helper. Resolution order:
1. DB-stored token via `hf_token.get(conn)` — implementation acquires a brief connection via `async with await _get_conn(pool_or_conn) as conn:`
2. `HF_TOKEN` env var (legacy fallback)
3. No header

The single call site in `pull_model()` already has `pool_or_conn` in scope — it's the function's first argument. The change is mechanical: `headers = await _hf_headers(pool_or_conn)` replaces `headers = _hf_headers()`. No new plumbing required.

## §6 — UI changes

### Settings → System (`SystemTab.jsx`)

- Tier picker: unchanged.
- **New `HfTokenField` above `ModelsPanel`**:
  - Label: "HuggingFace token"
  - Help text: "Required for MedGemma (gated). Paste your HuggingFace read token."
  - If `configured: true`: shows masked value (`hf_…XXXX`) + last-updated timestamp + `Edit` button (reveals password input + Save/Cancel) + `Clear` button.
  - If `configured: false`: shows password input with placeholder "Paste HF Token Here" + Save button.
  - **"Show me how" `<details>` disclosure** below the input, collapsed by default. Expands to a numbered walkthrough:
    1. Sign in (or sign up) at <a href="https://huggingface.co/join" target="_blank" rel="noopener noreferrer">huggingface.co/join</a>.
    2. Visit <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer">huggingface.co/settings/tokens</a> and click **Create new token**.
    3. Pick **Read** access. Name it anything (e.g. `homelabhealth`).
    4. Copy the token (starts with `hf_`) and paste it above. Click **Save**.
    5. *For MedGemma (or any gated model)*: open the model page (e.g. <a href="https://huggingface.co/google/medgemma-4b-it" target="_blank" rel="noopener noreferrer">google/medgemma-4b-it</a>) while signed in, then click **Agree and access repository**. Pulls won't work until both the token AND the license click are done.
  - Copy lives in the JSX as plain strings (no separate i18n file — project doesn't have one).
- Models panel: unchanged. Still chat-only (per §3, embed/rerank are loaded by `hlh_infer` directly). Add a small footer note: "Embedding + reranker models load automatically on first stack boot."

### Settings → Embedding

Replace the existing picker with a **read-only status card** when tier ≠ external:

```
Embedding model
bge-m3 (1024-dim) via HomeLab Health AI · Embed
Last verified: 2026-05-22 18:42 — ok
```

If tier = external, fall back to the existing picker (legacy behavior preserved for the `external` tier).

### Settings → Reranker

Same pattern — read-only card when tier ≠ external; existing picker when tier = external.

### Settings → Workspace

- Default state: chat provider shows as "HomeLab Health AI". No model picker, no provider dropdown.
- Below the read-only chat-provider line, an **"Change chat provider (advanced)"** disclosure (`<details>` element — no modal).
- Expanding the disclosure:
  1. Shows an inline warning card with destructive-styled border:
     > **Switching off HomeLab Health AI for chat**
     >
     > You'll need to keep an external chat endpoint reachable. Embeddings and reranking will still run on the bundled stack — only chat changes.
  2. Below the warning, the existing provider+model picker (filtered to `is_bundled=FALSE`).
  3. A `Save` button PATCHes the workspace with the chosen provider+model. Cancel reverts the disclosure to collapsed.
- When the workspace is currently on an external provider, a "Restore HomeLab Health AI default" button appears at the top of the tab — PATCHes back to the bundled chat provider + current tier's chat model.

### Settings → Providers

- Rows with `bundle_group IS NOT NULL` are **grouped** by `bundle_group` value (currently only `'homelab-health-ai'`). The group renders as one logical entry labeled "HomeLab Health AI" with an expand chevron — expanding it shows the three internal rows (chat/embed/rerank) read-only.
- All three bundled rows render with a 🔒 (or lock icon component) and the help text "Bundled by the homelabhealth stack — not editable." `Save` and `Delete` buttons are disabled.
- **`Test` button is role-aware.** The existing `POST /api/providers/{id}/test` in `routers/providers.py:317` only probes `GET /v1/models`, which works for chat but is meaningless for embed/rerank (and in fact returns 501 against `hlh_chat`'s llama.cpp server when something pointed at the wrong sidecar — the exact 501 that triggered this whole redesign). Test now branches on the row's `role`:
  - **`role IS NULL` or `role = 'chat'`**: existing behavior — `GET {base_url}/v1/models`, expect 200 + a `data` list. Used by external providers and the bundled chat row.
  - **`role = 'embed'`**: `POST {base_url}/v1/embeddings` with body `{"model": <stored model id>, "input": ["test"]}`. Expect 200 with `data[0].embedding` of length 1024. Report dimension mismatch as `"error: embedding dim mismatch: expected 1024, got <N>"` (matches the existing wire-contract string from CLAUDE.md).
  - **`role = 'rerank'`**: `POST {base_url}/rerank` with body `{"model": <stored model id>, "query": "test", "documents": ["a", "b"]}`. Expect 200 with a `results` array.
  - The model id sent in the body for embed/rerank tests comes from `global_settings.embedding_model` / `reranker_model` (which auto-bind populates per §4). If unset, the test falls back to the bundled defaults `BAAI/bge-m3` / `BAAI/bge-reranker-v2-m3`.
- External rows (`bundle_group IS NULL`) render as individual entries with the existing editable controls. The Test button on external rows continues to hit `/v1/models` (chat-style probe) — same as today; we don't try to guess what an external provider can do.

### Settings → Workspace — chat-provider picker filter

When the advanced override disclosure is expanded, the provider dropdown filters via:
```
is_bundled = FALSE OR role = 'chat'
```
External providers always appear (their `role` is `NULL` meaning general-purpose; we assume the operator knows their external endpoint serves chat). Bundled embed/rerank rows are excluded.

### Spec error strings

The existing wire-contract strings from CLAUDE.md (`"No provider configured for this workspace. …"`, `"Embedding model not configured. …"`) remain valid but are now **unreachable** for tier ≠ external because everything is auto-bound. For tier = external they still apply (legacy picker remains).

## §7 — Server-side immutability enforcement

In `routers/providers.py`:
- `PATCH /api/providers/{id}`: 403 `"Bundled providers are not editable. Adjust hardware tier in Settings → System."` if target row has `is_bundled=TRUE`.
- `DELETE /api/providers/{id}`: same 403.
- `POST /api/providers/{id}/test`: still allowed (read-only, useful for diagnostics).

Defense in depth — UI hides controls but server enforces.

## §8 — Files touched

Backend
- `backend/schema.sql` — new `hf_token_config` table; add `providers.is_bundled` + `providers.role` + `providers.bundle_group` columns; backfill UPDATE for existing `bundled-chat` row.
- `backend/services/bundled_providers.py` — rename; seed three rows (chat/embed/rerank) with `is_bundled=TRUE`, `role`, `bundle_group='homelab-health-ai'`; expose unified `ensure_bundled_providers(conn)`; new `apply_bundled_bindings(conn, tier)` helper used by both lifespan AND tier-save handler.
- `backend/services/hf_token.py` — new module (get/set/clear/masked).
- `backend/services/model_puller.py` — async `_hf_headers(conn)`. `MODEL_REGISTRY` expansion for embed + rerank deferred to Phase 2.B (per §3).
- `backend/services/rag.py` (audit only) — confirm embedding + rerank resolution still flows through `provider_client.resolve_*` against the new bundled rows.
- `backend/routers/system.py` — three new `/api/system/hf-token` endpoints; `PUT /api/system/profile` calls `apply_bundled_bindings(conn, new_tier)` after a successful tier save.
- `backend/routers/providers.py` — 403 for PATCH/DELETE on `is_bundled` rows; GET response includes `is_bundled`, `role`, `bundle_group`; `POST /providers/{id}/test` branches on `role` (chat → `/v1/models`, embed → `/v1/embeddings` 1024-dim probe, rerank → `/rerank` 2-doc probe) per §6.
- `backend/routers/workspaces.py` — on create, default `provider_id`/`model` to bundled chat when tier ≠ external.
- `backend/main.py` — lifespan calls `ensure_bundled_providers` then `apply_bundled_bindings` (same path as tier-save handler).

Frontend
- `frontend/src/api/system.js` — `getHfToken`, `putHfToken`, `deleteHfToken`.
- `frontend/src/api/providers.js` — surface `is_bundled` in the response type.
- `frontend/src/components/settings/SystemTab.jsx` — `HfTokenField` component above `ModelsPanel`.
- `frontend/src/components/settings/EmbeddingTab.jsx` — read-only card when tier ≠ external.
- `frontend/src/components/settings/ReRankerTab.jsx` (or equivalent path) — read-only card when tier ≠ external.
- `frontend/src/components/settings/WorkspaceTab.jsx` — chat-provider readonly + advanced override flow.
- `frontend/src/components/settings/ProvidersTab.jsx` — render bundled rows as locked.

Docker / config
- `docker-compose.yml` — add `hlh_infer` service. Pin `michaelfeil/infinity` to a specific tag (TBD in implementation). Compose profile renamed from `chat` to `bundled`.
- `.env.example` — rename `COMPOSE_PROFILES=chat` → `COMPOSE_PROFILES=bundled`. Document `HLH_INFER_PORT=9611`.

Scripts
- `backend/scripts/verify_hf_token.sh` — new.
- `backend/scripts/verify_bundled_immutability.sh` — new.
- `backend/scripts/verify_phase1_e2e.py` — update for "HomeLab Health AI · Chat" name and is_bundled.
- `backend/scripts/verify_embedding_reranker_settings.sh` — update expectations (read-only card for tier ≠ external; legacy picker still tested for external tier).

Docs
- `docs/roadmap.md` — record acceleration of Phase 2.A; flag bge-m3/bge-reranker filename verification follow-up.
- `docs/phase-1-design.md` — supplementary note pointing at this spec for the post-Phase-1 reshape.
- `README.md` — single line under setup: "**First boot:** the embedding sidecar (`hlh_infer`) downloads model weights from HuggingFace on first start. Expect 5–15 minutes before chat works end-to-end; the container restart-loops as healthy until the pull finishes."

## §9 — Verification (no test runner per CLAUDE.md)

`backend/scripts/verify_hf_token.sh`
- PUT a token; GET returns `configured: true` + masked.
- Confirm the model puller sends `Authorization: Bearer …` (mock HF endpoint).
- DELETE; GET returns `configured: false`.
- Token validation: PUT empty string → 400.

`backend/scripts/verify_bundled_immutability.sh`
- After lifespan boots, GET `/api/providers` returns three rows with `is_bundled: true`, `role` populated (`chat`/`embed`/`rerank`), and `bundle_group: "homelab-health-ai"`.
- PATCH any → 403 with the specified message.
- DELETE any → 403.
- POST `/api/providers/{id}/test` → 200 (still allowed).

`backend/scripts/verify_tier_change_rewrite.sh`
- Seed a workspace bound to the bundled chat provider with the cpu-min chat model.
- PUT `/api/system/profile` to switch tier from cpu-min → cpu-std.
- After the response, GET the workspace: `model` is now the cpu-std chat model id, not the cpu-min one.
- Repeat with a workspace bound to a non-bundled provider: its `model` is unchanged.
- Repeat with a workspace where the operator PATCHed a custom model on a bundled-chat binding: the override is reset to the new tier's chat model (boundary case per §4).

Manual UI smoke
- Boot stack with tier=cpu-min.
- Settings → System: confirm tier saved; pull Qwen3 chat (no token needed). Wait for `hlh_infer` to become healthy — first boot pulls bge-m3 + bge-reranker-v2-m3 from HF directly (one-time ~1-2 GB, no token needed).
- Settings → Embedding: read-only card showing bge-m3 / 1024-dim.
- Settings → Reranker: read-only card showing bge-reranker-v2-m3.
- Settings → Workspace: chat shows "HomeLab Health AI" with no picker.
- Settings → Workspace → Change chat provider (advanced): warning + picker reveals; dropdown excludes bundled embed/rerank rows.
- Settings → Providers: one grouped entry "HomeLab Health AI" that expands to three locked rows.
- Settings → System → HF Token: paste a token, save, refresh, see masked. Expand "Show me how" and confirm the 5-step walkthrough renders.
- Switch tier cpu-min → cpu-std in Settings → System; confirm workspaces bound to the bundled chat provider now show the cpu-std chat model in Settings → Workspace (without needing a re-save).
- Trigger a MedGemma pull (gated): observe progress; confirm 401 path surfaces correctly if token wrong.

## §10 — Known limitations and follow-ups

- **Models panel doesn't track embed/rerank pulls** (per §3). Operators only see chat-model pull progress; embed/rerank "appear" healthy when `hlh_infer` finishes loading. Phase 2.B follow-up: extend the puller to handle multi-file HF-format models and surface embed/rerank pull progress in the Models panel.
- **Infinity multi-model env var name to confirm at implementation time.** §3 references `MODEL_NAMES="A;B"` as the multi-model env contract — this is a placeholder. Before adding the `hlh_infer` service to compose, run a one-off `docker run --rm michaelfeil/infinity:<chosen-tag> --help` against the chosen image tag to confirm the actual variable / flag. If infinity has shifted to per-model env (e.g. `MODEL_ID_0`, `MODEL_ID_1`) or CLI-only multi-model, adjust the compose `command` accordingly. If multi-model isn't supported at all in the chosen tag, fall back to the two-sidecar path documented below.
- **`hlh_infer` may need a fallback to two separate sidecars** if multi-model mode in infinity is unreliable for this stack (per §3 trailing paragraph). Decision deferred to implementation; documented here.
- **Encryption falls back to cleartext** if no Fernet key configured. Same posture as `providers.api_key`; consistent, not a regression. Spec-level follow-up to require a key in production.
- **`hlh_infer` first-boot wait + healthcheck `start_period`.** The infer sidecar's healthcheck (e.g. `curl -fsS http://localhost:9611/health`) fails until infinity finishes downloading bge-m3 + bge-reranker-v2-m3 from HF. To avoid the container flapping between `health: starting` and `unhealthy` during the 5–15 min first-boot pull, set `start_period: 15m` (or higher) in the compose healthcheck. Nothing in compose `depends_on: { condition: service_healthy }` references `hlh_infer` — `hlh_api` only depends on `hlh_db: service_healthy` — so an unhealthy infer doesn't block `hlh_api` startup; instead, API calls into embed/rerank surface as connection refused / 5xx in the UI until the sidecar comes up. Same pattern as `hlh_chat`'s Phase 1 dynamic; README documents the wait.
- **Reranker bound to chat sidecar by historical mis-config** (currently in `global_settings`). The auto-bind rewrites this on next lifespan; no manual cleanup required.
- **Single embedding model across all tiers** — bge-m3 isn't ideal for low-RAM CPU-min hardware, but per non-goal §0 we're not parameterizing the vector dim, and bge-m3 is the only 1024-dim option already used. Operators on cpu-min will see slow ingest but it works.

## §11 — Rollout

This change supersedes the Phase 1 design's deferral of embed/rerank bundling. After merge:

1. **Schema apply** (idempotent on lifespan): adds `providers.is_bundled`, `providers.role`, `providers.bundle_group`, and the `hf_token_config` table. Backfill UPDATE tags the existing `bundled-chat` row.
2. **Provider seeding**: lifespan upgrade renames `bundled-chat` → `HomeLab Health AI · Chat` (preserving UUID; `role='chat'`, `bundle_group='homelab-health-ai'`), and adds two new bundled rows for embed + rerank.
3. **`apply_bundled_bindings`**: lifespan invokes it once. This always rewrites global embedding + reranker bindings to the bundled rows, and rewrites `workspaces.model` for every workspace bound to a bundled chat provider — including the historically mis-bound reranker (whose `global_settings` rows point at the chat sidecar) and any workspace whose model has drifted from the current tier.
4. **No data migration steps required beyond what `schema.sql` does on startup.** All transforms run idempotently as part of the lifespan path.
5. **Documentation**: README gains the first-boot wait note; roadmap records the Phase 2.A acceleration; phase-1-design.md gains a back-reference to this spec.
