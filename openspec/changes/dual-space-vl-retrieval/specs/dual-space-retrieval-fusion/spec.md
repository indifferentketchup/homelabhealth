# Delta spec: dual-space-retrieval-fusion

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: On gpu-24gb+ retrieval SHALL embed the query into the image space and ANN-search it

On `gpu-24gb+`, `backend/services/rag.py` `retrieve_context` SHALL, in addition
to the existing text embed + `source_chunks` ANN search, embed the query via
boofinity `/v1/mm_embeddings` (model `qwen3-vl-embed`, sliced to 1024 by the
same method used at ingestion) and ANN-search `source_image_embeddings` by
cosine distance (`embedding <=> $1::vector`) for the top image candidates. The
active tier SHALL be read from `system_profile WHERE id = 1`.

#### Scenario: Image-space search runs on gpu-24gb+

- **GIVEN** `system_profile.tier = 'gpu-24gb+'`, the VL providers configured, and
  image vectors present
- **WHEN** a query runs through `retrieve_context`
- **THEN** an ANN search against `source_image_embeddings` SHALL execute
- **AND** its candidates SHALL be carried into the fusion step

#### Scenario: pgvector cast is used for the query vector

- **WHEN** the image-space ANN query is issued
- **THEN** the query embedding SHALL be passed as `str(list)` with a `::vector`
  cast per the CLAUDE.md asyncpg+pgvector convention, not as a raw Python list

### Requirement: Cross-space candidates SHALL be fused by rank, never by raw score

`retrieve_context` SHALL NOT merge the text-space and image-space candidate sets
by comparing their raw cosine distances or similarity scores, because the
text-embedding space (Qwen3-Embedding-0.6B) and the image-embedding space
(Qwen3-VL-Embedding-2B) are NOT cosine-comparable. It SHALL fuse them by
**rank** using Reciprocal Rank Fusion
(RRF): each candidate's fused score is the sum over the lists it appears in of
`1 / (k + rank)` for a fixed constant `k`. The fusion method and the `k` value
SHALL be documented in `design.md`.

#### Scenario: No raw cross-space score comparison

- **WHEN** text-space and image-space candidates are combined
- **THEN** the merge SHALL be by per-list rank position, not by raw cosine score
- **AND** a text candidate and an image candidate SHALL never be ordered relative
  to each other by directly comparing their cosine distances

#### Scenario: RRF combines a candidate present in both lists

- **GIVEN** a passage that ranks high in both the text list and the image list
- **WHEN** RRF runs with constant `k`
- **THEN** its fused score SHALL be the sum of `1/(k+rank)` from each list
- **AND** it SHALL rank at or above a candidate present in only one list at the
  same per-list rank

### Requirement: The fused union SHALL be ordered by the Qwen3-VL reranker

`retrieve_context` SHALL order the fused candidate union with the Qwen3-VL
reranker via boofinity `/v1/mm_rerank` (model `qwen3-vl-rerank`), passing
text candidates as text and image candidates as images. This VL rerank SHALL
replace the existing text `/v1/rerank` (`_rerank_infinity`) call only on the
gpu-24gb+ dual-space path; the text-only path on every other tier SHALL continue
to use `_rerank_infinity` with the flashrank/similarity fallback chain
unchanged.

#### Scenario: VL rerank orders the union on gpu-24gb+

- **GIVEN** a fused union of text and image candidates on `gpu-24gb+`
- **WHEN** ordering runs
- **THEN** the order SHALL come from `/v1/mm_rerank` (model `qwen3-vl-rerank`)
- **AND** text candidates SHALL be submitted as text and image candidates as images

#### Scenario: VL rerank failure falls back without taking down the turn

- **GIVEN** the `/v1/mm_rerank` call raises or times out
- **WHEN** ordering runs
- **THEN** retrieval SHALL fall back to the RRF-fused order (or the text-only
  `_rerank_infinity` path) rather than raising
- **AND** the RAG-enabled chat turn SHALL still complete

### Requirement: The dual-space path SHALL be gated and otherwise leave retrieval unchanged

The image-space embed, image ANN search, RRF fusion, and VL rerank path SHALL
activate only when BOTH `system_profile.tier == 'gpu-24gb+'` AND the VL embed
and rerank providers are configured. When the gate is closed, `rag.py`
`retrieve_context` SHALL behave exactly as today: text embed + `source_chunks`
ANN + `_rerank_infinity` (flashrank/similarity fallback).

#### Scenario: cpu-std retrieval is byte-for-byte the existing path

- **GIVEN** `system_profile.tier = 'cpu-std'`
- **WHEN** a query runs through `retrieve_context`
- **THEN** no `/v1/mm_embeddings` or `/v1/mm_rerank` request SHALL be issued
- **AND** retrieval SHALL use only `source_chunks` and `_rerank_infinity` as today

#### Scenario: gpu-24gb+ without VL providers falls back to text-only

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` but the VL providers do not resolve
- **WHEN** a query runs
- **THEN** the dual-space path SHALL be skipped
- **AND** retrieval SHALL use the unchanged text-only path
