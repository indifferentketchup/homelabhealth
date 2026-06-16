# Delta spec: image-embedding-schema

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: source_image_embeddings table SHALL exist as an additive idempotent table

`backend/schema.sql` SHALL define a new table `source_image_embeddings` via
`CREATE TABLE IF NOT EXISTS`. The table SHALL carry: `id UUID PRIMARY KEY
DEFAULT gen_random_uuid()`, `source_id UUID NOT NULL REFERENCES sources(id) ON
DELETE CASCADE`, a page/image locator (`page_no INT` and `image_ref TEXT`),
`embedding vector(1024)`, and `created_at TIMESTAMPTZ DEFAULT NOW()`. The
`CREATE EXTENSION IF NOT EXISTS vector;` on line 3 of `schema.sql` already
precedes any `vector(N)` table, satisfying CLAUDE.md hard rule 4. The existing
`source_chunks` table and its index SHALL NOT be altered by this change.

#### Scenario: Table is created on a fresh DB

- **GIVEN** a fresh Postgres DB with `backend/schema.sql` applied at startup
- **WHEN** `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT to_regclass('source_image_embeddings')"` is run
- **THEN** the output SHALL be `source_image_embeddings` (not empty)
- **AND** the `embedding` column type SHALL be `vector` with 1024 dimensions

#### Scenario: Re-applying schema is a no-op

- **GIVEN** a DB that already has `source_image_embeddings`
- **WHEN** `backend/schema.sql` is applied a second time on startup
- **THEN** startup SHALL NOT raise (the `IF NOT EXISTS` guard makes it idempotent)
- **AND** `hlh_api` SHALL NOT crash-loop

#### Scenario: source_chunks is untouched

- **WHEN** the change is applied
- **THEN** `source_chunks` SHALL keep its `embedding vector(1024)` column and its
  `source_chunks_embedding_hnsw` index unchanged
- **AND** no `ALTER TABLE source_chunks` statement SHALL be added by this change

### Requirement: source_image_embeddings SHALL have an HNSW cosine index mirroring source_chunks

`backend/schema.sql` SHALL create an HNSW index on
`source_image_embeddings(embedding)` using `vector_cosine_ops`, mirroring the
existing `source_chunks_embedding_hnsw` index type. The index SHALL be created
with `CREATE INDEX IF NOT EXISTS source_image_embeddings_embedding_hnsw`. A
btree index on `source_id` SHALL also be created (`CREATE INDEX IF NOT EXISTS
source_image_embeddings_source_id_idx`) so per-source deletes and lookups do not
sequentially scan.

#### Scenario: HNSW cosine index exists

- **WHEN** `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT indexdef FROM pg_indexes WHERE indexname = 'source_image_embeddings_embedding_hnsw'"` is run
- **THEN** the output SHALL contain `USING hnsw`
- **AND** it SHALL contain `vector_cosine_ops`

#### Scenario: Index type matches source_chunks

- **GIVEN** `source_chunks_embedding_hnsw` uses `hnsw (embedding vector_cosine_ops)`
- **WHEN** the new index is compared
- **THEN** `source_image_embeddings_embedding_hnsw` SHALL use the same access
  method (`hnsw`) and the same operator class (`vector_cosine_ops`)

### Requirement: Deleting a source SHALL cascade-delete its image embeddings

The `source_id` foreign key SHALL be declared `ON DELETE CASCADE` so that
deleting a row from `sources` removes every `source_image_embeddings` row that
references it, matching the existing `source_chunks` cascade behavior. No
application-level delete of `source_image_embeddings` rows SHALL be required in
the sources delete path.

#### Scenario: FK cascade removes image rows on source delete

- **GIVEN** a source with one or more `source_image_embeddings` rows
- **WHEN** the source is deleted via `DELETE FROM sources WHERE id = $1`
- **THEN** every `source_image_embeddings` row with that `source_id` SHALL be
  deleted by the database
- **AND** a follow-up `SELECT count(*) FROM source_image_embeddings WHERE source_id = $1`
  SHALL return 0

### Requirement: source_image_embeddings SHALL inherit the source-scoped access and audit of source_chunks

`source_image_embeddings` rows SHALL be reachable only through their parent
`sources` row, with the same source-scoped access control and audit as
`source_chunks`, because the vectors derive from medical images (PHI-adjacent).
This change SHALL NOT add any endpoint that returns raw image vectors and SHALL
NOT introduce a separate auth or audit surface for the table; access and delete
happen via the already-controlled `sources` path (FK `ON DELETE CASCADE`). The
verify step SHALL confirm no read path for `source_image_embeddings` exists
outside the existing source-scoped guard.

#### Scenario: no new unguarded read path is introduced

- **WHEN** the change is applied
- **THEN** no endpoint SHALL return `source_image_embeddings` rows or raw vectors
  outside the existing source-scoped access control
- **AND** no separate audit surface SHALL be added for `source_image_embeddings`
  beyond what already covers `source_chunks` via the `sources` row
