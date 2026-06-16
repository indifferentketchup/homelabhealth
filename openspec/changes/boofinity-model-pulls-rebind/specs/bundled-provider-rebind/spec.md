# Delta spec: bundled-provider-rebind (C2)

**Date:** 2026-06-16

## MODIFIED Requirements

### Requirement: Bundled chat, embed, and rerank providers SHALL point at the front-door

`backend/services/bundled_providers.py` SHALL set
`BUNDLED_CHAT_BASE_URL`, `BUNDLED_EMBED_BASE_URL`, and `BUNDLED_RERANK_BASE_URL`
all to `http://hlh_swap:9620`, the llama-swap front-door, replacing the prior
`http://hlh_chat:9610`. `BUNDLED_EMBED_MODEL` SHALL stay `"qwen3-embed"` and
`BUNDLED_RERANK_MODEL` SHALL stay `"qwen3-reranker"` (llama-swap routing
aliases). `apply_bundled_bindings` logic SHALL be otherwise unchanged.

#### Scenario: all three base URLs are the front-door

- **GIVEN** `bundled_providers`
- **WHEN** the three `*_BASE_URL` constants are read
- **THEN** each SHALL equal `"http://hlh_swap:9620"`

#### Scenario: routing aliases unchanged

- **GIVEN** `bundled_providers`
- **WHEN** `BUNDLED_EMBED_MODEL` and `BUNDLED_RERANK_MODEL` are read
- **THEN** they SHALL equal `"qwen3-embed"` and `"qwen3-reranker"` respectively

### Requirement: existing bundled provider rows SHALL self-heal to the front-door on boot

The bundled provider upsert SHALL rewrite the `base_url` of the three bundled
`providers` rows to `http://hlh_swap:9620` on the next lifespan boot after this
change, via `_upsert_bundled_row`'s
`ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url`, without any
manual edit, for a deployment whose rows previously stored `http://hlh_chat:9610`.

#### Scenario: stored row base_url updated idempotently

- **GIVEN** a deployment whose bundled embed provider row has
  `base_url = 'http://hlh_chat:9610'`
- **WHEN** `ensure_bundled_providers` runs at boot
- **THEN** that row's `base_url` SHALL become `'http://hlh_swap:9620'`
- **AND** running `ensure_bundled_providers` again SHALL leave it unchanged

#### Scenario: resolved embedding provider targets the front-door

- **GIVEN** the bundled embed provider is bound in `global_settings`
- **WHEN** `resolve_embedding_provider()` resolves it
- **THEN** the returned provider `base_url` SHALL be `"http://hlh_swap:9620"`
- **AND** no deprecated `EMBEDDING_URL` env var SHALL be consulted
