# Providers and API Keys — Design

**Date:** 2026-05-21
**Status:** Shipped (v0.2.0). Historical design reference.
**Owner:** samkintop

## Goal

Replace the inline `OPENAI_API_KEY` env-var helper (duplicated in 4 files) and the env-var-only URL/model config with a DB-backed, UI-managed, multi-provider system modeled on OpenWebUI:

- A single shared list of OpenAI-compatible **providers** (name + base URL + optional API key).
- Per-provider **model discovery** via `/v1/models`.
- **Per-workspace** chat model selection: any model from any enabled provider.
- **One global** embedding model selection (provider + model).
- **One global** reranker model selection (provider + model, optional — `NULL` falls back to flashrank).
- Auth header (`Authorization: Bearer …`) flows through a single shared resolver for **all six** call sites (inference, chat title, memory summarization, pruning, embeddings, reranker) — closing the gap where embeddings and reranker currently ignore auth entirely.

## Non-goals (v1)

- Switching embedding models to a different vector dimension. `source_chunks.embedding` and `memory_entries.embedding` are hard-typed `vector(1024)`. The probe rejects non-1024 models with a clear error. Re-embedding existing data is a future migration.
- Per-chat model override (workspace-level is enough for now).
- Auto-detection of model capability. Embedding and reranker pickers are explicit; chat models are simply all discovered models.
- Test harness. The project has no test runner (CLAUDE.md); verification is a curl checklist (see §9).

## §1 — Data model

All schema changes are idempotent and additive (compatible with `schema.sql` being re-applied on every startup).

### New table

```sql
CREATE TABLE IF NOT EXISTS providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    api_key TEXT,                              -- NULL = no Authorization header sent
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    last_verified_at TIMESTAMPTZ,
    last_verified_status TEXT,                 -- 'ok' | 'error: <truncated msg, 200 char max>'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS providers_enabled_sort_idx
    ON providers (enabled, sort_order, created_at);
```

### Workspace changes

```sql
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS provider_id UUID REFERENCES providers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS workspaces_provider_id_idx
    ON workspaces (provider_id);

-- Pre-clean existing rows before the CHECK is added (drop-cold upgrade).
UPDATE workspaces
   SET model = NULL
 WHERE provider_id IS NULL
   AND model IS NOT NULL
   AND model <> '';

ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_provider_model_paired
    CHECK ((provider_id IS NULL AND (model IS NULL OR model = ''))
        OR (provider_id IS NOT NULL AND model IS NOT NULL AND model <> ''));
```

Adding the CHECK constraint must be guarded so re-running `schema.sql` doesn't error if the constraint is already present:

```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'workspaces_provider_model_paired'
    ) THEN
        ALTER TABLE workspaces
            ADD CONSTRAINT workspaces_provider_model_paired
            CHECK ((provider_id IS NULL AND (model IS NULL OR model = ''))
                OR (provider_id IS NOT NULL AND model IS NOT NULL AND model <> ''));
    END IF;
END $$;
```

`workspaces.model` keeps its existing `TEXT` shape. The pair `(provider_id, model)` is the resolvable identifier for chat routing.

### `global_settings` keys (no schema change to the table)

`global_settings` stays `(key TEXT PRIMARY KEY, value TEXT NOT NULL)`. Four new keys (and one or both for embedding/reranker may simply be absent → "not configured"):

| Key                      | Value                  | Notes |
|--------------------------|------------------------|-------|
| `embedding_provider_id`  | UUID string            | Absent = embeddings disabled (hard-fail at runtime) |
| `embedding_model`        | model id string        | Must match a model exposed by the embedding provider |
| `reranker_provider_id`   | UUID string            | Absent = use `flashrank` fallback |
| `reranker_model`         | model id string        | Absent = use `flashrank` fallback |

Reads use `SELECT value FROM global_settings WHERE key = $1`. Writes use the existing upsert pattern. A "clear" operation on either pair deletes both rows in one transaction.

### Resolved decisions

1. `api_key` is **nullable**. `NULL` = no `Authorization` header. **Empty string is invalid** — rejected at the API layer.
2. `UNIQUE(name)` on providers. Two providers with the same `base_url` are allowed as long as `name` differs (e.g. an OpenRouter key for chat and a separate OpenRouter key for embeddings — possible if you choose).
3. **Plain text in DB by default**, with **optional app-level AES-256-GCM** keyed by `PROVIDER_KEY_ENCRYPTION_KEY` env var. See §2. The DB column stores ciphertext-prefixed values (`enc:v1:…`) when encryption is active. UI never returns the secret — always redacted `"***"` if set, `null` if unset.
4. `ON DELETE SET NULL` on `workspaces.provider_id`. The delete endpoint requires `?force=true` if any workspace or `global_settings.{embedding,reranker}_provider_id` references the provider; without force → `409` with dependency counts (see §3 for body shape). With force, in a single transaction: (a) clear referencing `global_settings` rows; (b) `UPDATE workspaces SET provider_id = NULL, model = NULL WHERE provider_id = <id>` — nulls **both** columns in one statement so the `workspaces_provider_model_paired` CHECK stays satisfied at every intermediate state (a two-step variant that nulls only `model` first would itself violate the CHECK because `provider_id` is still set); (c) `DELETE FROM providers WHERE id = <id>` (the `ON DELETE SET NULL` cascade is then a no-op because `provider_id` is already NULL).
5. `vector(1024)` stays hard-coded. Embedding-model probe rejects non-1024 with the exact string: `embedding dimension mismatch: expected 1024, got <N>`.
6. Ordering tiebreaker everywhere: `ORDER BY sort_order ASC, created_at ASC`.
7. `last_verified_at` / `last_verified_status` updated **only** by the explicit test endpoint (§3). Never auto-probed.

## §2 — Crypto module (`backend/services/crypto.py`)

Adds the `cryptography` package to `backend/requirements.txt`. Exposes two functions:

```python
ENC_PREFIX = "enc:v1:"

def encrypt_secret(plaintext: str | None) -> str | None
def decrypt_secret(stored: str | None) -> str | None
```

### Behavior

- `_key()`: reads `PROVIDER_KEY_ENCRYPTION_KEY` (32 raw bytes, base64-encoded). Returns `None` if unset. Raises `RuntimeError` if set but not 32 bytes after base64 decode.
- `encrypt_secret(plaintext)`:
  - `None` in → `None` out.
  - No key configured → returns `plaintext` unchanged (passthrough; ciphertext writers can be added later without DB rewrite).
  - Key configured → `nonce = os.urandom(12)`, AES-256-GCM encrypt, returns `ENC_PREFIX + base64(nonce || ct)`.
- `decrypt_secret(stored)` — **hardened per §0 follow-up #7**:
  - `None` → `None`.
  - Does not start with `ENC_PREFIX` → return `stored` unchanged (legacy plaintext).
  - Starts with `ENC_PREFIX`:
    - Strip prefix, attempt `base64.b64decode(..., validate=True)`.
    - On `binascii.Error` (invalid base64) → return `stored` unchanged (treat as plaintext that happens to begin with the prefix; do **not** raise).
    - Decoded length < 13 (need ≥ 12 nonce + ≥ 1 ciphertext byte) → return `stored` unchanged.
    - Otherwise: if no key configured → `RuntimeError("encrypted secret found but PROVIDER_KEY_ENCRYPTION_KEY unset")`.
    - With key: `AESGCM(key).decrypt(blob[:12], blob[12:], None)`. On `InvalidTag` → `RuntimeError("provider api_key decrypt failed: invalid tag (wrong key or corruption)")`. On success → decoded UTF-8 string.

### Logging discipline

- `crypto.py` never logs plaintext, ciphertext, key bytes, or nonces.
- Any module that calls `decrypt_secret` must not log the return value. If a debug log needs to indicate "key is present", log `bool(decrypted)` only.

## §3 — Providers CRUD (`backend/routers/providers.py`)

FastAPI `APIRouter`, mounted under `/api/providers`. All endpoints `Depends(require_admin)`.

### Endpoints

| Method | Path                              | Body                                              | Returns                                                                                  |
|--------|-----------------------------------|---------------------------------------------------|------------------------------------------------------------------------------------------|
| GET    | `/api/providers`                  | —                                                 | List of providers, ordered `sort_order, created_at`. `api_key` redacted (`"***"`/`null`). |
| GET    | `/api/providers/{id}`             | —                                                 | Single provider, redacted.                                                               |
| POST   | `/api/providers`                  | `{name, base_url, api_key?, enabled?, sort_order?}` | Created provider, redacted. `201`.                                                       |
| PATCH  | `/api/providers/{id}`             | partial — see semantics below                     | Updated provider, redacted.                                                              |
| DELETE | `/api/providers/{id}?force=true`  | —                                                 | `204` on success; `409` with `{detail: "provider in use", references: {workspaces: N, embedding: bool, reranker: bool}}` if `force` absent and refs exist. |
| POST   | `/api/providers/{id}/test`        | —                                                 | `{ok: bool, status: string, models?: string[]}`                                          |
| GET    | `/api/providers/{id}/models`      | —                                                 | `{data: [{id: string, ...}]}` — live `/v1/models` proxy, no DB cache, 10s timeout.       |

### DELETE semantics

- Compute references: `SELECT COUNT(*) FROM workspaces WHERE provider_id = $1` and check `global_settings` for `embedding_provider_id` / `reranker_provider_id` matches.
- If all zero/false → straight `DELETE`, return `204`.
- If any reference exists and `?force` is absent/falsy → `409` with body `{"detail": "provider in use", "references": {"workspaces": <int>, "embedding": <bool>, "reranker": <bool>}}`.
- With `?force=true`, in a single transaction:
  1. `DELETE FROM global_settings WHERE key IN ('embedding_provider_id', 'embedding_model')` **only if** `embedding_provider_id` matched the target.
  2. Same for reranker keys.
  3. `UPDATE workspaces SET provider_id = NULL, model = NULL WHERE provider_id = $1` — nulls both columns at once so the `workspaces_provider_model_paired` CHECK is satisfied at every intermediate state. (A two-step variant nulling only `model` first would itself violate the CHECK because `provider_id` is still set; the constraint is not deferrable.)
  4. `DELETE FROM providers WHERE id = $1` — the `ON DELETE SET NULL` cascade is then a no-op (rows are already NULL).
- Return `204` on success.

### PATCH semantics for `api_key`

- Key **absent** from request body → leave DB value unchanged.
- `api_key: null` → clear the stored value (`UPDATE providers SET api_key = NULL`).
- `api_key: "<non-empty>"` → encrypt via `encrypt_secret` and replace.
- `api_key: ""` → reject with `400 api_key cannot be empty string; send null to clear or omit to keep`.

`updated_at` is set to `NOW()` on every PATCH that mutates anything.

### POST `/test` behavior

- Resolve provider, `decrypt_secret(api_key)`.
- `httpx.AsyncClient(timeout=httpx.Timeout(5.0))` → `GET {base_url}/v1/models` with `Authorization: Bearer <key>` if key set.
- On HTTP 2xx and JSON-parseable response with a list at `data`:
  - `UPDATE providers SET last_verified_at = NOW(), last_verified_status = 'ok' WHERE id = $1`.
  - Return `{ok: true, status: "ok", models: [m["id"] for m in data["data"] if isinstance(m, dict)]}`.
- On any failure (network, non-2xx, malformed JSON):
  - `status = f"error: {short_msg}"` truncated to 200 chars.
  - `UPDATE providers SET last_verified_at = NOW(), last_verified_status = $1 WHERE id = $2`.
  - Return `{ok: false, status}`. Always HTTP 200 (this is a probe result, not a request failure).

### GET `/models` behavior

- Resolve provider, decrypt key.
- `httpx.AsyncClient(timeout=httpx.Timeout(10.0))` → `GET {base_url}/v1/models`.
- On success: return the upstream JSON body verbatim. On any failure: `502` with `{detail: f"upstream models fetch failed: {short_msg}"}`. No DB write here (only `/test` writes).

### Redaction rule

Helper used by all return shapes:

```python
def _redact_provider(row) -> dict:
    out = dict(row)
    out["api_key"] = "***" if out.get("api_key") else None
    return out
```

Verified by a grep in §9: no endpoint returns a value of `api_key` other than `"***"` or `null`.

## §4 — Shared resolver (`backend/services/provider_client.py`)

Replaces the four duplicated `_openai_headers()` / `_inference_base()` helpers.

### Public surface

```python
@dataclass(frozen=True)
class Provider:
    id: UUID
    name: str
    base_url: str          # already rstrip('/')
    api_key: str | None    # plaintext after decrypt_secret
    enabled: bool

async def resolve_provider(provider_id: UUID) -> Provider:
    """Fetch + decrypt. Raises HTTPException(404) if not found, 409 if disabled."""

async def resolve_provider_for_workspace(workspace_id: UUID) -> tuple[Provider, str]:
    """Returns (provider, model). Raises HTTPException(400) with the user-facing
    message 'No provider configured for this workspace. Open Settings → Workspace
    to pick one.' if workspaces.provider_id is NULL."""

async def resolve_embedding_provider() -> tuple[Provider, str]:
    """From global_settings. Raises EmbeddingError with 'Embedding model not
    configured. Set one in Settings → Embedding.' if absent."""

async def resolve_reranker_provider() -> tuple[Provider, str] | None:
    """From global_settings. Returns None if absent (caller uses flashrank fallback)."""

def build_headers(provider: Provider, extra: dict | None = None) -> dict:
    h = {"Content-Type": "application/json", **(extra or {})}
    if provider.api_key:
        h["Authorization"] = f"Bearer {provider.api_key}"
    return h
```

### Call sites to migrate

1. `backend/routers/inference.py` — `/api/inference/models`, `/api/inference/chat`. Inference base + headers now come from the workspace's provider (or — for the `/models` listing — from a `provider_id` query param). The current global `INFERENCE_URL` env-var path goes away. `DEFAULT_MODEL` env var and its `RuntimeError` path are **deleted entirely**.
2. `backend/routers/chats.py` — `_openai_short_chat_title` resolves the workspace provider for the chat being titled.
3. `backend/routers/memory.py` — resolves the workspace provider (the same one used for chat).
4. `backend/services/pruning.py` — pruning summarizer resolves the workspace provider for the chat being pruned.
5. `backend/services/embeddings.py` — **new auth**. Reads `global_settings.embedding_provider_id` + `embedding_model` once per call, builds headers via `build_headers`. `EMBEDDING_URL` and `EMBEDDING_MODEL` env vars deleted. `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_TIMEOUT`, `EMBEDDING_QUERY_INSTRUCTION` stay (pipeline config, not provider config). **Path change:** `services/embeddings.py:32` currently calls `f"{EMBEDDING_URL}/embeddings"`; it becomes `f"{provider.base_url}/v1/embeddings"` to match the spec's probe path and OpenAI / OpenRouter / most OpenAI-compatible servers. If a target server only mounts the older `/embeddings` (no `/v1` prefix), the connection test in §3 surfaces the mismatch before any embed call is attempted.
6. `backend/services/rag.py` (reranker section only) — **new auth**. Reads `global_settings.reranker_provider_id` + `reranker_model`. `RERANKER_URL` env var deleted. `RERANKER_MODEL` (default) and `RERANKER_TIMEOUT` stay as fallback defaults if `reranker_model` global setting is somehow set without a value (defensive).

After migration, a grep across `backend/` must show **zero** occurrences of `OPENAI_API_KEY`, `INFERENCE_URL`, `EMBEDDING_URL`, `RERANKER_URL`, or `DEFAULT_MODEL` (other than the one-shot deprecation warning in §7).

### Inference `/models` listing

Old: single global `/api/inference/models` proxies `INFERENCE_URL/v1/models`.
New: that endpoint accepts `?provider_id=<uuid>` and proxies that provider's `/v1/models`. The frontend uses this to populate the workspace chat-model dropdown. (Same shape and timeout as `GET /api/providers/{id}/models` — could be the same handler under the hood.)

## §5 — Embedding + reranker selection endpoints (`backend/routers/settings.py`)

Mounted under `/api/settings`.

### GET `/api/settings/embedding`

```json
{
  "provider_id": "uuid-or-null",
  "model": "string-or-null",
  "dimension": 1024
}
```

### PUT `/api/settings/embedding`

Body: `{provider_id: uuid|null, model: string|null}`. Validation:

- Both `null` → delete both rows from `global_settings` (disable embeddings). Returns `200` with the resulting (null) state.
- Exactly one null → `400 provider_id and model must both be set or both null`.
- Both non-null → **probe**:
  - Resolve provider, decrypt key.
  - `POST {base_url}/v1/embeddings` body `{"model": <model>, "input": ["probe"]}`.
  - Read `len(data[0].embedding)`.
  - If `len != 1024` → `400 embedding dimension mismatch: expected 1024, got <N>`. **Exact string**, used by frontend to render a clear error and by the §9 verification step.
  - On other probe failure → `502 embedding probe failed: <short msg>`.
  - On success: upsert both `global_settings` rows in a single transaction.

### GET `/api/settings/reranker`

```json
{"provider_id": "uuid-or-null", "model": "string-or-null"}
```

### PUT `/api/settings/reranker`

Body: `{provider_id: uuid|null, model: string|null}`. No probe (rerank response shapes vary across vendors; surface runtime errors instead). Same both-null / both-set validation. Both null → delete both rows (fall back to flashrank).

## §6 — Frontend

All new tab components live in `frontend/src/components/settings/`. They mount inside the existing tabbed settings page at `frontend/src/pages/workspace/SettingsPage.jsx`, which already drives tabs via a local `tab` state (`typography`, `layout`, `search`, …). Three new tabs are added in the tab list and three new render branches in the tab body: `'providers'` → `<ProvidersTab />`, `'embedding'` → `<EmbeddingTab />`, `'reranker'` → `<RerankerTab />`. API client wrappers go in `frontend/src/api/` (one file per resource, matching the existing per-resource convention).

### `ProvidersTab.jsx`

- **List view**: table with columns *Name*, *Base URL* (truncated to 40 char with title attribute for full), *Key set* (Y/N), *Enabled* (checkbox toggling `PATCH /api/providers/{id}` with `enabled: bool`), *Verified* (relative time + `last_verified_status` color: green for `ok`, red for any `error: …`, gray if never tested), *Actions* (Edit / Test / Delete).
- **Add / Edit modal**: fields *Name* (required), *Base URL* (required), *API key* (password input, masked), *Enabled*, *Sort order* (integer, default 0).
  - On **Edit**: the API key field renders as `placeholder="•••••••• (leave blank to keep)"` with an empty initial value. Submitting empty omits the `api_key` field from the PATCH body (per §3 PATCH semantics). A separate **"Clear key"** button sends `api_key: null`.
  - On **Add**: the API key field is optional; submitting empty sends `api_key: null` (no header). Submitting with any non-empty value sends the literal string (the backend will encrypt at rest if configured).
- **Test** button → `POST /api/providers/{id}/test`, displays inline result (status + list of returned model ids in a collapsible).
- **Delete** button → `DELETE /api/providers/{id}`. On `409`, surface the dependency counts and re-prompt with a "Force delete (clears references)" button → retries with `?force=true`.

### Embedding picker

- Two cascading dropdowns. **Provider** lists enabled providers. **Model** is empty until a provider is picked, then populated via `GET /api/providers/{id}/models` and filtered/searchable.
- A **"Save"** button calls `PUT /api/settings/embedding`. Probe error (`400 embedding dimension mismatch: …`) renders inline beside the dropdowns.
- A **"Clear (disable embeddings)"** button calls `PUT /api/settings/embedding` with `{provider_id: null, model: null}`. Confirmation modal warns that ingestion and retrieval will fail until reconfigured.

### Reranker picker

- Identical shape to embedding picker; no probe. "Clear" reverts to `flashrank` fallback (label the clear button "Use flashrank fallback").

### Workspace chat-model picker

- Existing workspace settings UI (wherever `workspaces.model` is edited today) gains a provider dropdown + model dropdown.
- Model dropdown populated from `GET /api/providers/{id}/models` when a provider is selected.
- Saving sets both `workspaces.provider_id` and `workspaces.model` in one PATCH; the CHECK constraint enforces the pair.
- Clearing both fields is allowed (workspace has no chat model; chat send-button errors with the resolver's message).

## §7 — Migration / upgrade behavior

1. `schema.sql` re-applies on startup. The additions are idempotent (table `IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, constraint guarded by the `DO $$ IF NOT EXISTS` block, `CREATE INDEX IF NOT EXISTS`).
2. The pre-CHECK `UPDATE workspaces SET model = NULL WHERE provider_id IS NULL AND model IS NOT NULL AND model <> ''` runs on every startup (effectively a no-op after first run). Existing workspaces lose their stale model string and need to be re-pointed at a provider + model from the UI. This matches the "drop cold" upgrade choice.
3. **Lifespan startup hook** (one-shot, log-once) in `backend/main.py`:

   ```python
   _DEPRECATED_ENV_VARS = (
       "OPENAI_API_KEY", "INFERENCE_URL", "EMBEDDING_URL", "RERANKER_URL", "DEFAULT_MODEL"
   )
   set_vars = [v for v in _DEPRECATED_ENV_VARS if (os.environ.get(v) or "").strip()]
   if set_vars:
       logger.warning(
           "Deprecated env vars set and ignored: %s. "
           "Provider config now lives in Settings → Providers. "
           "Remove these from your .env to silence this warning.",
           ", ".join(set_vars),
       )
   ```

   Logged exactly once per process. No retry, no auto-action.
4. `global_settings.embedding_provider_id` / `embedding_model` start absent. Until configured, `embed_text`, `embed_batch`, and `embed_query` raise `EmbeddingError("Embedding model not configured. Set one in Settings → Embedding.")`. Ingestion endpoints and retrieval gates surface this user-facing.
5. `global_settings.reranker_provider_id` / `reranker_model` absent → reranker code uses the existing `flashrank` fallback path (already implemented in `services/rag.py`). No user-visible error.
6. `DEFAULT_MODEL` env var and its `RuntimeError` path in `backend/routers/inference.py:_default_model` are **deleted entirely**. Every place that needed a "default" now requires an explicit workspace `(provider_id, model)`.

## §8 — Order of work (with stop checkpoints)

Backup actions run as the first commands of step 1, before any edit:

```bash
# .bak files for every file we'll edit, dated
cp backend/schema.sql backend/schema.sql.bak-$(date +%Y%m%d)
# (others added per step)

# Postgres dump from inside the running stack
docker exec hlh_db pg_dump -U hlh -F c hlh > pre-providers-migration-$(date +%Y%m%d).dump
```

1. **Schema + crypto module + crypto verification scripts.**
   - Edit `backend/schema.sql` per §1 (new table, workspace column + index, pre-CHECK UPDATE, guarded CHECK).
   - Add `cryptography` to `backend/requirements.txt`.
   - Create `backend/services/crypto.py` per §2.
   - Create `backend/scripts/verify_crypto.py` — runnable script that exercises:
     - encrypt → decrypt roundtrip with no key set (passthrough).
     - encrypt → decrypt roundtrip with `PROVIDER_KEY_ENCRYPTION_KEY` set (real AES-GCM).
     - mixed plaintext + `enc:v1:…` rows (simulated) decrypt correctly.
     - `decrypt_secret("enc:v1:notbase64!!")` returns the input unchanged (hardening, no raise).
     - `decrypt_secret("enc:v1:" + b64(b"\x00" * 10))` (too short) returns input unchanged.
     - wrong key produces `InvalidTag → RuntimeError("…invalid tag…")`.
   - Bring the stack up (no migration to live DB without explicit "go"; this step only edits files).
   - **STOP. Report.** Required output: files changed (with line counts), `verify_crypto.py` invocation transcript, exact next command. Wait for "go" before step 2.

2. **Providers CRUD endpoints.**
   - Create `backend/routers/providers.py` per §3.
   - Mount in `backend/main.py`.
   - `python -m py_compile` clean.
   - Add `backend/scripts/verify_providers_crud.sh` — curl-based checklist hitting each endpoint and asserting redaction (`grep -v` over response bodies for anything that looks like a real key — see §9).
   - Report files changed + curl transcript.

3. **Connection test + live `/models` endpoints.**
   - `POST /api/providers/{id}/test` and `GET /api/providers/{id}/models` per §3.
   - Test against a known-good local provider and a deliberately-broken one (bad URL / bad key).
   - Report.

4. **Shared resolver + cutover of 6 call sites.** *(Riskiest step.)*
   - Create `backend/services/provider_client.py` per §4.
   - Migrate `inference.py`, `chats.py`, `memory.py`, `pruning.py`, `services/embeddings.py`, `services/rag.py`.
   - Delete the four `_openai_headers()` helpers, the four `_inference_base()` helpers, the `_default_model()` helper, and every read of the listed env vars.
   - `grep -RE 'OPENAI_API_KEY|INFERENCE_URL|EMBEDDING_URL|RERANKER_URL|DEFAULT_MODEL' backend/` → must return zero matches **except** the deprecation list in `main.py` and the `.env.example` documentation.
   - `python -m py_compile $(find backend -name '*.py')` clean.
   - **STOP. Report.** Wait for "go" before step 5.

5. **Embedding + reranker settings endpoints** (§5). Curl checklist exercises both dropdowns' save paths and the dim-mismatch error.

6. **Frontend providers UI** (§6 ProvidersTab) — list, add, edit, test, delete, force-delete-on-409, redaction in transit (network tab inspection).

7. **Frontend embedding + reranker pickers** — both cascading dropdowns, save, clear, error rendering.

8. **Frontend workspace provider+model picker** — wherever `workspaces.model` is edited today.

9. **Migration warning + env-var sweep** (§7 lifespan hook). Confirm the one-shot warning fires on startup with a deprecated var set, does not fire when none set, and does not repeat on subsequent requests.

10. **Final verification pass.** Walk the §9 checklist end-to-end. Report any deviation.

## §9 — Verification checklist (curl + manual)

No pytest harness. Each step produces a transcript checked into the report.

### Crypto module

```bash
# No key
unset PROVIDER_KEY_ENCRYPTION_KEY
python backend/scripts/verify_crypto.py

# Real key
export PROVIDER_KEY_ENCRYPTION_KEY=$(python -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')
python backend/scripts/verify_crypto.py
```

Expected: every assertion in the script passes; script exits 0.

### Providers CRUD

```bash
API=http://localhost:9600/api

# Create
curl -s -X POST $API/providers \
  -H 'Content-Type: application/json' \
  -d '{"name":"local-llamacpp","base_url":"http://llamacpp:8080","api_key":"sk-test-abc123"}' \
  | tee /tmp/p1.json
# Assertion: api_key in response is exactly "***", not "sk-test-abc123".
grep -q '"api_key":"\*\*\*"' /tmp/p1.json && ! grep -q 'sk-test-abc123' /tmp/p1.json

# List
curl -s $API/providers | tee /tmp/plist.json
! grep -q 'sk-test-abc123' /tmp/plist.json   # no plaintext leak

# Empty string rejected
curl -s -o /tmp/empty.json -w '%{http_code}' -X PATCH $API/providers/<id> \
  -H 'Content-Type: application/json' -d '{"api_key":""}'
# Expected: 400, body mentions "cannot be empty string"

# api_key absent on PATCH preserves existing
curl -s -X PATCH $API/providers/<id> -H 'Content-Type: application/json' -d '{"name":"renamed"}'
curl -s $API/providers/<id>   # api_key still "***"

# api_key:null on PATCH clears
curl -s -X PATCH $API/providers/<id> -H 'Content-Type: application/json' -d '{"api_key":null}'
curl -s $API/providers/<id>   # api_key is null

# DELETE without force on referenced provider → 409 with counts
curl -s -o /tmp/del.json -w '%{http_code}' -X DELETE $API/providers/<id>
# Expected: 409, body contains {workspaces: N, embedding: bool, reranker: bool}

# DELETE with force in single txn
curl -s -X DELETE "$API/providers/<id>?force=true"
# Confirm global_settings rows for embedding/reranker cleared if they pointed here
docker exec hlh_db psql -U hlh -d hlh -c \
  "SELECT key, value FROM global_settings WHERE key IN ('embedding_provider_id','reranker_provider_id');"
```

### CHECK constraint

```sql
-- Should reject both:
INSERT INTO workspaces (name, provider_id, model) VALUES ('bad1', '<uuid>', NULL);
INSERT INTO workspaces (name, provider_id, model) VALUES ('bad2', NULL, 'foo');
-- Should accept:
INSERT INTO workspaces (name, provider_id, model) VALUES ('ok1', NULL, NULL);
INSERT INTO workspaces (name, provider_id, model) VALUES ('ok2', NULL, '');
INSERT INTO workspaces (name, provider_id, model) VALUES ('ok3', '<uuid>', 'qwen3-32b');
```

### Embedding dim probe

```bash
# Configure with a 1024-dim model → 200
curl -s -X PUT $API/settings/embedding \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":"<uuid>","model":"BAAI/bge-m3"}'

# Configure with a non-1024 model → 400 with exact string
curl -s -w '\n%{http_code}\n' -X PUT $API/settings/embedding \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":"<uuid>","model":"text-embedding-3-small"}'
# Expected body contains: embedding dimension mismatch: expected 1024, got 1536
```

### Redaction sweep

```bash
# Across all provider-related endpoints, no real-looking key should appear in any response.
# Use a known-distinct test value (e.g. "sk-ZZZTESTREDACT") on every provider we create
# during verification, then grep all transcripts for that string at the end.
grep -r 'sk-ZZZTESTREDACT' /tmp/p*.json /tmp/plist.json /tmp/del.json && echo FAIL || echo PASS
```

### Env-var sweep (post step 4)

```bash
grep -RE 'OPENAI_API_KEY|INFERENCE_URL|EMBEDDING_URL|RERANKER_URL|DEFAULT_MODEL' backend/ \
  | grep -vE '(main\.py.*DEPRECATED|.env.example)'
# Expected: empty output
```

### Deprecation warning

```bash
# With one deprecated var set, expect one WARNING line in startup logs:
OPENAI_API_KEY=foo docker compose up -d --build hlh_api
docker logs hlh_api 2>&1 | grep -c 'Deprecated env vars set'
# Expected: 1

# Subsequent requests don't re-log:
curl -s $API/providers > /dev/null
docker logs hlh_api 2>&1 | grep -c 'Deprecated env vars set'
# Expected: still 1
```

### UI smoke (browser)

- Add a provider → verify saved key is masked in the form on next open.
- Test button updates the "Verified" cell with a fresh timestamp + status.
- Edit provider; submit with empty key → key preserved (re-test still passes).
- Edit provider; "Clear key" button → key cleared (re-test sees no auth header upstream, succeeds only if provider doesn't require one).
- Delete provider referenced by a workspace → 409 → confirm dependency counts → force-delete → workspace's provider dropdown reads "not configured".
- Embedding picker: pick a 1536-dim model → inline error with the exact §1.5 string.
- Workspace chat-model picker: provider A then provider B; chat sends route to the correct upstream (verified by `docker logs hlh_api` showing the right base URL in outgoing calls — only the URL, never the key).

## §10 — Out of scope (for follow-up specs)

- Re-embedding existing chunks when switching to a non-1024-dim model.
- Per-chat (not just per-workspace) model override.
- Workspace-scoped provider visibility (e.g. provider X only available to workspace Y).
- Multi-user / role-based provider visibility.
- Key rotation tooling for `PROVIDER_KEY_ENCRYPTION_KEY` (today: if you rotate, you must clear all stored keys and re-enter; documented but not automated).
