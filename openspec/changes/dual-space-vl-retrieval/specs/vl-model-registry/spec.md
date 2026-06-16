# Delta spec: vl-model-registry

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: bundled_models.role CHECK SHALL admit embed-vl and rerank-vl on fresh and existing DBs

`backend/schema.sql` SHALL widen the `bundled_models.role` CHECK to include
`embed-vl` and `rerank-vl` using the dual-update pattern (precedent:
`providers_role_check`, `schema.sql:388-390`): BOTH the inline `CREATE TABLE
bundled_models` CHECK list AND the idempotent
`ALTER TABLE bundled_models DROP CONSTRAINT IF EXISTS bundled_models_role_check;
ALTER TABLE bundled_models ADD CONSTRAINT bundled_models_role_check CHECK (role
IN (...))` SHALL list the two new values alongside the existing roles. Updating
only one of the two causes a `CheckViolationError` at `seed_registry` time on
the unupdated path (fresh DB uses the inline CHECK; existing DB uses the ALTER),
crash-looping `hlh_api`.

#### Scenario: embed-vl row seeds on a fresh DB

- **GIVEN** a fresh DB with `backend/schema.sql` applied
- **WHEN** `seed_registry` inserts the `embed-vl` / `gpu-24gb+` row
- **THEN** the INSERT SHALL succeed without a `CheckViolationError`
- **AND** `hlh_api` SHALL NOT crash-loop on boot

#### Scenario: rerank-vl row seeds on an existing DB

- **GIVEN** an existing DB created before this change (its CHECK lacks the VL roles)
- **WHEN** the new `ALTER TABLE ... DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT`
  runs at startup, then `seed_registry` inserts the `rerank-vl` / `gpu-24gb+` row
- **THEN** the ALTER SHALL widen the constraint and the INSERT SHALL succeed
- **AND** `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT count(*) FROM bundled_models WHERE role IN ('embed-vl','rerank-vl')"` SHALL return a positive integer on `gpu-24gb+`

#### Scenario: Both CHECK definitions list the VL roles

- **WHEN** `backend/schema.sql` is read
- **THEN** the inline `CREATE TABLE bundled_models` CHECK SHALL contain `embed-vl` and `rerank-vl`
- **AND** the `ADD CONSTRAINT bundled_models_role_check` CHECK SHALL contain `embed-vl` and `rerank-vl`

### Requirement: MODEL_REGISTRY SHALL define VL specs only on gpu-24gb+

`backend/services/model_puller.py` `MODEL_REGISTRY` SHALL gain an `embed-vl`
role mapping `gpu-24gb+` to a `ModelSpec` for `Qwen/Qwen3-VL-Embedding-2B`, and
a `rerank-vl` role mapping `gpu-24gb+` to a `ModelSpec` for
`Qwen/Qwen3-VL-Reranker-2B`. Every other tier (`cpu-min`, `cpu-std`, `gpu-4gb`,
`gpu-8gb`, `gpu-16gb`, `apple-mlx`, `external`) for both roles SHALL be `None`,
so `seed_registry` skips them and no lesser tier ever pulls a ~2B VL model. The
artifacts SHALL be fetched through folder C's HF-snapshot path (a directory
snapshot, not a single flat GGUF), so these roles SHALL NOT be added to
`_FLAT_DEST_ROLES`.

#### Scenario: VL roles seed exactly one tier each

- **WHEN** `seed_registry` runs against any DB
- **THEN** `SELECT DISTINCT tier FROM bundled_models WHERE role = 'embed-vl'`
  SHALL return only `gpu-24gb+`
- **AND** `SELECT DISTINCT tier FROM bundled_models WHERE role = 'rerank-vl'`
  SHALL return only `gpu-24gb+`

#### Scenario: Non-gpu tier seeds no VL rows

- **GIVEN** the active tier is `cpu-std` (or any tier other than `gpu-24gb+`)
- **WHEN** `seed_registry` runs and `pull_for_tier` is invoked for that tier
- **THEN** no `embed-vl` or `rerank-vl` artifact SHALL be pulled for that tier
- **AND** the `bundled_models` rows for those roles SHALL remain `gpu-24gb+`-only
  regardless of the active tier (the registry is tier-keyed, not active-tier-keyed)

#### Scenario: VL specs target the Qwen3-VL repos

- **WHEN** `backend/services/model_puller.py` `MODEL_REGISTRY` is read
- **THEN** the `embed-vl` / `gpu-24gb+` `ModelSpec.repo` SHALL be `Qwen/Qwen3-VL-Embedding-2B`
- **AND** the `rerank-vl` / `gpu-24gb+` `ModelSpec.repo` SHALL be `Qwen/Qwen3-VL-Reranker-2B`

### Requirement: ALL_ROLES SHALL gain embed-vl and rerank-vl consistently with MODEL_REGISTRY

`backend/services/model_puller.py` `ALL_ROLES` SHALL add `'embed-vl'` and
`'rerank-vl'` so the new VL roles are recognized project-wide and
`verify_model_puller.py`'s `set(MODEL_REGISTRY.keys()) == set(ALL_ROLES)`
assertion still holds after both sets gain the VL roles. Folder C adds `'tasks'`
to `ALL_ROLES`; this folder's two additions SHALL be kept consistent with that so
the union equals the `MODEL_REGISTRY` keys (the dependency on folder C's `tasks`
addition is noted in tasks.md).

#### Scenario: ALL_ROLES and MODEL_REGISTRY agree after the VL additions

- **GIVEN** `backend/services/model_puller.py` with folder C's `tasks` and this
  folder's `embed-vl` / `rerank-vl` additions applied
- **WHEN** `ALL_ROLES` and `MODEL_REGISTRY` keys are compared
- **THEN** `set(ALL_ROLES)` SHALL equal `set(MODEL_REGISTRY.keys())`
- **AND** both SHALL contain `embed-vl` and `rerank-vl`

### Requirement: Bundled VL embed and rerank providers SHALL be seeded on gpu-24gb+

`backend/services/bundled_providers.py` SHALL define `BUNDLED_VL_EMBED_*` and
`BUNDLED_VL_RERANK_*` constants (base_url `http://hlh_swap:9620`, models
`qwen3-vl-embed` / `qwen3-vl-rerank`) and SHALL upsert `embed-vl` and `rerank-vl`
provider rows ONLY on the `gpu-24gb+` tier, wiring them through
`apply_bundled_bindings` so `vision.py` and `rag.py` can resolve them by role. On
lesser tiers the rows SHALL NOT be seeded and the VL path SHALL no-op. The
`providers_role_check` constraint (`schema.sql:388-390`) SHALL be widened with
`embed-vl` and `rerank-vl` using the idempotent
`DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT` pattern, or the provider upsert
raises `CheckViolationError` and crash-loops `hlh_api`.

#### Scenario: VL embed provider resolves on gpu-24gb+

- **GIVEN** `system_profile.tier = 'gpu-24gb+'` after `apply_bundled_bindings`
- **WHEN** the `embed-vl` provider is resolved
- **THEN** a provider row with role `embed-vl`, `base_url = 'http://hlh_swap:9620'`,
  and model `qwen3-vl-embed` SHALL resolve

#### Scenario: VL providers absent on lesser tiers

- **GIVEN** `system_profile.tier = 'cpu-std'` (or any tier other than `gpu-24gb+`)
- **WHEN** `ensure_bundled_providers` runs
- **THEN** no `embed-vl` or `rerank-vl` provider row SHALL be seeded
- **AND** the VL retrieval and ingestion paths SHALL no-op because the provider does not resolve

#### Scenario: providers_role_check admits the VL roles

- **WHEN** `backend/schema.sql` is read
- **THEN** the `providers_role_check` CHECK SHALL include `embed-vl` and `rerank-vl`
- **AND** inserting a bundled `embed-vl` provider row SHALL NOT raise `CheckViolationError`

### Requirement: seed_registry pruning SHALL NOT drop the VL rows once defined

The `embed-vl` / `gpu-24gb+` and `rerank-vl` / `gpu-24gb+` rows SHALL be in the
`valid` set of `seed_registry`'s prune step (`model_puller.py:280-300`) and SHALL
survive the prune sweep on every boot, because both VL specs are present in
`MODEL_REGISTRY`.

#### Scenario: VL rows survive the prune sweep

- **GIVEN** `MODEL_REGISTRY` defines the two VL specs
- **WHEN** `seed_registry` runs its prune step
- **THEN** the `embed-vl` / `gpu-24gb+` and `rerank-vl` / `gpu-24gb+` rows SHALL NOT
  appear in the `stale` delete list
- **AND** they SHALL still exist after the sweep
