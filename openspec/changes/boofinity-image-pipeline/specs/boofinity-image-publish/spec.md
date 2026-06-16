# Delta spec: boofinity-image-publish (A1)

**Date:** 2026-06-16

## ADDED Requirements

### Requirement: boofinity SHALL publish cpu and cuda GHCR tags at version 0.1.0

The boofinity repo (`indifferentketchup/boofinity`) SHALL publish two images
built from `libs/boofinity/Dockerfile.cpu_auto` and
`libs/boofinity/Dockerfile.nvidia_auto` to GHCR as
`ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` and
`ghcr.io/indifferentketchup/boofinity:0.1.0-cuda`. The version tag SHALL match
the boofinity `pyproject.toml` version (`0.1.0`).

#### Scenario: cpu tag resolves on a public registry

- **GIVEN** the boofinity publish workflow has run
- **WHEN** `docker buildx imagetools inspect ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` is run with no GHCR credentials
- **THEN** it SHALL succeed and print a manifest digest
- **AND** the digest SHALL be reproducible on a second inspect of the same tag

#### Scenario: cuda tag resolves on a public registry

- **GIVEN** the boofinity publish workflow has run
- **WHEN** `docker buildx imagetools inspect ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` is run with no GHCR credentials
- **THEN** it SHALL succeed and print a manifest digest

### Requirement: published boofinity packages SHALL be public

Both GHCR packages SHALL have public visibility so that
`bootstrap.py:pull_image` (which always pulls) can fetch them on a fresh
self-hoster host with no GHCR authentication.

#### Scenario: unauthenticated pull succeeds

- **GIVEN** a host with no `docker login ghcr.io` credentials
- **WHEN** `docker pull ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` is run
- **THEN** it SHALL succeed without an authentication error

#### Scenario: visibility flip is verified after first publish

- **WHEN** the boofinity image is published for the first time
- **THEN** the package visibility SHALL be flipped from the GHCR default (private) to public
- **AND** an unauthenticated `docker buildx imagetools inspect` SHALL confirm it before the change is marked done

### Requirement: the published image SHALL be built from the VL-bearing ref

The published boofinity image SHALL be built from the boofinity ref that contains
the VL / `causal_lm` commits (the `ik-main` branch, or a tag cut from it), NOT
`origin/main`. The `/v1/mm_embeddings` and `/v1/mm_rerank` routes the bundled GPU
stack depends on live on that ref; an image built from `origin/main` SHALL be
considered invalid for this folder. Verification SHALL run the published cuda
image and confirm the `mm_` routes resolve before the publish is marked done.
Pushing or merging `ik-main` and cutting the `v0.1.0` tag in the separate
boofinity repo is an operator prerequisite.

#### Scenario: published image serves the mm_ routes

- **GIVEN** the published `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` image
- **WHEN** it is run with the GPU model command and a client posts to
  `/v1/mm_embeddings` and `/v1/mm_rerank`
- **THEN** neither route SHALL return 404
- **AND** a 404 SHALL be treated as evidence the wrong build ref was used (not `ik-main`)

#### Scenario: build ref is ik-main, not origin/main

- **GIVEN** the boofinity publish workflow
- **WHEN** the ref it builds from is read
- **THEN** it SHALL be `ik-main` or a tag cut from `ik-main`
- **AND** it SHALL NOT be `origin/main`

### Requirement: the cpu image architecture coverage SHALL be recorded

The cpu publish SHALL either be multi-arch (`linux/amd64` + `linux/arm64`) so the
`apple-mlx` tier pulls natively, or, if it is `linux/amd64`-only, the emulation
perf caveat for `apple-mlx` SHALL be documented in the CHANGELOG. The architecture
coverage SHALL NOT be left unrecorded.

#### Scenario: cpu manifest architecture is inspected and recorded

- **GIVEN** the published `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` image
- **WHEN** its manifest is inspected for architecture entries
- **THEN** either it SHALL include a `linux/arm64` entry (native `apple-mlx`)
- **AND** OR, if `linux/amd64`-only, the CHANGELOG SHALL document the `apple-mlx`
  emulation perf caveat

### Requirement: the build job SHALL live in the boofinity repo

The GitHub Actions workflow that builds and pushes the boofinity image SHALL
reside in `indifferentketchup/boofinity`, not in homelabhealth. homelabhealth
SHALL consume the published tag only and SHALL NOT build boofinity.

#### Scenario: homelabhealth contains no boofinity build workflow

- **GIVEN** the homelabhealth repository
- **WHEN** `.github/workflows/` is searched for a boofinity build step
- **THEN** no workflow SHALL build `Dockerfile.cpu_auto` or `Dockerfile.nvidia_auto`
- **AND** homelabhealth SHALL reference the boofinity image only by its published tag
