# Design: boofinity-model-pulls-rebind

**Date:** 2026-06-16

---

## C1. HF-snapshot pull path in model_puller.py

### The two pull shapes

Today every `ModelSpec` is a single-file GGUF: one
`https://huggingface.co/{repo}/resolve/{rev}/{filename}` URL streamed to a flat
`/models/{filename}` path (`_dest_path`, `pull_model`, `_FLAT_DEST_ROLES`).
boofinity needs the *whole repo* (config.json, tokenizer, multiple safetensors
shards) in the HuggingFace hub cache layout under `HF_HOME=/cache`:

```
/cache/hub/models--Qwen--Qwen3-Embedding-0.6B/snapshots/<commit>/...
/cache/hub/models--Qwen--Qwen3-Embedding-0.6B/refs/main
/cache/hub/models--Qwen--Qwen3-Embedding-0.6B/blobs/...
```

boofinity runs with `HF_HUB_OFFLINE=1`, so it never fetches: the snapshot must
exist before its first load. The fix is a second pull shape, not a rewrite of
the existing one.

### ModelSpec variant: repo-only snapshot

Add an optional `kind` discriminator to the frozen `ModelSpec` dataclass
(default `"file"`, the existing behavior). A `kind="snapshot"` spec has
`filename` unused for the download (boofinity discovers files itself) but still
needs a stable `model_id`. Today `model_id` is `f"{repo}@{filename}"`; for a
snapshot there is no single filename, so:

```python
@dataclass(frozen=True)
class ModelSpec:
    repo: str
    filename: str = ""            # "" for snapshot specs
    kind: str = "file"            # "file" | "snapshot"
    quant: str | None = None
    ...

    @property
    def model_id(self) -> str:
        if self.kind == "snapshot":
            return f"{self.repo}@snapshot"
        return f"{self.repo}@{self.filename}"
```

`_EMBED_SPEC` and `_RERANK_SPEC` change to:

```python
_EMBED_SPEC = ModelSpec(
    repo="Qwen/Qwen3-Embedding-0.6B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
    revision="main",
)
_RERANK_SPEC = ModelSpec(
    repo="Qwen/Qwen3-Reranker-0.6B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-Reranker-0.6B",
    revision="main",
)
```

Their `model_id` changes from `Qwen/Qwen3-Embedding-0.6B-GGUF@...gguf` to
`Qwen/Qwen3-Embedding-0.6B@snapshot`. Because `seed_registry` prunes any
`bundled_models` row whose `(role, tier, model_id)` is no longer in
`MODEL_REGISTRY`, the old GGUF embed/rerank rows are auto-removed at the first
boot after this change - exactly the documented prune behavior. No migration is
written for the retired rows.

`_TASKS_SPEC`, the chat specs, and the vision mmproj specs stay `kind="file"`
GGUFs on `hlh_chat` - boofinity does not serve tasks/chat/vision.

### hlh_infer_cache volume: ownership + which folder mounts it where

Two volume concerns, both owned by THIS folder (C):

1. **`hlh_api` mount.** Folder B mounts `hlh_infer_cache:/cache` into `hlh_infer`
   (boofinity, read side). The puller runs in `hlh_api`, so `hlh_api` must ALSO
   mount `hlh_infer_cache:/cache` to *write* the snapshot. **This folder (C) adds
   the `hlh_api` mount** (task C1.8); the named volume itself is declared by
   folder B. Stated plainly so a reader knows C owns the `hlh_api` side.
2. **Bootstrap ownership.** Exactly like `hlh_models` (CLAUDE.md: a populated
   named volume stays root-owned and the `read_only` uid-1000 `hlh_api` then
   gets `EACCES` writing into it), the `hlh_infer_cache` volume needs an
   idempotent chown to uid 1000. `hlh_orchestra/bootstrap.py` gains
   `ensure_infer_cache_ownership()` mirroring `ensure_models_ownership()`
   (`bootstrap.py:228-249`): a throwaway `alpine` container running
   `chown -R 1000:1000 /cache` against `hlh_infer_cache`, called from the same
   bootstrap sequence. Without it, the very first snapshot write fails with
   `EACCES` and the doctor `_check_infer_cache_writable` (C6) flags it.

### boofinity read_only cache dirs (HOME)

`hlh_infer` runs `read_only: true` (folder B). boofinity sets `HF_HOME=/cache`,
but torch/transformers may also write to `$HOME/.cache` (e.g.
`~/.cache/huggingface`, `~/.cache/torch`) for sub-caches not covered by
`HF_HOME`. On a read-only rootfs with `HOME` pointing at a non-writable path
those writes raise `EACCES` at startup. Mitigation: set `HOME=/cache` on
`hlh_infer` (so every `~/.cache/*` lands in the writable volume), or add a tmpfs
for any cache dir that must not persist. This folder notes the requirement; the
env addition is a one-line compose edit verified by a no-EACCES boot check.

### Destination: hlh_infer_cache, not /models

`_FLAT_DEST_ROLES` currently includes `embed` and `rerank` (flat
`/models/<file>`). Snapshot specs must land in the HF cache volume instead. Add
the cache root and a per-kind dispatch in `_dest_path`:

```python
INFER_CACHE_DIR = Path(os.environ.get("HLH_INFER_CACHE_DIR", "/cache"))
_FLAT_DEST_ROLES = {"chat", "tasks"}   # embed/rerank removed; they are snapshots now
```

The puller process (`hlh_api`) and boofinity (`hlh_infer`) both mount
`hlh_infer_cache` at `/cache`. The API needs the volume mounted to *write* the
snapshot; folder B mounts it into `hlh_infer` read-side. This folder adds the
same `hlh_infer_cache:/cache` mount to `hlh_api`'s service (a one-line compose
addition noted as a task; the compose service itself was authored in B).

### Download mechanism: huggingface_hub.snapshot_download

The existing puller is hand-rolled `httpx` streaming with sha256, disk
pre-flight, cancel events, and `.partial` rename. Reproducing the hub cache
layout (blobs, refs, snapshots symlinks) by hand is error-prone. Use
`huggingface_hub.snapshot_download` for snapshot specs:

```python
from huggingface_hub import snapshot_download

def _snapshot_pull(repo: str, revision: str, token: str | None) -> str:
    return snapshot_download(
        repo_id=repo,
        revision=revision or "main",
        cache_dir=str(INFER_CACHE_DIR / "hub"),
        token=token,
        local_files_only=False,
    )
```

`huggingface_hub` is already a transitive dependency (the project pins HF repos
throughout); it is added explicitly to `requirements.txt` if not already
present. `snapshot_download` is **synchronous**; run it in a thread via
`asyncio.to_thread` so it does not block the event loop while holding
`_PULL_LOCK`.

`pull_model` branches on `row`'s spec kind. The kind is not stored in
`bundled_models` today; rather than a schema change, the puller re-derives kind
by looking up the spec in `MODEL_REGISTRY` by `(role, tier, model_id)` - the
registry is the source of truth and is in-process. If the row is a snapshot
spec:

- Skip `_check_disk_space` against a single `expected_bytes` (snapshot total is
  unknown up front); log the skip like the existing `expected_bytes is None`
  path.
- Skip the sha256 single-file verification (per-file hashes are HF's job).
- Mark `pulling`, call `_snapshot_pull` in a thread, mark `ready` on success or
  `failed` with the exception text. `huggingface_hub` raises
  `GatedRepoError` / `RepositoryNotFoundError`; map a 401-equivalent to the
  same "License acceptance required" message the file path uses. Qwen3 repos are
  ungated Apache-2.0, so the gated path is defensive only.
- Honor the cancel event between this and any future multi-step work; for the
  single `snapshot_download` call, cancellation is best-effort (the call is
  atomic from our side), matching the existing "one pull at a time" contract.

`_PULL_LOCK` still serializes: a snapshot pull and a GGUF pull never run
concurrently, preserving the single-writer invariant.

### Progress reporting

`snapshot_download` does not stream per-byte progress back through our
`_update_bytes` path. Snapshot rows therefore report coarse progress: `pulling`
on start, `ready` on completion, with `pulled_bytes` left at 0 and
`expected_bytes` NULL. Settings -> Models shows a spinner ("downloading") rather
than a percentage for these two rows. This is acceptable for two ~1.2 GB repos
and avoids reaching into `huggingface_hub`'s internal tqdm.

---

## C2. Provider rebind to the front-door

`bundled_providers.py` constants change:

```python
BUNDLED_CHAT_BASE_URL   = "http://hlh_swap:9620"
BUNDLED_EMBED_BASE_URL  = "http://hlh_swap:9620"
BUNDLED_RERANK_BASE_URL = "http://hlh_swap:9620"
BUNDLED_EMBED_MODEL  = "qwen3-embed"      # unchanged: llama-swap routing alias
BUNDLED_RERANK_MODEL = "qwen3-reranker"   # unchanged: llama-swap routing alias
```

`apply_bundled_bindings` logic is unchanged: it still `INSERT ... ON CONFLICT`
the `embedding_provider_id` / `reranker_provider_id` / model keys into
`global_settings`. The only behavioral effect is the new `base_url`, which
`_upsert_bundled_row`'s `ON CONFLICT DO UPDATE SET base_url = EXCLUDED.base_url`
rewrites idempotently on the next boot - so existing deployments' bundled rows
self-heal to the front-door without manual edits. Chat moves too: llama-swap
fronts chat (`medgemma` / `qwen-chat` aliases) as well, so all three bundled
providers resolve through `hlh_swap:9620`.

The served aliases stay `qwen3-embed` / `qwen3-reranker`; llama-swap's config
(folder B) maps those aliases to boofinity's `proxy` upstream. From HLH's side
nothing about the model name changes - only the host:port.

---

## C3. boofinity /rerank contract in rag.py

`_rerank_infinity` already sends `documents: [p["text"] for p in passages]` (a
list of strings) and already parses `results[].index` + `results[].relevance_score`.
Reading the current code (`rag.py:251-278`), the request shape and the response
parse are **already** boofinity-shaped: documents is a list of strings, not
`[{text}]`. The work here is to confirm and lock that contract against
boofinity's `--url-prefix /v1` routing (folder B sets the prefix via the CLI
flag, not an env var) and to keep the soft-fallback:

(Note: the existing HLH function name `rag.py:_rerank_infinity` is application
code and out of scope for this fold; it keeps its identifier. A follow-up may
rename it to `_rerank_boofinity` for naming consistency.)

- Request: `POST {base_url}/v1/rerank` with
  `{"model", "query", "documents": [str, ...], "return_documents": false}`.
- Response: `{"results": [{"index": int, "relevance_score": float}, ...]}`.
- Parse: map `index` back into `passages[idx]`, attach `score = relevance_score`,
  drop out-of-range indices, return `None` (flashrank fallback) on empty or any
  exception.

`base_url` is now `http://hlh_swap:9620` (from C2's provider row), and
llama-swap forwards `/v1/rerank` to boofinity which serves it under its
`/v1` prefix. The broad `except Exception` soft-fallback to flashrank ->
similarity order is preserved verbatim; a cold-swap stall or a 404 during a
backend swap must degrade RAG, never break it.

If a future audit finds the request was ever `[{text}]`-shaped in a sibling
branch, the canonical contract is list-of-strings; the verify script asserts the
exact request body.

---

## C4. embeddings.py OpenAI-compat confirmation

`embeddings.py:_post` already posts `{"model", "input": [...]}` to
`{base_url}/v1/embeddings` and reads `data[].embedding`, asserting
`len(emb) == EMBEDDING_DIM` (1024). boofinity launched with `--url-prefix /v1`
(folder B's CLI flag) serves the OpenAI `/v1/embeddings` route and returns
1024-dim vectors for
Qwen3-Embedding-0.6B. No code change beyond `base_url` (which flows from the
provider row, C2). The verify script asserts a live 1024-length vector from the
front-door. The `EMBEDDING_DIM` mismatch raise stays as the integrity guard if a
wrong model is ever wired in.

---

## C5. One-shot reingest on cutover (the load-bearing safety design)

### Why automatic

Switching the embedder invalidates every stored `source_chunks.embedding`. A
manual "remember to reingest" step would leave most deployments silently
retrieving against stale vectors. So the cutover fires
`POST /api/sources/reingest-all` itself, once.

### Exactly-once guard

A new module `services/embed_cutover.py` runs from `main.py` lifespan, after
`apply_bundled_bindings` and after `seed_registry`. It is guarded by a
`global_settings` sentinel (key/value table; `INSERT ... ON CONFLICT (key) DO
NOTHING` per the singleton convention):

```
key   = 'embed_cutover_boofinity_done'
value = '<ISO-8601 timestamp>'
```

Algorithm:

1. If `global_settings['embed_cutover_boofinity_done']` exists -> no-op, return.
2. If tier is `external` -> no-op (operator owns their embedder); still write the
   sentinel so it never fires later when they have stale state from a prior
   bundled run? No - leave the sentinel unset for external so a later switch to
   bundled still triggers. (External never had bundled vectors to invalidate;
   reingest is harmless but unnecessary, so we skip and do not set the sentinel.)
3. Readiness precondition: the embed `bundled_models` row must be `ready` AND a
   live probe of the embed provider (`POST /v1/embeddings` with one tiny input
   through the front-door) must return a 1024-vector. If not ready, return
   **without** setting the sentinel, so the next boot retries. This prevents
   firing reingest while boofinity is still cold or mid-pull (which would mark
   every source `error`).
4. When ready: set the sentinel first (so a crash mid-reingest does not re-fire
   the whole corpus), set a `global_settings['retrieval_rebuilding'] = 'true'`
   flag for the banner, then enqueue the reingest by calling the same logic the
   `POST /api/sources/reingest-all` endpoint uses. To avoid a self-HTTP call
   from inside the container (no curl; awkward auth), factor the endpoint body
   into a reusable `reingest_all_sources_impl(pool, audit=None)` and call it
   directly from both the router and the cutover module.
5. The reingest tasks themselves clear `retrieval_rebuilding` when the last
   source finishes (a completion hook in the ingest path flips the flag to
   `false` once no source is `processing`).

### Sentinel-before-work ordering

Setting the sentinel *before* enqueueing guarantees at-most-once corpus-wide
reingest even if the process dies after enqueue. The trade-off: if the process
dies *between* sentinel-set and enqueue, no reingest happens and the sentinel
blocks a retry. Mitigation: enqueue is a synchronous `INSERT`-free in-memory
`asyncio.create_task` loop that runs in the same tick as the sentinel write;
the window is a single event-loop turn. An operator escape hatch is the existing
manual `POST /api/sources/reingest-all`, which is idempotent (it deletes and
re-creates chunks) and ignores the sentinel.

### Banner

`global_settings['retrieval_rebuilding']` is read by an existing settings
endpoint (or a one-line addition to the system status payload) and surfaced in
the frontend as "Retrieval is rebuilding after a model change." This folder
specifies the backend flag and its lifecycle; the exact banner component is a
thin frontend addition noted in tasks, reusing the existing degradation-banner
surface from `surface-retrieval-degradation`.

---

## C6. doctor.py

- `_check_model_pulls` is role/status-based and already covers any
  `bundled_models` row regardless of pull shape - the snapshot embed/rerank rows
  flow through it unchanged (`pulling` -> WARN, `failed` -> ERROR, `ready` ->
  counted). No change to the check body; the verify task asserts the embed/rerank
  rows appear with `role in (embed, rerank)`.
- New `_check_infer_cache_writable()` mirrors `_check_models_writable()` but for
  the HF cache volume: probe-write `/cache/.doctor-write-probe`. ERROR with the
  `chown -R 1000:1000` remedy (same failure class as `hlh_models`, per CLAUDE.md
  - a populated root-owned volume blocks uid-1000 snapshot writes). Added to
  `run_checks()` next to `_check_models_writable`.

---

## C7. providers.py 1024-dim check (unchanged)

boofinity embeddings are 1024-dim, so `providers.py:374-375` stays exactly:

```python
if dim != 1024:
    return False, f"error: embedding dim mismatch: expected 1024, got {dim}"
```

This wire-string is matched by frontend inline-error rendering and the verify
scripts; it is preserved verbatim. No change.

---

## C8. verify scripts

- `verify_boofinity_embed_rerank.sh` (new): probe the front-door from inside the
  container (no curl - `docker exec hlh_api python -c "import httpx..."`):
  - `POST http://hlh_swap:9620/v1/embeddings` with `{"model":"qwen3-embed","input":["x"]}`
    -> assert `data[0].embedding` length 1024.
  - `POST http://hlh_swap:9620/v1/rerank` with `{"model":"qwen3-reranker","query":"q","documents":["a","b"]}`
    -> assert `results[0]` has `index` and `relevance_score`.
  - assert `bundled_models` has `role=embed` and `role=rerank` rows reaching
    `status=ready` (poll the Models API, not psql).
- `verify_embedding_reranker_settings.sh` / `verify_embedding_reranker_ui.py`:
  update expected `base_url` from `hlh_chat:9610` to `hlh_swap:9620`; model
  aliases `qwen3-embed` / `qwen3-reranker` unchanged.
- `verify_bundled_immutability.sh`: the bundled provider rows now carry the
  front-door `base_url`; update the asserted immutable values accordingly.

---

## Guardrails

**Must Have:**
- Snapshot specs write the HF hub cache layout under
  `INFER_CACHE_DIR/hub/models--<org>--<repo>/` in `hlh_infer_cache`.
- `_EMBED_SPEC` / `_RERANK_SPEC` are `kind="snapshot"` safetensors repos;
  `seed_registry` prunes the retired GGUF rows.
- All three bundled provider `base_url`s are `http://hlh_swap:9620`.
- Reingest fires at most once, guarded by `embed_cutover_boofinity_done`, and
  only after the embed backend probes `ready` (1024-vector returned).
- `_rerank_infinity` sends `documents: list[str]` and parses
  `relevance_score` + `index`, with the soft-fallback preserved.
- The 1024-dim verbatim wire-string in `providers.py` is unchanged.
- `huggingface_hub.snapshot_download` runs in a thread under `_PULL_LOCK`.

**Must NOT Have:**
- No schema change (the sentinel is a `global_settings` key/value row).
- No VL embed/rerank, no image-embedding index (folder D).
- No change to `models.ini` (folder B owns it; embed/rerank sections already
  removed there).
- No self-HTTP call from inside the container for the reingest trigger; call the
  factored `reingest_all_sources_impl` directly.
- No reuse of the deprecated `EMBEDDING_URL` / `RERANKER_URL` / `INFERENCE_URL`
  env vars (hard rule #6); all resolution stays through `provider_client`.

---

## Open risks

1. **Reingest auto-trigger idempotency.** The sentinel-before-enqueue ordering
   gives at-most-once. The residual window (crash between sentinel-set and
   enqueue) leaves the sentinel set with no reingest; the manual endpoint is the
   escape hatch. A stronger design (a `reingest_jobs` table with a claimed/done
   state machine) was rejected as over-engineering for a one-time cutover.
2. **GGUF -> safetensors numerical drift.** Until reingest completes, queries
   embedded by boofinity are compared against GGUF-era stored vectors - cosine
   scores are meaningless and retrieval degrades. The `retrieval_rebuilding`
   banner makes this visible; the window is bounded by corpus size. There is no
   way to make the two vector spaces compatible, hence the full reingest.
3. **Readiness false-positive.** If the embed row is `ready` but boofinity is
   mid-swap (TTL-unloaded by llama-swap), the probe in step 3 pays a cold-start
   or times out. The probe uses a generous timeout and, on failure, returns
   without setting the sentinel so the next boot retries - never firing reingest
   against a down backend.
4. **Snapshot disk space.** `_check_disk_space` is skipped for snapshots (total
   unknown). Two ~1.2 GB repos on `hlh_infer_cache`; the existing
   `_check_disk_free("/models")` doctor check does not cover `/cache`. The new
   `_check_infer_cache_writable` checks writability but not free space; a
   free-space check on `/cache` is a possible follow-up, out of scope here.
5. **Deploy ordering with folder B.** If C deploys before B's front-door exists,
   the provider rows point at an unreachable `hlh_swap:9620`. B and C must land
   together; the doctor `hlh_swap` check (folder B) flags the gap.
6. **huggingface_hub version floor.** boofinity and the puller share the
   `huggingface_hub` cache layout; a too-old or too-new `huggingface_hub` in
   `hlh_api` could write a snapshot layout boofinity does not read, or change the
   `snapshot_download` signature. Mitigation: pin `huggingface_hub` explicitly in
   `requirements.txt` at `>=` boofinity's floor and verify the import in
   `hlh_api` (task C1.4). Operator-confirmable against boofinity's own pin.
7. **read_only boofinity cache writes.** `hlh_infer` is `read_only`; if
   torch/transformers write outside `HF_HOME` (e.g. `~/.cache`), a read-only
   rootfs raises `EACCES` at startup. Mitigation: `HOME=/cache` on `hlh_infer`
   (task C1.4a). If a sub-cache must not persist, a tmpfs covers it.

---

## Implementation notes

Added 2026-06-16 during folder C implementation. These are observations where a
cited source differed from the design assumption; no silent redesign was done.

- **C1.4a (HOME=/cache) was already landed by folder B.** The design assigns the
  `HOME=/cache` env addition to task C1.4a as a "one-line compose edit." On
  inspection, folder B already set `HF_HOME=/cache` AND `HOME=/cache` (plus
  `HF_HUB_OFFLINE=1`) on both the `hlh-swap-base` anchor and the `hlh_swap_gpu`
  override in `docker-compose.yml` (lines 17-18, 149-150). C added no compose env
  for this; the requirement is satisfied. Live no-EACCES boot confirmation is
  deferred to deploy.

- **C8.2 is a no-op against the current scripts.** Tasks C8.2 / design §C8 say to
  change the expected provider `base_url` from `hlh_chat:9610` to `hlh_swap:9620`
  in `verify_embedding_reranker_settings.sh` and `verify_embedding_reranker_ui.py`.
  Neither script references `hlh_chat:9610` or asserts the bundled providers'
  `base_url`: both stand up their own ad-hoc test providers (`step5-*`) with
  caller-supplied URLs and exercise the `/api/settings/embedding|reranker`
  endpoints, not the bundled rows. There was nothing to rewrite, so no edit was
  made. The front-door `base_url` assertion the design intends now lives in
  `verify_bundled_immutability.sh` (C8.3) and the new
  `verify_boofinity_embed_rerank.sh` (C8.1), which DO probe the front-door
  directly. Model aliases (`qwen3-embed` / `qwen3-reranker`) are unchanged, as
  specified.

- **Snapshot `kind` re-derivation.** Per design, `bundled_models` does not store
  `kind`; `pull_model` re-derives it from `MODEL_REGISTRY` via the new
  `_spec_kind(role, tier, model_id)` helper (matches on `model_id` so a stale row
  whose registry spec changed falls back to `"file"`, never mis-dispatching).

- **Empty-corpus banner clear.** `embed_cutover` clears `retrieval_rebuilding`
  immediately when `reingest_all_sources_impl` queues zero sources, because the
  ingest completion hook (which normally clears it) never fires with no source in
  `processing`. Prevents a stuck `'true'` flag on a deployment with no documents.

- **C3/C4/C7 confirmed unchanged.** `rag.py:_rerank_infinity` already sends
  `documents: list[str]` with `return_documents: False` and parses
  `index`/`relevance_score` under a broad soft-fallback; `embeddings._post`
  already posts `/v1/embeddings` and guards `len(emb) == EMBEDDING_DIM` (1024);
  `providers.py` still returns the verbatim
  `"error: embedding dim mismatch: expected 1024, got {dim}"`. No edits, as the
  planners locked.
