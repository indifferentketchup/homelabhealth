# Proposal: lift-inference-tuning

**Date:** 2026-06-13
**Status:** proposed

## Summary

Two targeted, low-risk tuning passes on the bundled inference stack. Group A1
edits only INI files (no Python changes, no schema changes, no Docker rebuild
required). Group A2 adds five-line latency instrumentation to two Python
service files. Combined scope is small: four files touched, zero new
dependencies, zero schema changes.

## Motivation

**Group A1 - models.ini tuning**

The bundled llama-server router (`hlh_chat`) runs with several performance
levers unset or set to suboptimal defaults:

- `cache-type-v` is absent from `hlh_chat/models.ini` (and the orchestra
  template copy). The K-cache is already quantized to `q4_0` globally (line 13
  of `hlh_chat/models.ini`). Adding `cache-type-v = q4_0` reduces VRAM usage
  by quantizing the V-cache to the same type. Because K and V types are
  identical (`q4_0` == `q4_0`), this does NOT require the
  `GGML_CUDA_FA_ALL_QUANTS` compile flag (that flag is only needed for mixed
  K/V types). Confirmed by `fattn.cu:424-428` in the fork.

- `flash-attn = on` is absent from the chat sections. The llama.cpp CUDA build
  treats flash-attention as auto-on for most quant combinations, but an
  explicit flag is a safety net that ensures the feature is active and surfaces
  any incompatibility in startup logs immediately. On CPU tiers flash-attn is a
  no-op; the flag is harmless there.

- `spec-type = draft-mtp` is absent from `[qwen-chat]`. The `draft-mtp`
  speculative-decoding strategy uses MTP heads from the main model GGUF
  directly; no separate draft model download is needed. Confirmed present in
  b9603 (the pinned build in docker-compose.yml:133,137) via `common/speculative.cpp`.
  The global `spec-type = ngram-mod` is overridden per-section by design
  (llama-server README:1644).

- `spec-ngram-mod-n-max` is absent from `[medgemma]`. The current global
  default is 64. For MedGemma (a larger model with medical reasoning), a
  moderate increase to 96 allows longer candidate drafts without the risk of
  large values that degrade acceptance rate. The value 96 is a conservative
  empirical starting point; the 128+ recommendation in the upstream finding
  report was not sourced and has been corrected.

- `spec-ngram-mod-thsh = 2` is set globally (line 18 of `hlh_chat/models.ini`)
  but is absent from llama.cpp README, `docs/speculative.md`, and `common/arg.cpp`.
  This parameter is potentially unrecognized and a no-op. It must be audited
  against the running b9603 build before the tuning batch ships.

**Group A2 - embed/rerank latency logging**

`services/embeddings.py:_post()` (lines 44-61) and `services/rag.py:_rerank_infinity()`
(lines 249-260) each make a single `httpx` HTTP call with no timing around it.
The only use of `time.monotonic()` in `rag.py` (line 175) is for the settings
cache TTL, not for request latency. Slow embedding or reranker calls are
invisible in logs today. A `time.monotonic()` bracket around each HTTP call,
with a structured `logger.debug` line, adds five lines per function and provides
the observability needed to diagnose retrieval performance.

## Scope

| ID  | File(s) touched                                       | Type              |
|-----|-------------------------------------------------------|-------------------|
| A1  | `hlh_chat/models.ini`, `hlh_orchestra/templates/models.ini` | INI tuning   |
| A2  | `backend/services/embeddings.py`, `backend/services/rag.py` | Latency logging |

Both copies of `models.ini` must be kept in sync per the CLAUDE.md convention
("Templates in `hlh_orchestra/templates/` must mirror `hlh_chat/models.ini`").

## Out of scope

- No schema changes.
- No new dependencies.
- No Docker image rebuild required for A1 (models.ini is bind-mounted at
  `/config/models.ini` via docker-compose; a container restart is sufficient).
  A2 requires `docker compose build --no-cache hlh_api` per CLAUDE.md hard rule 5.
- Streaming loading-sentinel (requires `inference.py` stream handler to read
  `reasoning_content` from deltas, which touches the fragile `useStream.js`
  durable-streaming path; deferred to a separate ticket).
- Background health-monitor with eviction (requires new asyncio background task
  in `main.py` lifespan; deferred to a separate ticket).
- cache-ram cap: KILLED. The default 8192 MiB cap is already active via the
  existing `cache-idle-slots = 1` setting; no change needed.

## Risk

Low overall. A1 is INI-only with no Python surface. The flash-attn and
draft-mtp changes apply only to GPU-capable chat sections; CPU tiers are
unaffected by flash-attn (no-op) and draft-mtp should work on CPU but has
unknown performance characteristics on cpu-min (see Blocking Unknowns in
design.md). A2 is additive instrumentation with no behavioral change.
