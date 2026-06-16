# Delta spec: vl-ingestion

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: On gpu-24gb+ ingestion SHALL also write native image embeddings

On the `gpu-24gb+` tier, ingestion SHALL ALSO embed the rendered image bytes
through boofinity `/v1/mm_embeddings` (model `qwen3-vl-embed`) and write the
resulting vector into `source_image_embeddings`, with `page_no` and `image_ref`
identifying the page or image. This SHALL be driven by `backend/routers/sources.py`
via a helper in `backend/services/vision.py`, for an image source or each PDF
page. The active tier SHALL be read from `system_profile WHERE id = 1`
(the same source `inference_job.py:426` and `routers/inference.py:49` use). This
path SHALL run in addition to the existing MedGemma-read-to-text path, not in
place of it.

#### Scenario: gpu-24gb+ image ingest writes a vector

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` and the VL embed provider is configured
- **WHEN** an image source finishes ingesting
- **THEN** at least one `source_image_embeddings` row SHALL exist for that `source_id`
- **AND** its `embedding` SHALL be non-NULL with 1024 dimensions

#### Scenario: PDF pages each get an image vector

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` and a multi-page PDF source
- **WHEN** the PDF finishes ingesting
- **THEN** `source_image_embeddings` SHALL contain one row per rendered page,
  each with a distinct `page_no`

### Requirement: The MedGemma-read-to-text path SHALL remain unchanged on every tier

The existing text path SHALL remain unchanged: `extract_image_via_vision` /
`extract_pdf_via_vision` (`backend/services/vision.py`) that feeds `source_chunks`.
On `gpu-24gb+` both the text path and the image-embedding path run; on every
lesser tier only the text path runs. A failure of the image-embedding pass
SHALL NOT fail the ingest - the text path result and `source_chunks` write are
the source of truth for `embedding_status`.

#### Scenario: Text path still feeds source_chunks on gpu-24gb+

- **GIVEN** `system_profile.tier = 'gpu-24gb+'`
- **WHEN** an image source is ingested
- **THEN** `source_chunks` SHALL still receive the MedGemma-transcribed text chunks
- **AND** `sources.embedding_status` SHALL be `complete` when the text path succeeds

#### Scenario: Image-embed failure does not fail the ingest

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` and the VL embed call raises or times out
- **WHEN** the source is ingested
- **THEN** the text path SHALL still complete and set `embedding_status = 'complete'`
- **AND** the ingest SHALL NOT be marked `error` solely because the image-embed pass failed

### Requirement: No image embeddings SHALL be written below gpu-24gb+

On any tier other than `gpu-24gb+`, ingestion SHALL NOT call
`/v1/mm_embeddings` and SHALL NOT write any `source_image_embeddings` row. The
gate SHALL require BOTH `system_profile.tier == 'gpu-24gb+'` AND the VL embed
provider being configured; if either is absent the image-embedding pass SHALL be
skipped silently.

#### Scenario: cpu-std ingest writes zero image rows

- **GIVEN** `system_profile.tier = 'cpu-std'`
- **WHEN** an image source is ingested
- **THEN** `SELECT count(*) FROM source_image_embeddings WHERE source_id = $1`
  SHALL return 0
- **AND** no `/v1/mm_embeddings` request SHALL be issued

#### Scenario: gpu-24gb+ without VL provider configured skips the pass

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` but no VL embed provider resolves
- **WHEN** an image source is ingested
- **THEN** the image-embedding pass SHALL be skipped without raising
- **AND** the text path SHALL still complete normally

### Requirement: Image vectors SHALL be matryoshka-sliced to 1024 dimensions

The ingestion path SHALL reduce the Qwen3-VL-Embedding-2B vector to exactly 1024
dimensions before insert (the `source_image_embeddings.embedding` column is
`vector(1024)` while the model emits a wider native vector), by requesting
`dimensions=1024` from `/v1/mm_embeddings` when boofinity honors it, otherwise
slicing the first 1024 components client-side (matryoshka prefix). The chosen
method SHALL be documented in `design.md`, and the same method SHALL be used for
the query embed at retrieval so ingest and query vectors are slice-consistent.

#### Scenario: Stored vector is exactly 1024-dim

- **WHEN** an image vector is inserted on `gpu-24gb+`
- **THEN** the inserted `embedding` SHALL have exactly 1024 dimensions
- **AND** the insert SHALL NOT raise a pgvector dimension-mismatch error

#### Scenario: Slice method is consistent between ingest and query

- **GIVEN** the documented slicing method (request `dimensions=1024` or first-1024 prefix)
- **WHEN** both the ingestion embed and the retrieval query embed run
- **THEN** both SHALL apply the same reduction so the two 1024-dim vectors occupy
  the same matryoshka subspace

### Requirement: The VL embed helper SHALL guard against a native dimension below 1024

The VL embed helper SHALL error clearly when the native vector returned by
`/v1/mm_embeddings` has length `< 1024` (so the first-1024 prefix slice is
impossible), naming the role and the observed length, rather than inserting a
short vector that pgvector rejects with an opaque dimension-mismatch. The native
output dimension of `Qwen3-VL-Embedding-2B` and whether boofinity honors a
`dimensions=1024` request parameter SHALL be determined and recorded; if the
parameter is honored the helper SHALL request `dimensions=1024`, otherwise it
SHALL slice the first 1024 components.

#### Scenario: native dim below 1024 raises a clear error

- **GIVEN** `/v1/mm_embeddings` returns a vector of length less than 1024
- **WHEN** the VL embed helper processes it
- **THEN** it SHALL raise (or soft-fail to `None`) with a message naming the role
  and the observed length
- **AND** it SHALL NOT insert a vector shorter than 1024 into `source_image_embeddings`

#### Scenario: dimensions parameter honored yields a server-reduced 1024 vector

- **GIVEN** boofinity `/v1/mm_embeddings` honors a `dimensions=1024` request
- **WHEN** the helper requests `dimensions=1024`
- **THEN** the returned vector SHALL be exactly 1024-dim
- **AND** the client-side first-1024 slice SHALL be a no-op on it
