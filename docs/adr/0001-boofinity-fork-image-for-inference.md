# 0001 — Ship a first-party boofinity fork image for embed/rerank/VL

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** indifferentketchup

## Context

Embedding, reranking, and (new) vision-language retrieval are moving off the
`hlh_chat` llama.cpp router onto [boofinity](https://github.com/indifferentketchup/boofinity),
a fork of `michaelfeil/infinity`. `backend/services/image_config.py` already pins
the inference image, but at upstream `michaelf34/infinity:0.0.77`.

The capabilities this work requires are **fork-only** and absent from upstream
`0.0.77`:

- CausalLM text reranker (`Qwen/Qwen3-Reranker-0.6B`) — `crossencoder/lm_torch.py`
- Qwen3-VL multimodal embed (`vlm/torch_vlm.py:278`, route `/mm_embeddings`)
- Qwen3-VL multimodal rerank (`vlm/torch_vlm.py:59`, route `/mm_rerank`)

boofinity has buildable Dockerfiles (`libs/boofinity/Dockerfile.cpu_auto`,
`Dockerfile.nvidia_auto`), a `boofinity` console entrypoint, default port 7997,
and a `/health` readiness endpoint.

## Decision

Build and publish the fork as `ghcr.io/indifferentketchup/boofinity:<ver>-cpu`
and `:<ver>-cuda` via a GitHub Actions job (GHCR, `write:packages`), mirroring
how the llama.cpp images are consumed. Replace the `michaelf34/infinity`
reference in `image_config.py` with a single `BOOFINITY_VERSION` pin and rename
the constant/managed env (`HLH_INFER_IMAGE`) to point at the fork tags.

## Consequences

- **+** Unlocks causal-LM rerank and Qwen3-VL embed/rerank — none available upstream.
- **+** Same pull-latest deploy story as the rest of the stack (bootstrap pulls images).
- **−** We now own a published image: a CI build job, GHCR visibility/auth
  (`gh auth refresh --scopes write:packages`), and tracking upstream security fixes.
- **−** Forking pins us to a snapshot of infinity; upstream improvements need deliberate rebases.

## Alternatives considered

- **Keep upstream `michaelf34/infinity`** — rejected: no causal-LM rerank, no VL.
- **Build locally per host, no registry** — rejected: breaks `install.sh`/bootstrap
  pull-latest; every operator would build from source.
