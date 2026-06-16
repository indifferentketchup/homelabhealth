# Tasks: boofinity-model-pulls-rebind

**Date:** 2026-06-16

Folder C. Depends on folder A (pins) and folder B (`hlh_swap`, `hlh_infer`,
`hlh_infer_cache`). C1-C4 may proceed in parallel; C5 depends on the reingest
factor (C5.1) and on C2 (provider rebind) being in place so the readiness probe
hits the front-door. Deploy C **with or after** folder B (the embed/rerank
aliases 404 on `hlh_chat` after B removes their `models.ini` sections).

All in-container probes use `docker exec hlh_api python -c "..."` (no curl in
`hlh_api`); state checks hit the API and assert on JSON, never `psql -c`.

---

## C1 - HF-snapshot pull path

### C1.1 - Add `kind` to ModelSpec
- [x] In `backend/services/model_puller.py:43-63`, add `kind: str = "file"` to
      the `ModelSpec` dataclass and `filename: str = ""` default.
- [x] Update the `model_id` property: return `f"{self.repo}@snapshot"` when
      `kind == "snapshot"`, else `f"{self.repo}@{self.filename}"`.
- [x] `python -m py_compile backend/services/model_puller.py`.

### C1.2 - Add cache constant and dispatch
- [x] Near `MODELS_BASE_DIR` (`model_puller.py:34`) add
      `INFER_CACHE_DIR = Path(os.environ.get("HLH_INFER_CACHE_DIR", "/cache"))`.
- [x] In `_FLAT_DEST_ROLES` (`model_puller.py:361`) remove `"embed"` and
      `"rerank"`, leaving `{"chat", "tasks"}`.

### C1.3 - Flip _EMBED_SPEC / _RERANK_SPEC to snapshots
- [x] Replace `_EMBED_SPEC` (`model_puller.py:110-117`) with a
      `kind="snapshot"` spec for `repo="Qwen/Qwen3-Embedding-0.6B"`,
      `license="apache-2.0"`, `revision="main"`.
- [x] Replace `_RERANK_SPEC` (`model_puller.py:118-125`) with a
      `kind="snapshot"` spec for `repo="Qwen/Qwen3-Reranker-0.6B"`.
- [x] Update the comment block above (`model_puller.py:102-109`) to note the
      GGUF->safetensors switch and that boofinity serves these from the HF cache.

### C1.4 - Add huggingface_hub dependency
- [x] Pin `huggingface_hub` explicitly in `backend/requirements.txt` at a version
      `>=` boofinity's floor (do not rely on it being a transitive pin that could
      drift). Use a `>=`/`<` range or `==` matching the installed major.
- [ ] Confirm import works in `hlh_api`:  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      `docker exec hlh_api python -c "import huggingface_hub; print(huggingface_hub.__version__)"`.
- [ ] Rebuild `--no-cache hlh_api` after adding the pin.  _(DEPLOY-DEFERRED: requires live stack/GPU)_

**Acceptance:** `grep -c '^huggingface_hub' backend/requirements.txt` >= 1; the import command prints a version.

### C1.4a - hlh_infer read_only cache HOME
- [x] On `hlh_infer` (folder B's service, read_only), set `HOME=/cache` in the  _(ALREADY DONE BY FOLDER B: compose sets HOME=/cache + HF_HOME=/cache + HF_HUB_OFFLINE=1 on the hlh-swap base anchor and gpu override; no-EACCES boot confirmation is DEPLOY-DEFERRED)_
      environment so torch/transformers sub-caches (`~/.cache/huggingface`,
      `~/.cache/torch`) that `HF_HOME` does not cover land in the writable volume
      rather than raising `EACCES` on the read-only rootfs. (Or add a tmpfs for any
      non-`/cache` cache dir.) Confirm a `bundled` boot logs no `EACCES`.

**Acceptance:** `docker logs hlh_infer` after a boot shows no `Permission denied` / `EACCES` from a cache write.

### C1.4b - bootstrap ensure_infer_cache_ownership
- [x] In `hlh_orchestra/bootstrap.py`, add `ensure_infer_cache_ownership()`
      mirroring `ensure_models_ownership()` (`bootstrap.py:228-249`): a throwaway
      `alpine` container running `chown -R 1000:1000 /cache` against the
      `hlh_infer_cache` volume. Call it in the bootstrap sequence next to the
      `ensure_models_ownership()` call. Keep it idempotent.
- [x] `python3 -m py_compile hlh_orchestra/bootstrap.py`.

**Acceptance:** `grep -c 'def ensure_infer_cache_ownership' hlh_orchestra/bootstrap.py` == 1.

### C1.5 - Snapshot download helper
- [x] Add `_snapshot_pull(repo, revision, token)` calling
      `huggingface_hub.snapshot_download(repo_id=repo, revision=revision or "main",
      cache_dir=str(INFER_CACHE_DIR / "hub"), token=token, local_files_only=False)`.
- [x] Map `GatedRepoError` / 401-equivalent to the existing
      "License acceptance required. Visit {license_url} ..." message.

### C1.6 - Branch pull_model on kind
- [x] In `pull_model` (`model_puller.py:460`), look up the spec in
      `MODEL_REGISTRY` by `(role, tier, model_id)` to derive `kind`.
- [x] For `kind == "snapshot"`: skip `_check_disk_space` and sha256; mark
      `pulling`; run `await asyncio.to_thread(_snapshot_pull, repo, revision, token)`
      under the already-held `_PULL_LOCK`; mark `ready` on success or `failed`
      with the exception text. Leave `pulled_bytes = 0`, `expected_bytes` NULL.
- [x] Keep the existing file path untouched for `kind == "file"`.
- [x] `python -m py_compile backend/services/model_puller.py`.

### C1.6a - Fix the pre-existing ALL_ROLES gap (add "tasks")
- [x] In `backend/services/model_puller.py:36`, add `"tasks"` to `ALL_ROLES`
      (currently `("chat", "embed", "rerank", "vision", "stt", "ocr")`). `tasks`
      is already a `MODEL_REGISTRY` key (line 201) but absent from `ALL_ROLES`, so
      `verify_model_puller.py:72`'s `set(MODEL_REGISTRY.keys()) == set(ALL_ROLES)`
      assertion (it expects "all 7 roles") fails. Keep the change idempotent (the
      VL roles `embed-vl`/`rerank-vl` are folder D's addition; this task only adds
      `tasks`).
- [x] `python3 -m py_compile backend/services/model_puller.py`.

**Acceptance:** `python3 -c "from backend.services.model_puller import ALL_ROLES, MODEL_REGISTRY; assert 'tasks' in ALL_ROLES; assert set(MODEL_REGISTRY.keys()) >= set(ALL_ROLES)"` exits 0 (run with the right sys.path).

### C1.7 - Verify seed_registry prune + snapshot rows
- [ ] After a boot, assert the registry rows via the Models API:  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      `docker exec hlh_api python -c "import asyncio,httpx; ..."` listing
      `bundled_models`; confirm an `embed` row with model_id
      `Qwen/Qwen3-Embedding-0.6B@snapshot` and a `rerank` row with
      `Qwen/Qwen3-Reranker-0.6B@snapshot`, and NO `.gguf` embed/rerank rows.

### C1.8 - Add hlh_infer_cache mount to hlh_api
- [x] In `docker-compose.yml`, add `hlh_infer_cache:/cache` to the `hlh_api`
      service volumes (the named volume itself is declared by folder B), so the
      API can write snapshots boofinity reads.
- [x] `docker compose config` resolves without error.

---

## C2 - Provider rebind to the front-door

### C2.1 - Rewrite base URLs
- [x] In `backend/services/bundled_providers.py:37,40,44` set
      `BUNDLED_CHAT_BASE_URL`, `BUNDLED_EMBED_BASE_URL`, `BUNDLED_RERANK_BASE_URL`
      all to `"http://hlh_swap:9620"`.
- [x] Leave `BUNDLED_EMBED_MODEL = "qwen3-embed"` and
      `BUNDLED_RERANK_MODEL = "qwen3-reranker"` unchanged.
- [x] `python -m py_compile backend/services/bundled_providers.py`.

### C2.2 - Verify self-heal on boot
- [ ] After boot, assert the three bundled provider rows resolve  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      `base_url = http://hlh_swap:9620`:
      `docker exec hlh_api python -c "import asyncio,httpx; ..."` against the
      providers API; run twice and confirm idempotent (no change second time).

---

## C3 - boofinity /rerank contract

### C3.1 - Confirm/lock request + parse
- [x] Read `rag.py:251-278`; confirm `documents` is `[p["text"] for p in passages]`
      (list of strings) and the parse reads `results[].index` + `relevance_score`.
      If any divergence, fix to that exact shape.
- [x] Keep `return_documents: false` and the broad `except Exception` soft-fallback
      returning `None`.
- [x] `python -m py_compile backend/services/rag.py`.

### C3.2 - Live rerank probe through the front-door
- [ ] `docker exec hlh_api python -c "import asyncio,httpx; ..."`:  _(DEPLOY-DEFERRED: requires live stack/GPU; covered by verify_boofinity_embed_rerank.sh)_
      `POST http://hlh_swap:9620/v1/rerank` with
      `{"model":"qwen3-reranker","query":"chest pain","documents":["unrelated","cardiac note"],"return_documents":false}`;
      assert `results[0]` has integer `index` and numeric `relevance_score`.

---

## C4 - embeddings.py confirmation

### C4.1 - Live embedding probe
- [ ] `docker exec hlh_api python -c "import asyncio,httpx; ..."`:  _(DEPLOY-DEFERRED: requires live stack/GPU; covered by verify_boofinity_embed_rerank.sh)_
      `POST http://hlh_swap:9620/v1/embeddings` with
      `{"model":"qwen3-embed","input":["test"]}`; assert
      `len(data[0]["embedding"]) == 1024`.
- [x] Confirm no code change needed beyond the provider `base_url` (C2); the
      `EMBEDDING_DIM` guard (`embeddings.py:59`) stays.

---

## C5 - One-shot reingest on cutover

### C5.1 - Factor reingest impl (prerequisite)
- [x] In `backend/routers/sources.py:454-484`, extract the body into a plain
      `async def reingest_all_sources_impl(pool, audit=None) -> dict` callable
      that takes the pool directly and does NOT use FastAPI `Depends`. The
      endpoint at lines 454-484 currently uses `Depends(get_principal)` and
      `Depends(audit_event)`, which only resolve inside a request; lifespan has no
      request, so `embed_cutover.py` (called from lifespan) CANNOT call the
      endpoint - it must call the plain impl. Have the `@router.post` endpoint
      delegate to the impl, passing its request-scoped `audit` handle; the
      cutover calls the impl with `audit=None`.
- [x] Behavior identical (delete chunks, mark processing,
      `asyncio.create_task(_ingest_source(...))`, return counts).
- [x] `python -m py_compile backend/routers/sources.py`.

**Acceptance:** `grep -n 'def reingest_all_sources_impl' backend/routers/sources.py` matches; the impl signature has no `Depends(` default.

### C5.2 - Create embed_cutover.py
- [x] New `backend/services/embed_cutover.py` with
      `async def run_embed_cutover(conn_or_pool) -> None`.
- [x] No-op if `global_settings['embed_cutover_boofinity_done']` exists.
- [x] No-op (without setting sentinel) if `system_profile.tier = 'external'`.
- [x] Readiness gate: embed `bundled_models` row `status='ready'` AND a live
      `/v1/embeddings` probe through the front-door returns a 1024-vector; on
      failure return WITHOUT setting the sentinel.
- [x] On ready: `INSERT ... ON CONFLICT (key) DO NOTHING` the sentinel with an
      ISO-8601 value; set `global_settings['retrieval_rebuilding'] = 'true'`;
      call `reingest_all_sources_impl(pool)`.

### C5.3 - Clear the rebuilding flag on completion
- [x] Add a completion hook in the ingest path (the tail of `_ingest_source` in
      `backend/routers/sources.py`, after a source's `embedding_status` is set to
      `complete`/`error`): query
      `SELECT count(*) FROM sources WHERE embedding_status = 'processing'`; when
      the count is 0, set `global_settings['retrieval_rebuilding'] = 'false'`
      (`INSERT ... ON CONFLICT (key) DO UPDATE`). Guard the flip so it only runs
      when the flag is currently `'true'` (avoid a write on every normal ingest).
- [x] `python -m py_compile backend/routers/sources.py`.

**Acceptance:** after a cutover reingest drains (no source `processing`),
`global_settings['retrieval_rebuilding']` is `'false'`; the banner clears.

### C5.4 - Wire into lifespan
- [x] In `backend/main.py` lifespan, after `apply_bundled_bindings` and
      `seed_registry`, `await run_embed_cutover(pool)` inside the existing
      try/except so a cutover failure logs but does not block startup.
- [x] `python -m py_compile backend/main.py`.

### C5.5 - Expose the banner flag
- [x] Add `retrieval_rebuilding` to the system/settings status payload the
      frontend already polls (reuse the `surface-retrieval-degradation` banner
      surface); render "Retrieval is rebuilding after a model change." when true.

### C5.6 - Verify idempotency
- [ ] Boot once with a ready embed backend; confirm via the sources API that  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      `queued > 0` and the sentinel is set (`docker exec hlh_api python -c ...`).
- [ ] Restart; confirm the cutover no-ops (no new reingest; `queued` not re-fired)  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      by checking the sentinel present and source `updated_at` unchanged.

---

## C6 - doctor.py

### C6.1 - HF cache writable check
- [x] Add `_check_infer_cache_writable()` mirroring `_check_models_writable`
      (`doctor.py:418`) but probing `INFER_CACHE_DIR` (default `/cache`); ERROR
      with the `chown -R 1000:1000 /cache` remedy.
- [x] Register it in `run_checks()` (`doctor.py:480`) next to
      `_check_models_writable()`.
- [x] `python -m hlh.doctor` (note: exits 1 if any check ERROR by contract); use
      `|| true` to capture output.

### C6.2 - Confirm model_pulls covers snapshots
- [x] Confirm `_check_model_pulls` (`doctor.py:441`) needs no change: a `failed`
      embed snapshot row yields ERROR. Add this assertion to the verify script.

---

## C7 - providers.py dim check (no change)

### C7.1 - Confirm verbatim wire-string preserved
- [x] Confirm `backend/routers/providers.py:374-375` still reads
      `if dim != 1024: return False, f"error: embedding dim mismatch: expected 1024, got {dim}"`.
      No edit; this folder must not paraphrase it.

---

## C8 - verify scripts

### C8.1 - New verify_boofinity_embed_rerank.sh
- [x] Create `backend/scripts/verify_boofinity_embed_rerank.sh`: front-door
      embed probe (1024-len), front-door rerank probe (`index` + `relevance_score`),
      and an assertion that `bundled_models` embed+rerank rows reach `ready` via
      the Models API. Use `if cmd; then ec=0; else ec=$?; fi` and `PASS=$((PASS+1))`.

### C8.2 - Update embedding/reranker verify scripts
- [x] In `verify_embedding_reranker_settings.sh` and
      `verify_embedding_reranker_ui.py`, change expected provider `base_url` from
      `hlh_chat:9610` to `hlh_swap:9620`; keep aliases `qwen3-embed` /
      `qwen3-reranker`.

### C8.3 - Update immutability verify
- [x] In `verify_bundled_immutability.sh`, update the asserted bundled-row
      `base_url` to `http://hlh_swap:9620`.

---

## Deploy ordering note

- [ ] Deploy this folder **with or after** folder B. Confirm the doctor  _(DEPLOY-DEFERRED: requires live stack/GPU)_
      `hlh_swap` check (folder B) is OK before flipping providers, so the embed
      and rerank aliases resolve at the front-door rather than 404 on `hlh_chat`.
- [x] Update `CHANGELOG.md` `[Unreleased]` (AI track) by hand or a targeted
      `Edit` (do NOT `sed` - `[Unreleased]` appears twice).
