# Proposal: dual-space-vl-retrieval

**Date:** 2026-06-16
**Status:** proposed

## Why

The operator wants native Qwen3-VL image embedding and reranking. Today images
get retrieval indirectly: `backend/services/vision.py` has MedGemma read each
image at ingestion and emit text, which the text embedder
(Qwen3-Embedding-0.6B) embeds into `source_chunks.embedding vector(1024)`. A
chart, scan, or lab photograph is only findable by whatever words MedGemma
happened to transcribe.

ADR 0003 (`docs/adr/0003-dual-space-multimodal-retrieval.md`, Accepted
2026-06-16) settles the shape: **additive dual-space retrieval**. The hard
constraint is that Qwen3-Embedding-0.6B (text) and Qwen3-VL-Embedding-2B
(image) are different models whose vectors occupy different spaces and are NOT
cosine-comparable. Image vectors therefore cannot be dropped into the existing
text index - even sliced to 1024 dims they would be mathematically incomparable
to a text-embed query vector. They need a separate index and a fusion step that
never compares raw cross-space scores.

The VL models are ~2B params each and GPU-favoured, so this whole path is gated
to the `gpu-24gb+` tier only. Every smaller tier keeps the existing
MedGemma-read-to-text fallback, unchanged.

This is folder D of the boofinity split. It depends on folder B (boofinity
serves the VL models behind the `hlh_swap` front-door) and folder C (the
HF-snapshot puller path plus the embed-vl/rerank-vl provider plumbing).

## What Changes

- **NEW table `source_image_embeddings`** (`vector(1024)`) in
  `backend/schema.sql`, additive and idempotent, with an HNSW cosine index
  mirroring the existing `source_chunks_embedding_hnsw`. The existing
  `source_chunks` table and index are untouched.
- **NEW `bundled_models.role` values** `embed-vl` and `rerank-vl`, added via the
  dual-update CHECK pattern (inline `CREATE TABLE` CHECK plus an idempotent
  `ALTER TABLE DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT`) so `seed_registry`
  can insert them without a `CheckViolationError` on a fresh or existing DB.
- **NEW `MODEL_REGISTRY` entries** in `backend/services/model_puller.py`:
  `embed-vl` -> `Qwen/Qwen3-VL-Embedding-2B` and `rerank-vl` ->
  `Qwen/Qwen3-VL-Reranker-2B`, both only on `gpu-24gb+`, every other tier
  `None`. Pulled via folder C's HF-snapshot path. Served behind `hlh_swap` under
  aliases `qwen3-vl-embed` and `qwen3-vl-rerank`.
- **NEW bundled VL providers** in `backend/services/bundled_providers.py`:
  `embed-vl` and `rerank-vl` rows (base_url `http://hlh_swap:9620`, models
  `qwen3-vl-embed` / `qwen3-vl-rerank`), seeded only on `gpu-24gb+` and wired
  through `apply_bundled_bindings`, plus a `providers_role_check` widening so the
  rows insert. `vision.py` and `rag.py` resolve these to reach boofinity.
- **Image-embedding at ingestion** (`backend/services/vision.py` +
  `backend/routers/sources.py`): on `gpu-24gb+`, when ingesting an image or a
  PDF page, ALSO embed the rendered image via boofinity `/v1/mm_embeddings`
  (model `qwen3-vl-embed`, matryoshka-sliced to 1024) and write the vector into
  `source_image_embeddings`. The MedGemma-read-to-text path is unchanged and
  still feeds `source_chunks` on every tier.
- **Dual-space retrieval** (`backend/services/rag.py`): on `gpu-24gb+`, also
  embed the query into the image space via `/v1/mm_embeddings`, ANN-search
  `source_image_embeddings`, fuse the image candidates with the text-space
  `source_chunks` candidates by **rank** (Reciprocal Rank Fusion), then order
  the fused union with the Qwen3-VL reranker (`/v1/mm_rerank`, model
  `qwen3-vl-rerank`) - text candidates passed as text, image candidates as
  images. Raw cross-space scores are never compared.
- **NEW verify script** `backend/scripts/verify_dual_space_retrieval.sh`,
  gpu-only, that SKIPs cleanly when the active tier is not `gpu-24gb+`.

## Impact

- Affected specs: `image-embedding-schema`, `vl-model-registry`,
  `vl-ingestion`, `dual-space-retrieval-fusion` (all ADDED).
- Affected code: `backend/schema.sql` (table + both role-CHECK widenings),
  `backend/services/model_puller.py`, `backend/services/bundled_providers.py`
  (VL provider rows), `backend/services/vision.py`,
  `backend/routers/sources.py`, `backend/services/rag.py`,
  `backend/scripts/verify_dual_space_retrieval.sh`.
- Tiers other than `gpu-24gb+`: zero behavior change. The schema table and the
  role-CHECK widening apply on every DB (additive), but no rows are seeded and
  no ingestion or retrieval path activates off `gpu-24gb+`.
- Requires folder B (VL models served behind `hlh_swap`) and folder C (HF-
  snapshot puller + embed-vl/rerank-vl providers) to be present at runtime.
  Without them the gate stays closed and behavior is unchanged.

## Out of scope

- No change to `source_chunks`, the text embedder, or the text reranker.
- No live multimodal chat - image vectors feed retrieval only; chat stays text.
- No VL pulls or VL ingestion on any tier below `gpu-24gb+`.
- The HF-snapshot puller mechanics and the embed-vl/rerank-vl provider rows are
  folder C; this folder consumes them.
- The `hlh_swap` front-door and the `hlh_infer` boofinity service are folder B.
- No re-embedding of content ingested before this folder landed (backfill is a
  follow-up; pre-existing sources simply have no image vectors).
