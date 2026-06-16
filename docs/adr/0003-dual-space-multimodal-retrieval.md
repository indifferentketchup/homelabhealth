# 0003 — Additive dual-space multimodal retrieval

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** indifferentketchup

## Context

The operator wants native Qwen3-VL image embedding and reranking. Today images
get retrieval indirectly: `services/vision.py` has MedGemma read them at
ingestion and emit text, which is embedded by the text embedder into
`source_chunks.embedding vector(1024)`.

Hard constraint: Qwen3-Embedding-0.6B (text) and Qwen3-VL-Embedding-2B are
**different models**, so their vectors occupy **different spaces** and are not
cosine-comparable. Image vectors cannot simply be dropped into the existing text
index — even sliced to 1024 dims they would be mathematically incomparable to
text-embed query vectors. The VL models are also ~2B params each (GPU-favoured),
viable only on the largest GPU tier.

## Decision

Adopt **additive dual-space retrieval**:

- Text retrieval is unchanged on every tier (Qwen3-Embedding-0.6B → `source_chunks`,
  MedGemma-read-to-text remains the image fallback on lesser tiers).
- On gpu-24gb+, ingestion *also* produces native image vectors via
  Qwen3-VL-Embedding-2B into a **new, separate** `source_image_embeddings`
  `vector(1024)` table (matryoshka-sliced to 1024 to reuse the pgvector/HNSW plumbing).
- At query time, embed the query into both spaces, ANN-search each, fuse the
  candidate sets, and order the union with the Qwen3-VL reranker.

## Consequences

- **+** Real visual retrieval (find the chart/scan by query) without disturbing
  the text path or any non-GPU tier.
- **+** Graceful tier story: smaller tiers keep working exactly as today.
- **−** A second index + cross-space fusion logic; two query embeds on gpu-24gb+.
- **−** New schema (`source_image_embeddings`) — additive and reversible-ish, but a real migration.
- **−** Image vectors only exist for content ingested while on gpu-24gb+; tier downgrades leave them stale/unused.

## Alternatives considered

- **Unified VL embedder for everything** (replace text embedder, one space) —
  rejected: 2B torch model is GPU-centric and slow on CPU tiers, contradicting
  the "VL on GPU only" resource decision; every tier swap forces a full reingest.
- **VL rerank only, defer VL embed** — viable smaller cut, rejected because the
  operator explicitly wants native VL *embedding*, not just reranking.
