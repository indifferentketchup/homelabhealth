# Delta spec: boofinity-rerank-contract (C3, C4)

**Date:** 2026-06-16

## MODIFIED Requirements

### Requirement: _rerank_infinity SHALL use boofinity's /rerank contract

`backend/services/rag.py`'s `_rerank_infinity` SHALL `POST {base_url}/v1/rerank`
with a body whose `documents` field is a list of strings
(`[p["text"] for p in passages]`), NOT a list of objects. It SHALL parse the
response `results` array, where each result carries an integer `index` (into the
input documents) and a numeric `relevance_score`, mapping each result back to
`passages[index]` and attaching `score = float(relevance_score)`. Out-of-range
indices SHALL be skipped.

#### Scenario: request sends documents as a list of strings

- **GIVEN** three passages
- **WHEN** `_rerank_infinity` builds its request body
- **THEN** `documents` SHALL be `["<text0>", "<text1>", "<text2>"]`
- **AND** no element of `documents` SHALL be a dict

#### Scenario: response relevance_score and index are parsed

- **GIVEN** a boofinity `/rerank` response
  `{"results": [{"index": 1, "relevance_score": 0.92}, {"index": 0, "relevance_score": 0.10}]}`
- **WHEN** `_rerank_infinity` parses it for two passages
- **THEN** the first returned item SHALL be `passages[1]` with `score == 0.92`
- **AND** the second SHALL be `passages[0]` with `score == 0.10`

#### Scenario: out-of-range index dropped

- **GIVEN** a response containing a result with `index` >= number of passages
- **WHEN** `_rerank_infinity` parses it
- **THEN** that result SHALL be skipped, not raise

### Requirement: _rerank_infinity SHALL preserve the soft-fallback to similarity order

`_rerank_infinity` SHALL return `None` on an empty result set or on ANY
exception (resolve failure, network error, `raise_for_status`, JSON parse
error), so the caller falls back to flashrank and then to similarity order. A
misconfigured or mid-swap reranker SHALL NOT break a RAG-enabled chat turn.

#### Scenario: backend error degrades, does not raise

- **GIVEN** the front-door returns HTTP 503 during a backend swap
- **WHEN** `_rerank_infinity` runs
- **THEN** it SHALL return `None`
- **AND** the caller SHALL fall back to flashrank then similarity order

#### Scenario: empty results return None

- **GIVEN** a `/rerank` response with `results: []`
- **WHEN** `_rerank_infinity` parses it
- **THEN** it SHALL return `None`

### Requirement: embeddings SHALL resolve 1024-dim vectors from the front-door

`backend/services/embeddings.py`'s `_post` SHALL `POST {base_url}/v1/embeddings`
with `{"model", "input": [...]}` and read `data[].embedding`, where `base_url`
is the front-door (`http://hlh_swap:9620`) resolved through the bundled embed
provider. boofinity launched with the `--url-prefix /v1` CLI flag (folder B)
serves the OpenAI `/v1/embeddings` route and returns 1024-dim vectors for
Qwen3-Embedding-0.6B; the existing `len(emb) == EMBEDDING_DIM` (1024) guard
SHALL be retained.

#### Scenario: live embedding from the front-door is 1024-dim

- **GIVEN** the bundled embed provider points at `http://hlh_swap:9620`
- **WHEN** `_post` requests an embedding for one input
- **THEN** the returned vector SHALL have length 1024
- **AND** a non-1024 length SHALL raise `EmbeddingError`
