# Delta spec: llama-swap-frontdoor (B1, B2, B2b, B3)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: hlh_swap SHALL be the single combined inference front-door

`docker-compose.yml` SHALL define an `hlh_swap` service whose entrypoint is
llama-swap (v226) and whose combined image
(`ghcr.io/indifferentketchup/hlh-swap:<ver>-{cpu,cuda}`, overridable via
`HLH_SWAP_IMAGE`) bundles the `llama-server` and `boofinity` binaries. It SHALL
listen on `0.0.0.0:9620`, attach only to the internal `hlh_inference` network,
publish no host ports, and be gated by `COMPOSE_PROFILES` as `hlh_swap_cpu`
(profile `bundled`) and `hlh_swap_gpu` (profile `bundled-gpu`). It SHALL
bind-mount `./hlh_swap/config.yaml` at `/config/config.yaml` read-only and SHALL
NOT mount the Docker socket.

#### Scenario: hlh_swap present on both bundled profiles

- **GIVEN** `docker-compose.yml`
- **WHEN** `docker compose --profile bundled config` is rendered
- **THEN** the output SHALL contain a service `hlh_swap_cpu`
- **AND** `docker compose --profile bundled-gpu config` SHALL contain `hlh_swap_gpu`
- **AND** the rendered `hlh_swap` SHALL list `hlh_inference` as its only network
- **AND** `hlh_swap` SHALL declare no `ports:` host mapping
- **AND** the standalone `hlh_chat` and `hlh_infer` services SHALL NOT be present

#### Scenario: hlh_swap mounts no Docker socket

- **GIVEN** the `hlh_swap` service definition
- **WHEN** its `volumes` are read
- **THEN** none SHALL bind `/var/run/docker.sock`

#### Scenario: hlh_swap healthcheck targets the llama-swap readiness endpoint

- **GIVEN** the `hlh_swap` service definition
- **WHEN** its `healthcheck.test` is read
- **THEN** it SHALL probe llama-swap's readiness endpoint on `http://localhost:9620`
- **AND** the probe SHALL use the image's bundled `python` interpreter (no wget/curl dependency)

### Requirement: the combined image SHALL be built from boofinity plus copied binaries

`hlh_swap/Dockerfile` SHALL define a multi-stage build that is FROM the boofinity
image (bringing python, torch, and the boofinity install), COPYs the
`llama-server` binary and its shared libraries from the llama.cpp image
(`ghcr.io/ggml-org/llama.cpp:server-b9660` / `server-cuda-b9660`), and COPYs the
`llama-swap` binary from `ghcr.io/mostlygeek/llama-swap:v226`. The CPU and CUDA
variants SHALL build FROM the matching boofinity and llama.cpp bases. The image
entrypoint SHALL be `llama-swap`.

#### Scenario: combined image carries all three binaries

- **GIVEN** an image built from `hlh_swap/Dockerfile`
- **WHEN** the image is inspected
- **THEN** `llama-swap`, `llama-server`, and `boofinity` SHALL each be on PATH
- **AND** the entrypoint SHALL be `llama-swap`

#### Scenario: cpu and cuda variants build from matching bases

- **GIVEN** `hlh_swap/Dockerfile`
- **WHEN** the build args are read
- **THEN** the CPU variant SHALL build FROM `boofinity:<ver>-cpu` and `llama.cpp:server-b9660`
- **AND** the CUDA variant SHALL build FROM `boofinity:<ver>-cuda` and `llama.cpp:server-cuda-b9660`

### Requirement: hlh_swap config SHALL launch each backend as a child process

`hlh_swap/config.yaml` SHALL define a `models:` map where each entry's `cmd:`
launches a **child process** inside the `hlh_swap` container. `medgemma`,
`qwen-chat`, and `gemma-tasks` SHALL launch the `llama-server` child
(`llama-server --models-preset /models/models.ini ...`); `qwen3-embed`,
`qwen3-reranker`, `qwen3-vl-embed`, and `qwen3-vl-rerank` SHALL launch the
`boofinity` child (`boofinity v2 ... --url-prefix /v1 ...`). Each model entry
SHALL carry a `cmd` and a positive `ttl`. The config SHALL contain no Docker
socket reference, no `docker start`/`docker stop`, and no sibling-container
`proxy` upstream URL.

#### Scenario: embed alias launches the boofinity child

- **GIVEN** `hlh_swap/config.yaml`
- **WHEN** the `qwen3-embed` model entry is read
- **THEN** its `cmd` SHALL launch `boofinity v2`
- **AND** a request to `hlh_swap:9620/v1/embeddings` with `{"model":"qwen3-embed"}` SHALL be served by the boofinity child and return a 1024-dimension vector

#### Scenario: chat alias launches the llama-server child

- **GIVEN** `hlh_swap/config.yaml`
- **WHEN** the `medgemma` model entry is read
- **THEN** its `cmd` SHALL launch `llama-server --models-preset /models/models.ini`
- **AND** a request to `hlh_swap:9620` with `{"model":"medgemma"}` SHALL be served by the llama-server child

#### Scenario: no Docker socket or sibling lifecycle in the config

- **GIVEN** `hlh_swap/config.yaml`
- **WHEN** the file is read
- **THEN** it SHALL NOT contain `/var/run/docker.sock`, `docker start`, or `docker stop`

#### Scenario: every model entry carries a child cmd and a ttl

- **GIVEN** `hlh_swap/config.yaml`
- **WHEN** each entry under `models:` is read
- **THEN** it SHALL define a `cmd` and a `ttl` greater than 0

### Requirement: swap group SHALL make the children mutually exclusive on constrained VRAM

`hlh_swap/config.yaml` SHALL define a `groups:` entry with `swap: true` and
`exclusive: true` whose `members` include both the llama-server-child aliases and
the boofinity-child aliases, so that loading any one model stops the others and
the two child processes are never both VRAM-resident on constrained tiers. This
exclusivity is enforced in-process by llama-swap, not by container lifecycle.

#### Scenario: idle child is stopped when the other is requested

- **GIVEN** an `hlh_swap` exclusive swap group containing `medgemma` and `qwen3-embed`
- **WHEN** a request for `qwen3-embed` arrives while the `medgemma` (llama-server) child is loaded
- **THEN** llama-swap SHALL stop the llama-server child before starting and serving the boofinity child
- **AND** only one child process SHALL hold VRAM at any moment

#### Scenario: TTL stops an idle child

- **GIVEN** a model entry with `ttl: 300`
- **WHEN** the model has served no request for more than 300 seconds
- **THEN** llama-swap SHALL stop its child process

### Requirement: swap config SHALL be mirrored into the orchestra template

`hlh_orchestra/templates/swap_config.yaml` SHALL exist and SHALL be line-for-line
identical to `hlh_swap/config.yaml`, per the CLAUDE.md template-sync convention.

#### Scenario: both swap config copies are identical

- **GIVEN** `hlh_swap/config.yaml` and `hlh_orchestra/templates/swap_config.yaml`
- **WHEN** the two files are compared with `diff`
- **THEN** `diff` SHALL report no differences

## MODIFIED Requirements

### Requirement: models.ini SHALL NOT serve embed or rerank roles

`hlh_chat/models.ini` and `hlh_orchestra/templates/models.ini` SHALL NOT contain
`[qwen3-embed]` or `[qwen3-reranker]` sections; those roles move to the boofinity
child. The `[medgemma]`, `[gemma-tasks]`, `[qwen-chat]`, and `[*]` sections SHALL
be retained unchanged and SHALL be served by the llama-server child reading
`models.ini` from the read-only `hlh_models` mount.

#### Scenario: embed and rerank sections removed from both copies

- **GIVEN** `hlh_chat/models.ini`
- **WHEN** the file is read
- **THEN** it SHALL NOT contain a `[qwen3-embed]` section
- **AND** it SHALL NOT contain a `[qwen3-reranker]` section
- **AND** the same SHALL hold for `hlh_orchestra/templates/models.ini`

#### Scenario: chat and tasks sections survive unchanged

- **GIVEN** `hlh_chat/models.ini`
- **WHEN** the file is read
- **THEN** it SHALL still contain `[medgemma]`, `[gemma-tasks]`, and `[qwen-chat]` sections
