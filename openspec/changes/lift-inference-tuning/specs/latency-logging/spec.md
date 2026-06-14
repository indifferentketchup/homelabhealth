# Delta spec: latency-logging (A2)

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: embeddings.py SHALL log per-call latency at DEBUG level

`backend/services/embeddings.py:_post()` SHALL log a debug line of the form
`"embed _post: n=<count> <ms>ms"` after each successful HTTP call to
`/v1/embeddings`. The timing SHALL use `time.monotonic()` brackets around the
`await client.post(...)` call. The log level SHALL be `DEBUG` so the line is
silent at the default INFO level. `import time` SHALL be added to the
top-level imports in `embeddings.py`.

#### Scenario: Timing line absent at default INFO log level

- **WHEN** an embedding call completes successfully
- **AND** `LOG_LEVEL` is unset (defaults to INFO)
- **THEN** `docker logs hlh_api` SHALL NOT contain `"embed _post:"` lines

#### Scenario: Timing line present at DEBUG log level

- **WHEN** an embedding call completes successfully
- **AND** `LOG_LEVEL=DEBUG` is set
- **THEN** the log output SHALL contain a line matching `"embed _post: n="`
  where the count and duration are positive integers

#### Scenario: py_compile passes after embeddings.py change

- **WHEN** `python3 -m py_compile backend/services/embeddings.py` is run
- **THEN** it SHALL exit 0 with no output

### Requirement: rag.py SHALL log per-call reranker latency at DEBUG level

`backend/services/rag.py:_rerank_infinity()` SHALL log a debug line of the
form `"rerank _rerank_infinity: <ms>ms"` after each successful HTTP call to
`/v1/rerank`. The timing SHALL use `time.monotonic()` brackets around the
`await client.post(...)` call. The log level SHALL be `DEBUG`. `time` is
already imported in `rag.py` and no new import is required.

#### Scenario: Reranker timing line present at DEBUG log level

- **WHEN** a rerank call completes successfully
- **AND** `LOG_LEVEL=DEBUG` is set
- **THEN** the log output SHALL contain a line matching
  `"rerank _rerank_infinity:"` with a positive integer duration in ms

#### Scenario: py_compile passes after rag.py change

- **WHEN** `python3 -m py_compile backend/services/rag.py` is run
- **THEN** it SHALL exit 0 with no output
