# Design: dual-space-vl-retrieval

**Date:** 2026-06-16

---

## Where this sits in the boofinity split

This is folder D. It is purely additive and runs only on `gpu-24gb+`.

- **Folder B** (`boofinity-inference-frontdoor`) stands up the `hlh_swap`
  front-door (`:9620`) and the `hlh_infer` boofinity service. On `gpu-24gb+` the
  GPU `hlh_infer` already loads `Qwen/Qwen3-VL-Embedding-2B` (design.md of
  folder B, `hlh_infer_gpu` command). The VL reranker is added to that command
  by the same boofinity wiring. llama-swap routes the `qwen3-vl-embed` and
  `qwen3-vl-rerank` aliases to `hlh_infer:7997` (folder B config already lists
  both members in the swap group).
- **Folder C** (`boofinity-model-pulls-rebind`) adds the HF-snapshot puller path
  that the VL specs pull through. This folder (D) consumes that pull path; it
  does not re-author it. The `embed-vl` / `rerank-vl` bundled provider rows that
  `rag.py` and `vision.py` resolve are authored in THIS folder (see "VL bundled
  providers" below), not folder C.

This folder owns: the `source_image_embeddings` schema, the two new
`bundled_models.role` values, the two `MODEL_REGISTRY` specs, the ingestion
second-embed pass, and the retrieval fusion path. Nothing here loads on a tier
below `gpu-24gb+`.

---

## Schema: a separate index, not a column on source_chunks

`source_chunks` stays exactly as it is (`schema.sql:242-260`,
`source_chunks_embedding_hnsw` cosine HNSW). The new table mirrors its shape so
the existing pgvector/asyncpg conventions carry over verbatim:

```sql
CREATE TABLE IF NOT EXISTS source_image_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_no     INT,
    image_ref   TEXT,
    embedding   vector(1024),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS source_image_embeddings_source_id_idx
    ON source_image_embeddings(source_id);
CREATE INDEX IF NOT EXISTS source_image_embeddings_embedding_hnsw
    ON source_image_embeddings USING hnsw (embedding vector_cosine_ops);
```

`CREATE EXTENSION IF NOT EXISTS vector;` on `schema.sql:3` already precedes every
`vector(N)` table (CLAUDE.md hard rule 4), so no ordering change is needed. The
table goes near `source_chunks` (after line 260) so a reader finds both RAG
indexes together.

**Index type choice: HNSW.** `source_chunks` uses HNSW (`vector_cosine_ops`),
not ivfflat. We mirror it so the two RAG indexes behave identically (no ivfflat
`lists`/`probes` tuning to reconcile) and the cosine operator class matches what
the `<=>` query in `rag.py` already assumes.

### bundled_models.role widening (dual-update)

Two edits in lockstep, precedent `providers_role_check` (`schema.sql:388-390`):

1. Inline `CREATE TABLE bundled_models` CHECK gains `embed-vl`, `rerank-vl`.
2. The idempotent `ALTER TABLE bundled_models DROP CONSTRAINT IF EXISTS
   bundled_models_role_check; ADD CONSTRAINT ... CHECK (role IN (...))` gains the
   same two values.

The fresh-DB path enforces (1); the existing-DB path enforces (2). Updating only
one yields a `CheckViolationError` at `seed_registry` on the other path and
crash-loops `hlh_api` (CLAUDE.md "Role CHECK constraints gate new enum values").
`python -m py_compile` does NOT catch this - it is a runtime DB constraint, so
the verify step exercises a real insert.

---

## MODEL_REGISTRY: tier-gated VL specs

`model_puller.py` `MODEL_REGISTRY` gains two roles. Unlike the router roles
(`embed`, `rerank`, `tasks`) that use `_router_role(...)` to fan one GGUF across
all `_ROUTER_TIERS`, the VL specs are single-tier dicts:

```python
"embed-vl": {
    "cpu-min": None, "cpu-std": None, "gpu-4gb": None,
    "gpu-8gb": None, "gpu-16gb": None,
    "gpu-24gb+": ModelSpec(repo="Qwen/Qwen3-VL-Embedding-2B", filename="<snapshot>"),
    "apple-mlx": None, "external": None,
},
"rerank-vl": {
    ...same None pattern...
    "gpu-24gb+": ModelSpec(repo="Qwen/Qwen3-VL-Reranker-2B", filename="<snapshot>"),
},
```

`ALL_ROLES` (`model_puller.py:36`) is extended so the roles are recognized
project-wide. These are NOT added to `_FLAT_DEST_ROLES` (`model_puller.py:361`):
boofinity loads a HuggingFace directory snapshot (config + weights + tokenizer),
not a single flat `/models/<file>.gguf`, so the dest is a per-role/tier directory
under folder C's snapshot path. The exact `filename`/snapshot-dir convention is
folder C's; this folder's specs just point at the two repos.

`seed_registry`'s prune sweep (`model_puller.py:280-300`) keys on `(role, tier,
model_id)`; both VL rows are in `MODEL_REGISTRY` so they are in the `valid` set
and survive every boot.

---

## Ingestion: a second embed pass, gated

`routers/sources.py` ingest (around lines 123-205) keeps its current flow: vision
text extraction -> chunk -> `embed_batch` -> `source_chunks`. On `gpu-24gb+`,
after the text path, a new helper in `vision.py` runs the image-embedding pass:

1. Read `system_profile.tier` (`SELECT tier FROM system_profile WHERE id = 1`,
   the pattern at `inference_job.py:426`).
2. If tier is `gpu-24gb+` AND the `embed-vl` provider resolves (folder C), POST
   each rendered image (the image source bytes, or each PDF page rendered to an
   image) to `/v1/mm_embeddings` model `qwen3-vl-embed`.
3. Slice to 1024 dims (see below) and INSERT into `source_image_embeddings` with
   `page_no` (PDF page index, or 0/NULL for a single image) and `image_ref` (a
   stable per-page locator).

The embedding is stored as `format_vector(vec)` / `str(list)` with `::vector`
(the `embeddings.format_vector` helper `sources.py:20` already uses for
`source_chunks`).

**Failure isolation.** The image pass is wrapped so any exception (provider
unreachable, mm_embeddings error, slice failure) is logged and swallowed - the
text path already set `embedding_status`, and `source_chunks` is the source of
truth. This mirrors the deliberately broad soft-fail on `_rerank_infinity`
(`rag.py:224-`). The second pass must never turn a good ingest into an `error`.

### Matryoshka slice to 1024

Qwen3-VL-Embedding-2B emits a wider native vector; the column is `vector(1024)`.
**Decision: request `dimensions=1024` from `/v1/mm_embeddings` when boofinity
honors the parameter; otherwise take the first 1024 components (matryoshka
prefix) client-side.** The helper applies the identical reduction at query time
in `rag.py`, so ingest and query vectors share one matryoshka subspace. The two
1024-dim spaces (text vs image) remain non-comparable to each other - slicing
only makes the image vectors fit the column and reuse the HNSW plumbing; it does
NOT make them comparable to text vectors. Open fidelity risk noted below.

---

## Retrieval: dual-space embed, RRF fuse, VL rerank

`rag.py` `retrieve_context` (`rag.py:319`) gains a gated branch. The text path
(BM25 prefilter -> `embed_query` -> `source_chunks` ANN -> `_rerank_infinity`)
is unchanged and is the only path off `gpu-24gb+`.

On `gpu-24gb+` with VL providers configured:

1. **Text candidates** as today: top-K from `source_chunks` (`rag.py` existing
   ANN, `TOP_K_RETRIEVE = 40`).
2. **Image candidates**: embed the query via `/v1/mm_embeddings`
   (`qwen3-vl-embed`, sliced 1024), ANN-search `source_image_embeddings`
   (`embedding <=> $1::vector` ORDER BY ... LIMIT top-K). Each image candidate
   resolves to its `source_id` + page/image locator and the rendered image (or a
   reference the reranker can fetch).
3. **Fuse by rank (RRF), not by score.** Text and image cosine distances are NOT
   comparable (different models). Each list is rank-ordered independently; the
   fused score of a candidate is `sum over lists of 1/(k + rank)` with
   **`k = 60`** (the standard RRF constant from Cormack et al. 2009; chosen
   because it is rank-only and parameter-light, so no per-space score
   calibration is needed). The union is deduped by `source_id`+locator.
4. **Order by the VL reranker**: POST the fused union to `/v1/mm_rerank`
   (`qwen3-vl-rerank`), text candidates as text, image candidates as images.
   This replaces `_rerank_infinity` only on this branch.

**Why RRF, not score-merge or a single shared reranker score.** ADR 0003 makes
cross-space score comparison a hard no. RRF needs only per-list rank, so it is
provably free of cross-space score leakage. The VL reranker then re-scores the
small fused union in one comparable space (its own), which is legitimate because
the reranker is a single model scoring all candidates together. Alternatives
considered: (a) min-max normalizing each space's scores then merging - rejected,
still leaks distributional assumptions across non-comparable spaces; (b) skip
RRF and rerank the raw concatenation - viable but wastes reranker budget on
low-rank tails; RRF pre-trims to the candidates each space actually liked.

**Fallback chain.** If `/v1/mm_rerank` fails, fall back to the RRF-fused order;
if the whole VL branch fails, fall back to the unchanged text-only path
(`_rerank_infinity` -> flashrank -> similarity). A RAG turn never dies on a VL
failure, matching the existing soft-fail contract.

---

## VL bundled providers (embed-vl / rerank-vl)

`rag.py` and `vision.py` resolve a provider to reach boofinity. For the VL roles
they need `embed-vl` and `rerank-vl` provider rows. This folder seeds them in
`bundled_providers.py`, gated to `gpu-24gb+`:

```python
BUNDLED_VL_EMBED_NAME      = "HomeLab Health AI · VL Embed"
BUNDLED_VL_EMBED_BASE_URL  = "http://hlh_swap:9620"
BUNDLED_VL_EMBED_MODEL     = "qwen3-vl-embed"
BUNDLED_VL_RERANK_NAME     = "HomeLab Health AI · VL Rerank"
BUNDLED_VL_RERANK_BASE_URL = "http://hlh_swap:9620"
BUNDLED_VL_RERANK_MODEL    = "qwen3-vl-rerank"
```

`ensure_bundled_providers` upserts these two rows ONLY when the active tier is
`gpu-24gb+` (the only tier that pulls the VL models); on lesser tiers they are
not seeded and the VL retrieval/ingest gate stays closed (the provider does not
resolve, so the path no-ops). `apply_bundled_bindings` wires the two rows on
`gpu-24gb+` so `resolve_embedding_provider`-style resolution can find them by
role.

### providers_role_check must admit the VL roles

The bundled VL rows go in the `providers` table, whose
`providers_role_check` currently admits `('chat','embed','rerank','vision_embed')`
(`schema.sql:388-390`). Inserting a `role='embed-vl'` / `'rerank-vl'` row raises
`CheckViolationError` unless the CHECK is widened. This folder widens
`providers_role_check` to add `embed-vl` and `rerank-vl` using the same idempotent
`DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT` pattern as the `bundled_models`
widening above. This is a SECOND role-CHECK widening (distinct from the
`bundled_models_role_check` one): both tables gate the VL role values and both
must be updated or `seed_registry` / the provider upsert crash-loops `hlh_api`.

## VL native output dimension and the 1024 slice

`Qwen3-VL-Embedding-2B`'s native output dimension must be determined empirically
(it is a ~2B matryoshka embedder; the native width is wider than 1024). Two
things must be verified before relying on the slice:

1. Whether boofinity's `/v1/mm_embeddings` honors a `dimensions=1024` request
   parameter (returning a server-side-reduced 1024 vector). If it does, request
   it; the matryoshka property makes the server-reduced 1024 vector valid.
2. If `dimensions` is NOT honored, the client slices the first 1024 components
   (matryoshka prefix). This requires the native dim to be `>= 1024`.

**Guard:** the ingest/query helper SHALL error clearly if the native returned
vector length is `< 1024` (a misconfigured model or an unexpected native width),
rather than silently inserting a short vector that pgvector rejects with an
opaque dimension-mismatch. The error message names the role and the observed
length so the operator can see the model is wrong.

## PHI coverage of source_image_embeddings

`source_image_embeddings` vectors derive from medical images, so they are PHI-
adjacent. The table's `source_id` FK to `sources` with `ON DELETE CASCADE`
(above) means an image vector is reachable and deletable only through its source,
exactly like `source_chunks`. Access and audit are source-scoped: any read or
delete of `source_image_embeddings` happens via the `sources` row it hangs off,
which is already access-controlled and audited the same as `source_chunks`. This
folder adds NO new endpoint that returns raw image vectors and NO separate auth
or audit surface; the verify step confirms there is no path that reads
`source_image_embeddings` outside the existing source-scoped access (i.e. no
auth/audit gap is introduced). If a future endpoint exposes the vectors directly,
it must reuse the source-scoped guard.

## Cleanup / FK cascade

`source_id ... ON DELETE CASCADE` means a `DELETE FROM sources` removes the
image rows for free, exactly like `source_chunks`. The sources delete path
(`routers/sources.py`) deletes the `sources` row; Postgres cascades to both
`source_chunks` and `source_image_embeddings`. No new application delete is
needed. The verify script asserts the cascade.

---

## Verification

`backend/scripts/verify_dual_space_retrieval.sh`, gpu-only:

- Reads the active tier via the API JSON (CLAUDE.md: `psql -c` cannot do
  `:'var'` interpolation; assert on API JSON or `psql -f`). If tier is not
  `gpu-24gb+`, print `SKIP: requires gpu-24gb+` and exit 0.
- Asserts `source_image_embeddings` and both indexes exist.
- Asserts `embed-vl`/`rerank-vl` rows seed without `CheckViolation` (real insert
  path, since `py_compile` cannot catch a DB constraint).
- Ingests a small image source, asserts `source_image_embeddings` gains a row.
- Deletes the source, asserts the image rows are gone (cascade).
- Internal HTTP probes use `docker exec hlh_api python -c "import asyncio, httpx;
  ..."` (CLAUDE.md: `hlh_api` has no curl), and `docker exec hlh_db psql ...`
  without `-it`.

---

## Open risks

1. **RRF constant choice.** `k = 60` is the literature default, but with one
   text list (40) and one image list (top-K) the fusion is sensitive to how many
   image candidates exist. If a source has few image vectors, image candidates
   barely move the fused order. `k` and the per-list top-K are the tuning knobs;
   they belong in `global_settings` with env fallbacks in a follow-up, like the
   existing RAG thresholds. Shipped value is a conservative starting point, not
   tuned against a labeled set.
2. **Matryoshka-1024 fidelity.** Slicing a ~2B VL embedder down to 1024 dims
   discards tail dimensions. Qwen3-VL embeddings are matryoshka-trained so the
   1024-prefix is a valid (lower-fidelity) representation, but retrieval recall
   at 1024 vs full width is unmeasured here. If recall is poor, the column would
   have to widen (a real migration) - hence 1024 is locked to reuse the existing
   pgvector/HNSW plumbing for v1, with width as an explicit future lever.
3. **Ingestion latency of a second embed pass.** Every gpu-24gb+ image/PDF page
   now pays a second embed (VL) on top of MedGemma-read-to-text. PDFs with many
   pages multiply this. The pass is sequential after the text path; batching the
   page embeds and a per-source time budget are mitigations, but worst-case
   ingest time roughly doubles for image-heavy sources on gpu-24gb+. The failure
   isolation means a slow/aborted VL pass never blocks the text result.
4. **Tier downgrade leaves orphan image vectors.** If a deployment moves off
   `gpu-24gb+`, `source_image_embeddings` rows already written stay in the DB but
   are never queried (the retrieval gate is closed) - harmless but stale, and
   they still cascade-delete with their source. New ingests on the lower tier
   write none, so the index simply stops growing. Re-upgrading to `gpu-24gb+`
   resumes writes but does NOT backfill the gap; sources ingested while
   downgraded have no image vectors until re-ingested. A backfill job is out of
   scope (noted in proposal). The swap latency / model-load behavior of the VL
   models under `hlh_swap` is folder B's risk, not this folder's.
5. **VL model availability on HuggingFace (operator-confirmable).**
   `Qwen/Qwen3-VL-Embedding-2B` and `Qwen/Qwen3-VL-Reranker-2B` must be publicly
   downloadable and ungated for the bundled (offline-after-pull) flow, analogous
   to the `unsloth/medgemma-*` public-mirror note in CLAUDE.md. If either repo is
   gated or renamed, the snapshot pull (folder C path) fails and the VL gate
   stays closed. A task verifies public + ungated status; if unconfirmed it is a
   flagged risk, not a silent failure (the puller reports `failed`).
6. **VL native output dimension vs the 1024 column (operator/empirical).** The
   native width of `Qwen3-VL-Embedding-2B` and whether boofinity honors
   `dimensions=1024` are unverified here. If the native dim is `< 1024` the slice
   guard errors clearly rather than inserting a short vector. Determining the
   native dim and the `dimensions` parameter support is a required verification
   step (needs the model loaded on real GPU hardware).
