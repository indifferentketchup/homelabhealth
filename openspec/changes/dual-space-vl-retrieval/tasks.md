# Tasks: dual-space-vl-retrieval

**Date:** 2026-06-16

Folder D. Additive, `gpu-24gb+`-only. Depends on folder B (VL served behind
`hlh_swap`) and folder C (HF-snapshot puller + embed-vl/rerank-vl providers) at
runtime; the schema and registry tasks here are independent of B/C and can land
first. Do D1 (schema) before D3 (ingest) and D4 (retrieval) so the table exists.
Do D2 (registry) before any pull verification.

All DB probes use `docker exec hlh_db psql -U hlh -d hlh ...` without `-it`.
All in-container HTTP probes use `docker exec hlh_api python -c "import asyncio,
httpx; ..."` (no curl in `hlh_api`). `psql -c` cannot do `:'var'`
interpolation - assert on API JSON or `psql -f`.

---

## D1 - Schema: source_image_embeddings + role widening

### D1.1 - Add the source_image_embeddings table

- [ ] In `backend/schema.sql`, immediately after the `source_chunks` block
      (after the `source_chunks_source_id_idx` create, around line 252), add
      `CREATE TABLE IF NOT EXISTS source_image_embeddings` with columns `id`,
      `source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE`,
      `page_no INT`, `image_ref TEXT`, `embedding vector(1024)`,
      `created_at TIMESTAMPTZ DEFAULT NOW()`.
- [ ] Confirm the table is placed AFTER `CREATE EXTENSION IF NOT EXISTS vector;`
      (`schema.sql:3`) - it is, since `source_chunks` already is.

**Verify:** apply schema, then
`docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT to_regclass('source_image_embeddings')"`
returns `source_image_embeddings`.

### D1.2 - Add the HNSW cosine + source_id indexes

- [ ] In `backend/schema.sql`, beside the new table, add
      `CREATE INDEX IF NOT EXISTS source_image_embeddings_source_id_idx ON source_image_embeddings(source_id);`
      and
      `CREATE INDEX IF NOT EXISTS source_image_embeddings_embedding_hnsw ON source_image_embeddings USING hnsw (embedding vector_cosine_ops);`
      mirroring `source_chunks_embedding_hnsw` (`schema.sql:257-258`).

**Verify:**
`docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT indexdef FROM pg_indexes WHERE indexname='source_image_embeddings_embedding_hnsw'"`
output contains `USING hnsw` and `vector_cosine_ops`.

### D1.3 - Widen the inline bundled_models role CHECK

- [ ] In `backend/schema.sql` `CREATE TABLE IF NOT EXISTS bundled_models`
      (around line 473), add `'embed-vl'` and `'rerank-vl'` to the inline
      `role TEXT NOT NULL CHECK (role IN (...))` list.

### D1.4 - Widen the idempotent ALTER bundled_models role CHECK

- [ ] In `backend/schema.sql` (lines 501-503), add `'embed-vl'` and
      `'rerank-vl'` to the `ALTER TABLE bundled_models ADD CONSTRAINT
      bundled_models_role_check CHECK (role IN (...))` list. Add a one-line
      comment noting the VL roles, matching the existing `vision_base` comment
      style (lines 494-500). Precedent: `providers_role_check` (lines 388-390).

**Verify (both paths):** on a fresh DB, schema applies clean; on an existing DB,
the ALTER widens the constraint. Assert:
`docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='bundled_models_role_check'"`
output contains both `embed-vl` and `rerank-vl`.

### D1.5 - py_compile + schema smoke

- [ ] `python3 -m py_compile $(find backend -name '*.py')` exits 0.
- [ ] `docker compose build --no-cache hlh_api && docker compose up -d hlh_api`;
      `docker logs hlh_api` shows no `CheckViolationError` and no crash-loop.

---

## D2 - MODEL_REGISTRY: VL specs (gpu-24gb+ only)

### D2.1 - Extend ALL_ROLES

- [ ] In `backend/services/model_puller.py:36`, add `"embed-vl"` and
      `"rerank-vl"` to `ALL_ROLES`. Keep the set consistent with
      `MODEL_REGISTRY`: folder C adds `"tasks"` to `ALL_ROLES`, so after both
      changes `set(ALL_ROLES) == set(MODEL_REGISTRY.keys())` (the
      `verify_model_puller.py:72` assertion). Dependency: this task assumes folder
      C's `tasks` addition; if folder C has not landed, add `"tasks"` here too so
      the equality holds, and reconcile when C merges.

**Acceptance:** `python3 -c "from backend.services.model_puller import ALL_ROLES, MODEL_REGISTRY; assert set(ALL_ROLES)==set(MODEL_REGISTRY.keys()); assert {'embed-vl','rerank-vl'} <= set(ALL_ROLES)"` exits 0.

### D2.5 - Verify the VL repos are public and ungated on HuggingFace

- [ ] Verify `Qwen/Qwen3-VL-Embedding-2B` and `Qwen/Qwen3-VL-Reranker-2B` are
      publicly downloadable and ungated (no "Agree and access" gate), analogous to
      the `unsloth/medgemma-*` public-mirror note in CLAUDE.md. Check each repo's
      HuggingFace page / API for gated status.
- [ ] If either is gated or unavailable, flag it as a risk in design.md Open Risks
      (already noted) and do not mark the VL path shippable until resolved.

**Acceptance:** both repos confirmed public + ungated, or the risk is explicitly flagged unresolved.

### D2.2 - Add the embed-vl spec

- [ ] In `backend/services/model_puller.py` `MODEL_REGISTRY` (starts line 138),
      add an `"embed-vl"` role: every tier `None` except
      `"gpu-24gb+": ModelSpec(repo="Qwen/Qwen3-VL-Embedding-2B", filename=<folder-C snapshot convention>)`.
      Do NOT add `embed-vl` to `_FLAT_DEST_ROLES` (`model_puller.py:361`) - it is
      an HF directory snapshot, not a flat GGUF.

### D2.3 - Add the rerank-vl spec

- [ ] In the same `MODEL_REGISTRY`, add a `"rerank-vl"` role: every tier `None`
      except `"gpu-24gb+": ModelSpec(repo="Qwen/Qwen3-VL-Reranker-2B", filename=<folder-C snapshot convention>)`.

**Verify:** after restart,
`docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT DISTINCT tier FROM bundled_models WHERE role IN ('embed-vl','rerank-vl')"`
returns only `gpu-24gb+`. On a non-gpu tier the same query still returns only
`gpu-24gb+` (registry is tier-keyed), and `count(*)` for those roles is > 0.

### D2.4 - Confirm prune sweep keeps the VL rows

- [ ] Re-apply boot (`docker compose restart hlh_api`); confirm `docker logs
      hlh_api` `seed_registry: pruned N` does NOT remove the VL rows. Re-run the
      D2.3 count to confirm they persist.

### D2.6 - Widen providers_role_check for the VL provider roles

- [ ] In `backend/schema.sql`, add `'embed-vl'` and `'rerank-vl'` to the
      `providers_role_check` CHECK (`schema.sql:388-390`, currently
      `('chat', 'embed', 'rerank', 'vision_embed')`), via the idempotent
      `DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT` pattern. This is a SECOND
      role-CHECK widening, distinct from the `bundled_models_role_check` one
      (D1.3/D1.4); both gate VL role values.

**Verify:**
`docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='providers_role_check'"`
output contains both `embed-vl` and `rerank-vl`.

### D2.7 - Seed bundled VL embed/rerank providers (gpu-24gb+)

- [ ] In `backend/services/bundled_providers.py`, add `BUNDLED_VL_EMBED_*` and
      `BUNDLED_VL_RERANK_*` constants (name, `base_url = "http://hlh_swap:9620"`,
      models `qwen3-vl-embed` / `qwen3-vl-rerank`) mirroring the existing
      `BUNDLED_EMBED_*` / `BUNDLED_RERANK_*` block (lines 36-45).
- [ ] In `ensure_bundled_providers` (line 99), upsert the two VL rows with roles
      `embed-vl` / `rerank-vl` ONLY when the active tier is `gpu-24gb+`; on other
      tiers skip them.
- [ ] In `apply_bundled_bindings` (line 135), on `gpu-24gb+` wire the VL provider
      ids so `vision.py` / `rag.py` can resolve `embed-vl` / `rerank-vl` by role.
- [ ] `python3 -m py_compile backend/services/bundled_providers.py`.

**Verify (gpu-24gb+):** the `embed-vl` provider resolves with
`base_url = http://hlh_swap:9620`, model `qwen3-vl-embed`. On a lesser tier the
`embed-vl` / `rerank-vl` rows are absent and the VL path no-ops.

---

## D3 - Ingestion: second VL embed pass (gpu-24gb+)

### D3.1 - Add a VL image-embed helper in vision.py

- [ ] In `backend/services/vision.py`, add an async helper (e.g.
      `embed_image_vl(image_bytes, mime_type) -> list[float] | None`) that POSTs
      to boofinity `/v1/mm_embeddings` with model `qwen3-vl-embed`, resolving the
      `embed-vl` provider (folder D's bundled provider, D2.7). Slice the returned
      vector to 1024 dims per design.md (request `dimensions=1024`, else
      first-1024 prefix). Soft-fail to `None` on any exception, like `_call_vision`
      (`vision.py:75-114`).
- [ ] Add the native-dim guard: if the returned native vector length is `< 1024`,
      log an error naming the role and the observed length and return `None` (do
      NOT insert a short vector). Determine the native output dim of
      `Qwen3-VL-Embedding-2B` and whether boofinity honors `dimensions=1024`;
      record the finding in design.md.

**Acceptance:** a unit/probe shows a `< 1024` native length returns `None` and logs the length; a 1024 result inserts cleanly.

### D3.2 - Wire the gpu-24gb+ gate into the ingest path

- [ ] In `backend/routers/sources.py`, after the `source_chunks` insert block
      (after line ~199, where `embedding_status='complete'` is set), read the
      tier (`SELECT tier FROM system_profile WHERE id = 1`, pattern at
      `inference_job.py:426`). If tier == `gpu-24gb+` AND the `embed-vl` provider
      resolves, run the VL embed pass for the image source or each rendered PDF
      page and INSERT into `source_image_embeddings` using `format_vector`
      (`sources.py:20`) + `::vector` cast.
- [ ] Wrap the whole VL pass in try/except: log and swallow; never flip
      `embedding_status` to `error` because of a VL failure (spec
      vl-ingestion "Image-embed failure does not fail the ingest").

### D3.3 - Confirm the text path is unchanged

- [ ] Confirm `extract_image_via_vision` / `extract_pdf_via_vision`
      (`vision.py:117,156`) and the `source_chunks` write
      (`sources.py:182-199`) are untouched and still run on every tier.

**Verify (gpu-24gb+ only):** ingest a test image; assert
`SELECT count(*) FROM source_image_embeddings WHERE source_id=<id>` > 0 and the
`embedding` is 1024-dim. On a non-gpu tier, the same ingest yields 0 image rows.

---

## D4 - Retrieval: dual-space embed + RRF fuse + VL rerank

### D4.1 - Add a query VL-embed + image ANN helper in rag.py

- [ ] In `backend/services/rag.py`, add a helper that embeds the query via
      `/v1/mm_embeddings` (`qwen3-vl-embed`, sliced 1024, same method as D3.1)
      and ANN-searches `source_image_embeddings`
      (`ORDER BY embedding <=> $1::vector LIMIT TOP_K_RETRIEVE`). Pass the query
      vector as `str(list)` with `::vector` (CLAUDE.md asyncpg+pgvector).
      Soft-fail to an empty list on any exception.

### D4.2 - Add the RRF fusion helper

- [ ] In `backend/services/rag.py`, add a pure `rrf_fuse(text_ranked,
      image_ranked, k=60)` that combines by rank (`1/(k+rank)` summed across
      lists), deduping by `source_id`+locator. No raw cosine score comparison
      across the two lists (spec dual-space-retrieval-fusion).

### D4.3 - Add the VL rerank call

- [ ] In `backend/services/rag.py`, add a `_rerank_vl(query, candidates)` that
      POSTs the fused union to `/v1/mm_rerank` (`qwen3-vl-rerank`), text
      candidates as text and image candidates as images, resolving the
      `rerank-vl` provider via folder C. Soft-fail to `None` so the caller falls
      back to the RRF order, mirroring `_rerank_infinity` (`rag.py:224`).

### D4.4 - Gate the branch in retrieve_context

- [ ] In `backend/services/rag.py` `retrieve_context` (`rag.py:319`), after the
      text candidates are gathered, read the tier (`system_profile WHERE id=1`).
      If tier == `gpu-24gb+` AND both VL providers resolve: run D4.1 image ANN,
      D4.2 RRF fuse with the text candidates, D4.3 VL rerank; on VL-rerank
      failure use the RRF order; on any branch failure fall back to the existing
      text-only `_rerank_infinity` path. Otherwise leave the existing path
      byte-for-byte unchanged.

**Verify (gpu-24gb+ only):** with image vectors present, a query logs the image
ANN + VL rerank running (DEBUG). On a non-gpu tier, no `/v1/mm_embeddings` or
`/v1/mm_rerank` request is issued and retrieval uses only `source_chunks` +
`_rerank_infinity`.

---

## D5 - Cleanup (FK cascade verification)

### D5.1 - Confirm the cascade on source delete

- [ ] Confirm the sources delete path in `backend/routers/sources.py` deletes
      the `sources` row (it does; `source_chunks` already cascades). No new
      application delete of `source_image_embeddings` is needed.

**Verify:** create a source with image rows, `DELETE FROM sources WHERE id=<id>`,
then `SELECT count(*) FROM source_image_embeddings WHERE source_id=<id>` returns 0.

### D5.2 - Confirm PHI access/audit coverage (no new gap)

- [ ] Confirm no new endpoint or query reads `source_image_embeddings` rows or
      raw vectors outside the existing source-scoped access control. The vectors
      derive from medical images (PHI-adjacent); they MUST be reachable only via
      the already-controlled `sources` path. Grep for any `source_image_embeddings`
      SELECT that is not gated by the source's access check.
- [ ] Confirm no separate audit surface is added for `source_image_embeddings`
      beyond what covers `source_chunks` via the `sources` row.

**Acceptance:** `grep -rn 'source_image_embeddings' backend/routers/ backend/services/rag.py` shows only the ingest write and the gated retrieval ANN search, no ungated read endpoint.

---

## D6 - Verify script

### D6.1 - Author verify_dual_space_retrieval.sh

- [ ] Add `backend/scripts/verify_dual_space_retrieval.sh` following the existing
      `verify_*.sh` style. First read the active tier via API JSON; if not
      `gpu-24gb+`, print `SKIP: requires gpu-24gb+` and `exit 0`.
- [ ] On `gpu-24gb+`, assert in order: (a) `source_image_embeddings` + both
      indexes exist; (b) `embed-vl`/`rerank-vl` rows seeded without
      `CheckViolation` (real insert path); (c) ingesting an image adds a
      `source_image_embeddings` row; (d) deleting the source cascades the image
      rows away; (e) a query on `gpu-24gb+` exercises the VL rerank path.
- [ ] Use `PASS=$((PASS+1))` (not `((PASS++))`) and the
      `if cmd; then ec=0; else ec=$?; fi` pattern (CLAUDE.md bash quirks).
- [ ] In-container HTTP via `docker exec hlh_api python -c "import asyncio,
      httpx; ..."`; DB via `docker exec hlh_db psql -U hlh -d hlh ...` (no `-it`).

**Verify:** `bash backend/scripts/verify_dual_space_retrieval.sh` exits 0 (SKIP
off `gpu-24gb+`, all-pass on `gpu-24gb+`).

---

## D7 - Docs

### D7.1 - CHANGELOG

- [ ] Add a `## [Unreleased]` entry under the AI track noting additive
      dual-space VL retrieval (gpu-24gb+). Edit the exact line, do not `sed` the
      CHANGELOG (CLAUDE.md: `[Unreleased]` appears twice).
