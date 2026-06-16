# Delta spec: boofinity-service (B1, B2, B4)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: boofinity SHALL run as a child process of hlh_swap

boofinity SHALL run as a **child process launched by llama-swap inside the
`hlh_swap` container**, not as a standalone service. Its `cmd:` in
`hlh_swap/config.yaml` SHALL invoke `boofinity v2` with repeated `--model-id`
flags, `--device cpu|cuda`, `--url-prefix /v1`, and a `--port` bound to the
local `${PORT}` llama-swap assigns. There SHALL be no separate `hlh_infer`
container.

#### Scenario: boofinity is a child cmd, not a container

- **GIVEN** `docker-compose.yml`
- **WHEN** the services are rendered for either bundled profile
- **THEN** there SHALL be no `hlh_infer` service
- **AND** `hlh_swap/config.yaml` SHALL contain a `cmd` invoking `boofinity v2`

#### Scenario: boofinity child binds a local port behind the front-door

- **GIVEN** the boofinity child's `cmd`
- **WHEN** it is read
- **THEN** it SHALL include a `--port` bound to the llama-swap-assigned local port
- **AND** the boofinity child SHALL be reachable only through `hlh_swap:9620`, never on a published host port

#### Scenario: GPU variant runs the boofinity child on cuda with float32

- **GIVEN** the CUDA combined image's boofinity child `cmd`
- **WHEN** it is read
- **THEN** it SHALL include `--device cuda`
- **AND** it SHALL include a `--dtype` whose default resolves to `float32`
- **AND** the `hlh_swap_gpu` service SHALL declare `deploy.resources.reservations.devices` with `driver: nvidia` and `count: 1`

### Requirement: boofinity child SHALL pass --url-prefix /v1 so OpenAI-compat routes are under /v1

The boofinity child's `cmd` SHALL pass the boofinity CLI flag `--url-prefix /v1`
(boofinity `cli.py:252` supports the flag) so every boofinity route is moved
under `/v1`. boofinity's `url_prefix` defaults to the empty string
(`/opt/boofinity/libs/boofinity/boofinity/env.py:207-208`, `default=""`), so
without the flag boofinity serves its routes at `/embeddings`, `/rerank`,
`/mm_embeddings`, and `/mm_rerank` with no `/v1` prefix and the HLH clients
(which post to `/v1/...` through `hlh_swap`) would 404. The flag is therefore
load-bearing. No `INFINITY_*` environment variable SHALL be set; the prefix is
configured exclusively through the CLI flag.

#### Scenario: --url-prefix /v1 is passed on the boofinity child

- **GIVEN** the boofinity child's `cmd` in `hlh_swap/config.yaml`
- **WHEN** it is read
- **THEN** it SHALL include `--url-prefix` followed by `/v1`
- **AND** no `INFINITY_*` environment variable SHALL be set in HLH config

#### Scenario: all four OpenAI-compat routes are reachable through hlh_swap

- **GIVEN** the boofinity child running with `--url-prefix /v1` behind llama-swap
- **WHEN** a client posts to the front-door `/v1/embeddings`, `/v1/rerank`,
  `/v1/mm_embeddings`, and `/v1/mm_rerank`
- **THEN** llama-swap SHALL route each request to the boofinity child (not 404)
- **AND** with the `--url-prefix` flag omitted (boofinity default empty prefix)
  those `/v1/...` routes SHALL NOT resolve, confirming the flag is load-bearing

### Requirement: boofinity child GPU cmd SHALL load both VL models

On GPU builds, the boofinity child's `cmd` SHALL pass `--model-id
Qwen/Qwen3-VL-Embedding-2B` AND `--model-id Qwen/Qwen3-VL-Reranker-2B` alongside
the text embed and rerank model ids, so boofinity serves both VL roles. The two
VL model ids are `Qwen/Qwen3-VL-Embedding-2B` (embed-vl) and
`Qwen/Qwen3-VL-Reranker-2B` (rerank-vl).

#### Scenario: GPU child cmd includes both VL model ids

- **GIVEN** the CUDA combined image's boofinity child `cmd`
- **WHEN** it is read
- **THEN** it SHALL include `--model-id Qwen/Qwen3-VL-Embedding-2B`
- **AND** it SHALL include `--model-id Qwen/Qwen3-VL-Reranker-2B`

### Requirement: boofinity child dtype SHALL be operator-overridable with a float32 default

The boofinity child's GPU `cmd` SHALL select the dtype via
`--dtype ${HLH_INFER_DTYPE:-float32}` so the default is `float32` (Pascal-safe)
and an operator on Ampere or newer can set `HLH_INFER_DTYPE=bfloat16`.
`HLH_INFER_DTYPE` SHALL be a `write_tier_env` managed key seeded to `float32`.

#### Scenario: dtype defaults to float32 and is overridable

- **GIVEN** the boofinity child's GPU `cmd`
- **WHEN** the `--dtype` argument is read
- **THEN** it SHALL resolve to `float32` when `HLH_INFER_DTYPE` is unset
- **AND** it SHALL resolve to the value of `HLH_INFER_DTYPE` when that env var is set

### Requirement: hlh_swap SHALL use an offline HF cache volume

`hlh_swap` SHALL mount the named volume `hlh_infer_cache` at `/cache` and SHALL
set `HF_HOME=/cache`, `HOME=/cache`, and `HF_HUB_OFFLINE=1` so the boofinity
child loads weights from the cache without reaching the network.

#### Scenario: cache volume and offline env present

- **GIVEN** the `hlh_swap` service definition
- **WHEN** its volumes and environment are read
- **THEN** it SHALL mount `hlh_infer_cache` at `/cache`
- **AND** it SHALL set `HF_HOME` to `/cache`
- **AND** it SHALL set `HF_HUB_OFFLINE` to `1`
- **AND** `docker-compose.yml` SHALL declare the `hlh_infer_cache` volume

### Requirement: hlh_swap SHALL keep the read_only hardening profile

`hlh_swap` SHALL set `read_only: true`, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, `user: "1000:1000"`, and tmpfs at
`/tmp` and `/run`, with the documented `LD_LIBRARY_PATH=/app` (llama.cpp child
libs) and `HOME=/cache` (boofinity child caches) exceptions. Because the
child-process topology mounts no Docker socket, no read_only exception is needed
for socket access.

#### Scenario: hlh_swap is hardened read-only

- **GIVEN** a running `hlh_swap` container
- **WHEN** `docker inspect hlh_swap` is read
- **THEN** `.HostConfig.ReadonlyRootfs` SHALL be `true`
- **AND** `.HostConfig.CapDrop` SHALL contain `ALL`
- **AND** `.HostConfig.SecurityOpt` SHALL contain `no-new-privileges:true`
- **AND** no bind SHALL target `/var/run/docker.sock`

### Requirement: hlh_swap healthcheck SHALL gate readiness on the llama-swap endpoint

`hlh_swap`'s healthcheck SHALL probe llama-swap's readiness endpoint on
`http://localhost:9620` using the image's bundled `python` interpreter. Per-child
readiness (a 200 on each child's `/health` after its models finish loading) is
llama-swap's concern before it routes. The healthcheck SHALL allow a
`start_period` of at least 120 seconds for cold child load.

#### Scenario: healthcheck probes the front-door with a cold-load grace

- **GIVEN** the `hlh_swap` service definition
- **WHEN** its healthcheck is read
- **THEN** `healthcheck.test` SHALL probe `http://localhost:9620` via `python`
- **AND** `healthcheck.start_period` SHALL be at least `120s`

## MODIFIED Requirements

### Requirement: image_config SHALL manage the combined swap image and tier-scaled infer memory

`backend/services/image_config.py` SHALL add `HLH_SWAP_IMAGE` and
`HLH_INFER_MEM` to `_MANAGED_KEYS` and SHALL write both in `write_tier_env`.
`HLH_SWAP_IMAGE` SHALL be the combined-image tag
`ghcr.io/indifferentketchup/hlh-swap:<ver>-cpu` on CPU tiers and `...-cuda` on
GPU tiers, replacing the former separate `HLH_CHAT_IMAGE` / `HLH_INFER_IMAGE`
pair. `HLH_INFER_MEM` SHALL be a per-tier memory string scaled to the tier
(smaller on `cpu-min`, larger on `gpu-24gb+`), NOT a flat value across tiers.

#### Scenario: write_tier_env emits the combined swap image and infer memory

- **GIVEN** `image_config.write_tier_env("gpu-8gb")` writes to a writable `.env`
- **WHEN** the resulting `.env` is read
- **THEN** it SHALL contain a line `HLH_SWAP_IMAGE=ghcr.io/indifferentketchup/hlh-swap:<ver>-cuda`
- **AND** it SHALL contain a line `HLH_INFER_MEM=<tier-scaled value>`

#### Scenario: infer memory differs across tiers

- **GIVEN** the `TIER_IMAGE_MAP` (or its policy companion)
- **WHEN** the infer memory for `cpu-min` and `gpu-24gb+` are compared
- **THEN** they SHALL NOT be equal
- **AND** the `gpu-24gb+` value SHALL be larger than the `cpu-min` value
