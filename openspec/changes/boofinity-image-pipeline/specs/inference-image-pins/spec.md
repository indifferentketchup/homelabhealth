# Delta spec: inference-image-pins (A2/A3/A4)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: image_config SHALL define BOOFINITY_VERSION and LLAMA_SWAP_VERSION

`backend/services/image_config.py` SHALL define `BOOFINITY_VERSION = "0.1.0"`
and `LLAMA_SWAP_VERSION = "v226"` as module-level constants. `LLAMA_SWAP_VERSION`
SHALL be defined even though the front-door service wiring is a downstream folder,
so that folders B/C/D import one source of truth.

#### Scenario: constants import with expected values

- **GIVEN** `backend/services/image_config.py`
- **WHEN** `from services.image_config import BOOFINITY_VERSION, LLAMA_SWAP_VERSION` is imported
- **THEN** `BOOFINITY_VERSION` SHALL equal `"0.1.0"`
- **AND** `LLAMA_SWAP_VERSION` SHALL equal `"v226"`

#### Scenario: module compiles cleanly

- **WHEN** `python3 -m py_compile backend/services/image_config.py` is run
- **THEN** it SHALL exit 0 with no output

## MODIFIED Requirements

### Requirement: LLAMA_CPP_VERSION SHALL pin b9660

`backend/services/image_config.py` SHALL pin `LLAMA_CPP_VERSION = "b9660"`,
bumped from `b9628`. The `chat_image` entries in `TIER_IMAGE_MAP` SHALL pick up
the new value through `{LLAMA_CPP_VERSION}` interpolation with no per-tier edit.

#### Scenario: llama.cpp pin is b9660

- **GIVEN** `backend/services/image_config.py`
- **WHEN** `LLAMA_CPP_VERSION` is read
- **THEN** it SHALL equal `"b9660"`
- **AND** the `cpu-min` `chat_image` SHALL contain `server-b9660`
- **AND** a GPU tier `chat_image` SHALL contain `server-cuda-b9660`

### Requirement: TIER_IMAGE_MAP infer_image SHALL resolve to the boofinity fork tag

Every `TIER_IMAGE_MAP` entry's `infer_image` SHALL resolve to
`ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` for cpu-class tiers
(`cpu-min`, `cpu-std`, `apple-mlx`, `external`) and to
`ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` for GPU tiers
(`gpu-4gb`, `gpu-8gb`, `gpu-16gb`, `gpu-24gb+`). The now-dead `INFINITY_VERSION`
constant SHALL be removed, and no `michaelf34/infinity` reference SHALL remain
under `backend/`.

#### Scenario: cpu tiers map to the cpu fork tag

- **GIVEN** `TIER_IMAGE_MAP`
- **WHEN** the `cpu-min`, `cpu-std`, `apple-mlx`, and `external` entries are read
- **THEN** each `infer_image` SHALL equal `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu`

#### Scenario: gpu tiers map to the cuda fork tag

- **GIVEN** `TIER_IMAGE_MAP`
- **WHEN** the `gpu-4gb`, `gpu-8gb`, `gpu-16gb`, and `gpu-24gb+` entries are read
- **THEN** each `infer_image` SHALL equal `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda`

#### Scenario: dead upstream references are gone

- **WHEN** `backend/` is grepped for `michaelf34/infinity` and `INFINITY_VERSION`
- **THEN** zero matches SHALL be found

### Requirement: gpu-24gb+ compose_profiles SHALL drop the stale vision token

`TIER_IMAGE_MAP['gpu-24gb+'].compose_profiles` SHALL be `"bundled-gpu"`, with the
stale `vision` token removed. No service in `docker-compose.yml` carries a
`vision` profile (MedGemma vision is the chat model + mmproj, not a separate
service), so the seeded value SHALL NOT include `vision`. The `write_tier_env`
operator-preserve branch for `vision` SHALL be left intact.

#### Scenario: gpu-24gb+ profiles no longer seed vision

- **GIVEN** `TIER_IMAGE_MAP`
- **WHEN** the `gpu-24gb+` `compose_profiles` is read
- **THEN** it SHALL equal `"bundled-gpu"`
- **AND** it SHALL NOT contain the token `vision`

### Requirement: .env.example SHALL document the fork tag

`.env.example` SHALL document the `HLH_INFER_IMAGE` managed override as
`ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` and the `HLH_CHAT_IMAGE`
override at `server-b9660`. No `HLH_SWAP_IMAGE` var SHALL be added in this folder
(the front-door service has no compose entry yet).

#### Scenario: env example reflects the fork and the new llama.cpp pin

- **GIVEN** `.env.example`
- **WHEN** the `HLH_INFER_IMAGE` and `HLH_CHAT_IMAGE` comment lines are read
- **THEN** `HLH_INFER_IMAGE` SHALL reference `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu`
- **AND** `HLH_CHAT_IMAGE` SHALL reference `server-b9660`
- **AND** no `michaelf34/infinity` string SHALL remain in `.env.example`

### Requirement: bootstrap.py image defaults SHALL pin b9660 and the fork tag

`hlh_orchestra/bootstrap.py` SHALL pin its hardcoded chat image defaults at
`server-b9660` / `server-cuda-b9660`, and any infinity image default SHALL be
rewritten to the boofinity fork tag. The `pull_image` always-pull behavior SHALL
be preserved.

#### Scenario: bootstrap chat defaults are b9660

- **GIVEN** `hlh_orchestra/bootstrap.py`
- **WHEN** `CHAT_IMAGE_CPU` and `CHAT_IMAGE_GPU` defaults are read
- **THEN** `CHAT_IMAGE_CPU` SHALL end with `server-b9660`
- **AND** `CHAT_IMAGE_GPU` SHALL end with `server-cuda-b9660`

#### Scenario: no upstream infinity default survives in orchestra

- **WHEN** `hlh_orchestra/` is grepped for `michaelf34/infinity`
- **THEN** zero matches SHALL be found

#### Scenario: pull_image still always pulls

- **GIVEN** `hlh_orchestra/bootstrap.py`
- **WHEN** `pull_image` is read
- **THEN** it SHALL NOT contain a skip-if-present branch that bypasses the pull
