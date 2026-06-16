# Delta spec: embed-cutover-reingest (C5, C6)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: The embed cutover SHALL fire reingest-all at most once

`backend/services/embed_cutover.py` SHALL, from `main.py` lifespan, fire the
`reingest-all` logic at most once for the GGUF-to-boofinity embed cutover,
guarded by a `global_settings` sentinel row with key
`'embed_cutover_boofinity_done'`. The sentinel SHALL be written
(`INSERT ... ON CONFLICT (key) DO NOTHING`) BEFORE the reingest is enqueued, so a
crash mid-reingest does not re-fire the whole corpus on the next boot.

#### Scenario: reingest fires once on first cutover boot

- **GIVEN** `global_settings` has no `embed_cutover_boofinity_done` row and the
  embed backend is ready
- **WHEN** lifespan runs the cutover
- **THEN** the `reingest-all` logic SHALL be invoked exactly once
- **AND** the sentinel `embed_cutover_boofinity_done` SHALL be set

#### Scenario: reingest does not re-fire on subsequent boots

- **GIVEN** the sentinel `embed_cutover_boofinity_done` already exists
- **WHEN** lifespan runs the cutover
- **THEN** the cutover SHALL no-op
- **AND** the `reingest-all` logic SHALL NOT be invoked

### Requirement: The cutover SHALL not fire until the embed backend is ready

The cutover SHALL verify, before firing reingest, that the embed
`bundled_models` row is `status = 'ready'` AND a live probe of the embed
provider through the front-door returns a 1024-length vector. If the backend is
not ready, the cutover SHALL return WITHOUT setting the sentinel, so the next
boot retries. This prevents re-embedding the corpus against a cold or down
backend (which would mark every source `error`).

#### Scenario: not-ready backend defers without consuming the sentinel

- **GIVEN** the embed `bundled_models` row is `status = 'pulling'`
- **WHEN** lifespan runs the cutover
- **THEN** reingest SHALL NOT be invoked
- **AND** the sentinel `embed_cutover_boofinity_done` SHALL remain absent

#### Scenario: probe failure defers without consuming the sentinel

- **GIVEN** the embed row is `ready` but the front-door embedding probe times out
- **WHEN** lifespan runs the cutover
- **THEN** reingest SHALL NOT be invoked
- **AND** the sentinel SHALL remain absent so a later boot retries

### Requirement: The cutover SHALL no-op on the external tier

When `system_profile.tier = 'external'` the cutover SHALL no-op and SHALL NOT set
the sentinel, because an external deployment owns its embedder and has no bundled
vectors to invalidate; a later switch to a bundled tier SHALL then still be able
to trigger.

#### Scenario: external tier skips cutover

- **GIVEN** `system_profile.tier = 'external'`
- **WHEN** lifespan runs the cutover
- **THEN** the cutover SHALL no-op
- **AND** the sentinel SHALL remain absent

### Requirement: A retrieval-rebuilding flag SHALL be exposed while reingest runs

When the cutover enqueues reingest it SHALL set
`global_settings['retrieval_rebuilding'] = 'true'`, and the ingest completion
path SHALL set it back to `'false'` once no source is in `processing`. The flag
SHALL be readable through a settings/system status endpoint so the frontend can
render a "Retrieval is rebuilding after a model change" banner.

#### Scenario: flag set on enqueue, cleared on completion

- **GIVEN** a ready embed backend and unfired cutover
- **WHEN** the cutover enqueues reingest
- **THEN** `global_settings['retrieval_rebuilding']` SHALL be `'true'`
- **AND** once every source finishes reingesting it SHALL be `'false'`

### Requirement: The reingest logic SHALL be callable from lifespan without FastAPI Depends

The body of `POST /api/sources/reingest-all` SHALL be factored into a reusable
`reingest_all_sources_impl(pool, audit=None)` callable that takes the pool
directly and uses NO FastAPI `Depends`. The existing endpoint
(`routers/sources.py:454-484`) resolves `Depends(get_principal)` and
`Depends(audit_event)`, which only bind inside a request; lifespan has no
request, so `embed_cutover.py` (run from lifespan) MUST call the plain impl, not
the endpoint. The `@router.post` endpoint SHALL delegate to the impl, and the
cutover SHALL call the impl directly so it does not make an HTTP request to its
own container (no curl is available in `hlh_api`).

#### Scenario: cutover calls impl directly

- **GIVEN** the cutover decides to reingest
- **WHEN** it triggers the rebuild
- **THEN** it SHALL call `reingest_all_sources_impl` directly
- **AND** SHALL NOT issue an HTTP request to `localhost`/`hlh_api`

#### Scenario: impl has no request-scoped Depends defaults

- **GIVEN** `reingest_all_sources_impl`
- **WHEN** its signature is read
- **THEN** no parameter SHALL default to a FastAPI `Depends(...)`
- **AND** it SHALL accept the connection pool as a parameter so lifespan can call it

### Requirement: A completion hook SHALL clear the rebuilding banner when reingest drains

The ingest path SHALL include a completion hook that, once no source remains in
`embedding_status = 'processing'`, sets
`global_settings['retrieval_rebuilding'] = 'false'`, so the "Retrieval is
rebuilding" banner clears after the cutover reingest finishes. The hook SHALL
live in the ingest completion path (not only in the manual endpoint) so a
lifespan-triggered cutover reingest also clears the flag.

#### Scenario: banner clears after the last source finishes reingesting

- **GIVEN** a cutover-triggered reingest is in progress with
  `global_settings['retrieval_rebuilding'] = 'true'`
- **WHEN** the last source transitions out of `processing`
- **THEN** the completion hook SHALL set `global_settings['retrieval_rebuilding']` to `'false'`
- **AND** the banner SHALL no longer render

### Requirement: doctor SHALL check the HF cache volume is writable

`backend/hlh/doctor.py` SHALL add `_check_infer_cache_writable()` that
probe-writes a file under `INFER_CACHE_DIR` (default `/cache`) and reports ERROR
with a `chown -R 1000:1000` remedy when the write fails, mirroring
`_check_models_writable`. It SHALL be registered in `run_checks()`.

#### Scenario: writable cache reports OK

- **GIVEN** `hlh_infer_cache` is writable by uid 1000
- **WHEN** `_check_infer_cache_writable` runs
- **THEN** it SHALL return status OK

#### Scenario: unwritable cache reports ERROR with remedy

- **GIVEN** `/cache` is root-owned and not writable by uid 1000
- **WHEN** `_check_infer_cache_writable` runs
- **THEN** it SHALL return status ERROR
- **AND** the detail SHALL mention `chown -R 1000:1000`

### Requirement: model_pulls doctor check SHALL cover the snapshot embed and rerank rows

`_check_model_pulls` SHALL surface the snapshot `embed` and `rerank`
`bundled_models` rows by status the same as file-pull rows: `pulling` -> WARN,
`failed` -> ERROR, `ready` counted. No special-casing of snapshot rows is
required.

#### Scenario: failed embed snapshot row reported as ERROR

- **GIVEN** the `embed` snapshot row has `status = 'failed'`
- **WHEN** `_check_model_pulls` runs
- **THEN** it SHALL return status ERROR
- **AND** the detail SHALL include `embed`
