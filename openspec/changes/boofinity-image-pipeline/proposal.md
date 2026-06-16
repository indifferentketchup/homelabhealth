# Proposal: boofinity-image-pipeline

**Date:** 2026-06-16
**Status:** proposed

## Summary

Stand up the build/publish and version-pin layer for the boofinity inference
fork (ADR 0001). This is folder A of the boofinity split: it publishes the fork
as a GHCR image and rewrites the pins in `backend/services/image_config.py`,
`.env.example`, and `hlh_orchestra/bootstrap.py` to consume the fork tag instead
of upstream `michaelf34/infinity`. It also bumps the llama.cpp pin to `b9660`
and records the llama-swap front-door version (`v226`) as a constant so folders
B/C/D have a single source of truth.

No runtime HLH behavior changes here beyond the pins. The llama-swap front-door
service wiring, the `hlh_infer` compose service, and the VL retrieval paths are
folders B/C/D and consume the constants this folder establishes.

## Motivation

Embedding, reranking, and Qwen3-VL retrieval are moving off the `hlh_chat`
llama.cpp router onto boofinity, a fork of `michaelfeil/infinity`
(repo `indifferentketchup/boofinity`, `pyproject.toml` version `0.1.0`). The
required capabilities (CausalLM text reranker, Qwen3-VL multimodal embed and
rerank) are fork-only and absent from upstream `0.0.77`, per ADR 0001.

Today `backend/services/image_config.py` pins `INFINITY_VERSION = "0.0.77"` and
every tier's `infer_image` points at `michaelf34/infinity`. The fork has
buildable Dockerfiles (`libs/boofinity/Dockerfile.cpu_auto`,
`Dockerfile.nvidia_auto`), a `boofinity` console entrypoint, and default port
`7997`. We need a published image and a pin rewrite before any of the runtime
folders can wire it in.

Two adjacent pins are bumped in the same pass to keep the registry consistent:

- `LLAMA_CPP_VERSION` moves `b9628` to `b9660` (continuing the rolling pin; the
  most recent bump `b9603` to `b9628` is commit `9b5655b`).
- `LLAMA_SWAP_VERSION = "v226"` is added as a constant. The front-door wiring is
  folder B, but the pin lives here so all four folders read one value.

## Scope

| ID | File(s) touched | Type |
|----|-----------------|------|
| A1 | boofinity repo GitHub Actions workflow (described, not authored) | CI publish |
| A2 | `backend/services/image_config.py` | Pin rewrite |
| A3 | `.env.example` | Comment/pin update |
| A4 | `hlh_orchestra/bootstrap.py` | Image default bump |

The workflow itself is authored in the separate `indifferentketchup/boofinity`
repo (see design.md for the rationale). This folder describes it as a task and
verifies the published tags from the homelabhealth side; it does not commit a
`.github/workflows/*.yml` file into homelabhealth.

## Out of scope

- No `hlh_infer` service in `docker-compose.yml` (folder B).
- No llama-swap front-door wiring beyond the version constant (folder B).
- No resource policy, `pipeline_status.py`, or VL retrieval changes (folders B/C/D).
- No schema changes.
- No new Python dependencies.
- Pascal-GPU `--dtype float32` runtime flag is a downstream note (folder B).

## Risk

Low to moderate. The Python pin rewrite is mechanical and verified by
`python -m py_compile` plus an assertion on `TIER_IMAGE_MAP`. The moderate risk
is operational, not code:

- **GHCR cross-repo pull auth.** Packages default to private on first push. If
  visibility is not flipped to public, `bootstrap.py:pull_image` (which always
  pulls) fails for operators with no GHCR auth. The build task includes the
  visibility flip and a verification step.
- **CI home.** The build job lives in the boofinity repo, not homelabhealth.
  homelabhealth consumes the published tag only. See the open risk in design.md.
- **Pin/runtime gap.** This folder changes pins while the `hlh_infer` service
  does not yet exist in compose, so the new `infer_image` value is inert until
  folder B lands. That is intentional and matches the "ghost service" framing in
  `docs/CONTEXT.md`.
