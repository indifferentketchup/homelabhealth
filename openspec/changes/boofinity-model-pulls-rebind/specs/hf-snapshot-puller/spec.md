# Delta spec: hf-snapshot-puller (C1)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: ModelSpec SHALL support a repo-only snapshot variant

`backend/services/model_puller.py`'s `ModelSpec` dataclass SHALL support a
`kind` field with values `"file"` (default, existing single-file GGUF behavior)
and `"snapshot"` (whole-repo HuggingFace snapshot). A snapshot spec SHALL derive
`model_id` as `f"{self.repo}@snapshot"` so it is stable without a single
filename, and `kind="file"` specs SHALL keep `model_id` as
`f"{self.repo}@{self.filename}"`.

#### Scenario: snapshot spec model_id

- **GIVEN** a `ModelSpec(repo="Qwen/Qwen3-Embedding-0.6B", kind="snapshot")`
- **WHEN** `.model_id` is read
- **THEN** it SHALL equal `"Qwen/Qwen3-Embedding-0.6B@snapshot"`

#### Scenario: file spec model_id unchanged

- **GIVEN** a `ModelSpec(repo="r", filename="f.gguf")` with default `kind`
- **WHEN** `.model_id` is read
- **THEN** it SHALL equal `"r@f.gguf"`

### Requirement: snapshot_download SHALL write the HF hub cache layout into hlh_infer_cache

For a `kind="snapshot"` spec, the puller SHALL call
`huggingface_hub.snapshot_download(repo_id, revision, cache_dir=<INFER_CACHE_DIR>/hub, token=...)`
inside a thread (`asyncio.to_thread`) while holding `_PULL_LOCK`, where
`INFER_CACHE_DIR` defaults to `/cache` and is overridable via
`HLH_INFER_CACHE_DIR`. After a successful pull the repo SHALL exist on disk in
the standard hub layout `models--<org>--<repo>/snapshots/<commit>/`, so a
boofinity process running with `HF_HOME=/cache` and `HF_HUB_OFFLINE=1` resolves
the model without network access.

#### Scenario: snapshot lands in hub cache layout

- **GIVEN** `_EMBED_SPEC` is a snapshot spec for `Qwen/Qwen3-Embedding-0.6B`
- **WHEN** its `bundled_models` row is pulled to completion
- **THEN** `<INFER_CACHE_DIR>/hub/models--Qwen--Qwen3-Embedding-0.6B/snapshots/`
  SHALL contain at least one commit directory with `config.json`
- **AND** the row SHALL reach `status = 'ready'`

#### Scenario: snapshot pull holds the single-pull lock

- **GIVEN** a snapshot pull is in progress
- **WHEN** `is_pulling()` is called
- **THEN** it SHALL return `True`
- **AND** no second pull (file or snapshot) SHALL start until it completes

#### Scenario: offline boofinity resolves the snapshot

- **GIVEN** the embed snapshot is present in `hlh_infer_cache`
- **WHEN** `hlh_infer` starts with `HF_HUB_OFFLINE=1`
- **THEN** its `/health` SHALL reach 200 without any outbound HuggingFace request

### Requirement: bootstrap SHALL ensure the hlh_infer_cache volume is uid-1000 writable

`hlh_orchestra/bootstrap.py` SHALL gain an `ensure_infer_cache_ownership()`
function, analogous to `ensure_models_ownership()` (`bootstrap.py:228-249`), that
idempotently `chown -R 1000:1000`s the `hlh_infer_cache` volume (mounted at
`/cache`) via a throwaway root container, and SHALL call it in the bootstrap
sequence. The `hlh_api` service SHALL mount `hlh_infer_cache:/cache` so the
puller (which runs in `hlh_api`) can write the snapshot that boofinity reads;
this `hlh_api` mount is added by THIS folder (C), while the named volume is
declared by folder B.

#### Scenario: bootstrap chowns the infer cache volume

- **GIVEN** a populated root-owned `hlh_infer_cache` volume
- **WHEN** `ensure_infer_cache_ownership()` runs
- **THEN** the volume root SHALL become owned by uid 1000
- **AND** re-running it SHALL be idempotent (no error on an already-correct volume)

#### Scenario: hlh_api mounts the infer cache so the puller can write

- **GIVEN** `docker-compose.yml` after folder C
- **WHEN** the `hlh_api` service volumes are read
- **THEN** `hlh_infer_cache` SHALL be mounted at `/cache`

### Requirement: snapshot specs SHALL skip single-file disk and sha256 checks

The puller SHALL skip `_check_disk_space` and the single-file sha256
verification for `kind="snapshot"` specs, because a snapshot has no single
`expected_bytes` or single `sha256`, logging the skip the same way the existing
`expected_bytes is None` path does. Per-file integrity SHALL be delegated to
`huggingface_hub`.

#### Scenario: snapshot pull does not raise InsufficientDiskError on unknown size

- **GIVEN** a snapshot spec with no `expected_bytes`
- **WHEN** it is pulled
- **THEN** the puller SHALL NOT raise `InsufficientDiskError` for the snapshot
- **AND** SHALL log that the disk pre-flight was skipped

## MODIFIED Requirements

### Requirement: ALL_ROLES SHALL include every MODEL_REGISTRY role

`backend/services/model_puller.py` `ALL_ROLES` SHALL include `"tasks"`, which is
already a `MODEL_REGISTRY` key but is currently absent from `ALL_ROLES`. The set
of `ALL_ROLES` SHALL be a subset of (and for the non-VL roles, equal to) the
`MODEL_REGISTRY` keys so `verify_model_puller.py`'s
`set(MODEL_REGISTRY.keys()) == set(ALL_ROLES)` assertion holds (the VL roles
`embed-vl` / `rerank-vl` are added by folder D, which extends both in lockstep).

#### Scenario: tasks is a recognized role

- **GIVEN** `backend/services/model_puller.py`
- **WHEN** `ALL_ROLES` is read
- **THEN** it SHALL contain `"tasks"`
- **AND** every member of `ALL_ROLES` SHALL be a key in `MODEL_REGISTRY`

### Requirement: _EMBED_SPEC and _RERANK_SPEC SHALL be boofinity safetensors snapshots

`_EMBED_SPEC` SHALL be `ModelSpec(repo="Qwen/Qwen3-Embedding-0.6B", kind="snapshot", ...)`
and `_RERANK_SPEC` SHALL be `ModelSpec(repo="Qwen/Qwen3-Reranker-0.6B", kind="snapshot", ...)`,
replacing the prior flat GGUF specs (`Qwen/Qwen3-Embedding-0.6B-GGUF@...gguf`
and `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF@...gguf`). Both SHALL keep
`license = "apache-2.0"` and `revision = "main"`. `embed` and `rerank` SHALL be
removed from `_FLAT_DEST_ROLES` so `_dest_path` no longer routes them to flat
`/models/<file>`.

#### Scenario: embed and rerank are snapshot specs

- **GIVEN** `model_puller._EMBED_SPEC` and `model_puller._RERANK_SPEC`
- **WHEN** their `kind` is read
- **THEN** both SHALL equal `"snapshot"`
- **AND** `_EMBED_SPEC.repo` SHALL equal `"Qwen/Qwen3-Embedding-0.6B"`
- **AND** `_RERANK_SPEC.repo` SHALL equal `"Qwen/Qwen3-Reranker-0.6B"`

#### Scenario: embed and rerank no longer flat-dest roles

- **GIVEN** `model_puller._FLAT_DEST_ROLES`
- **WHEN** the set is read
- **THEN** it SHALL NOT contain `"embed"` or `"rerank"`
- **AND** it SHALL still contain `"chat"` and `"tasks"`

### Requirement: seed_registry SHALL prune retired GGUF embed and rerank rows

`seed_registry`'s existing orphan prune SHALL delete the prior GGUF
`bundled_models` rows whose `(role, tier, model_id)` is no longer in
`MODEL_REGISTRY` after embed/rerank flip to snapshot model_ids, and SHALL upsert
the new snapshot rows.

#### Scenario: old GGUF rows pruned, snapshot rows present

- **GIVEN** a database seeded under the prior flat-GGUF embed/rerank specs
- **WHEN** `seed_registry` runs after this change
- **THEN** no `bundled_models` row SHALL have `model_id` ending in `.gguf` for
  `role IN ('embed','rerank')`
- **AND** a row with `model_id = 'Qwen/Qwen3-Embedding-0.6B@snapshot'` and
  `role = 'embed'` SHALL exist
- **AND** a row with `model_id = 'Qwen/Qwen3-Reranker-0.6B@snapshot'` and
  `role = 'rerank'` SHALL exist
