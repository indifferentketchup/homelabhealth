# Design: lift-inference-tuning

**Date:** 2026-06-13

---

## A1 - models.ini tuning

### Files

- `hlh_chat/models.ini` (primary; bind-mounted into the running container)
- `hlh_orchestra/templates/models.ini` (template copy; must stay in sync per CLAUDE.md)

### Changes to `[medgemma]`

Add after the existing `jinja = 1` line:

```ini
cache-type-v = q4_0
flash-attn = on
spec-ngram-mod-n-max = 96
```

**Rationale:**

- `cache-type-v = q4_0`: The global `[*]` section already sets
  `cache-type-k = q4_0`. Setting the V-cache to the same type reduces VRAM
  by 50% for the KV store compared to f16 default. K == V == q4_0 satisfies
  the `fattn.cu:424-428` constraint and does NOT require `GGML_CUDA_FA_ALL_QUANTS`.
- `flash-attn = on`: Explicit opt-in. On CPU builds this is a no-op. On CUDA
  builds, flash-attention is documented as auto-on for most combinations
  (`docs/multi-gpu.md:43`), but an explicit flag surfaces any incompatibility
  in startup logs immediately (instead of silently falling back).
- `spec-ngram-mod-n-max = 96`: Overrides the global default (64). Allows
  longer ngram-mod candidate drafts for the larger MedGemma models. 96 is
  a conservative starting point; can be increased empirically. The 128+
  recommendation from the upstream analysis report was not sourced and has
  been removed.

**NOTE:** `spec-ngram-mod-n-min` is NOT added. The global default (48) is
appropriate for MedGemma; only n-max is tuned here.

### Changes to `[qwen-chat]`

Add after the existing `jinja = 1` line:

```ini
cache-type-v = q4_0
flash-attn = on
spec-type = draft-mtp
```

**Rationale:**

- `cache-type-v = q4_0`: Same reasoning as [medgemma].
- `flash-attn = on`: Same reasoning as [medgemma].
- `spec-type = draft-mtp`: Overrides the global `spec-type = ngram-mod`.
  MTP speculative decoding (`draft-mtp`) uses the Multi Token Prediction
  heads embedded in the main model GGUF; no separate draft model download is
  needed. The `unsloth/Qwen3.5-0.8B-MTP-GGUF` source (confirmed in
  `model_puller.py:144-149`) includes MTP heads. Pinned build b9603 includes
  `draft-mtp` (verified in `common/speculative.cpp`). Section-level keys
  override `[*]` (llama-server README:1644).

**NOTE:** `spec-ngram-mod-n-max` is NOT added to `[qwen-chat]`. The global
defaults (n-min=48, n-max=64) are appropriate for the 0.8B model; the
`draft-mtp` strategy supersedes ngram-mod anyway.

### `spec-ngram-mod-thsh` audit

`hlh_chat/models.ini:18` contains `spec-ngram-mod-thsh = 2` in the `[*]`
section. This key is absent from:
- `tools/server/README.md`
- `docs/speculative.md`
- `common/arg.cpp` (not found in the fork)

It is either a renamed parameter, a removed parameter, or has never been
recognized by llama.cpp. An unknown key is ignored silently by llama.cpp (no
error), but it adds confusion.

**Decision:** The task must verify whether `spec-ngram-mod-thsh` is a
recognized parameter in the running b9603 image before shipping. If it is
unrecognized, remove it from both copies. If it is recognized (unlikely given
the evidence), keep it and document the finding.

**Verification method:** Run `docker exec hlh_chat /app/llama-server --help 2>&1 | grep ngram`
(or equivalent) to see all recognized `--spec-ngram-*` parameters in the
running binary.

### `hlh_orchestra/templates/models.ini` sync

The template copy has a minimal `[*]` section (only `sleep-idle-seconds`)
and the same section stubs as the primary. The same `cache-type-v`, `flash-attn`,
`spec-type`, and `spec-ngram-mod-n-max` lines are added to the same sections.
If `spec-ngram-mod-thsh` is removed from the primary, it is removed from the
template too (it does not appear in the template, so no action is needed there).

---

## A2 - Embed/rerank latency logging

### `backend/services/embeddings.py:_post()`

Current code (lines 44-48):

```python
async def _post(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    inputs: list[str],
) -> list[list[float]]:
    r = await client.post(
        f"{base_url}/v1/embeddings",
        json={"model": model, "input": inputs},
        headers=headers,
    )
```

Change to:

```python
# top-level imports (add import time alongside import logging, import os):
import logging
import os
import time

async def _post(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    inputs: list[str],
) -> list[list[float]]:
    _t0 = time.monotonic()
    r = await client.post(
        f"{base_url}/v1/embeddings",
        json={"model": model, "input": inputs},
        headers=headers,
    )
    r.raise_for_status()
    logger.debug("embed _post: n=%d %.0fms", len(inputs), (time.monotonic() - _t0) * 1000)
```

Note: `time` is added to the top-level imports (alongside `import logging`, `import os`).
The `logger.debug` line is placed AFTER `r.raise_for_status()` so it only fires on
successful calls, consistent with the spec requirement and the A2.2 pattern in rag.py.

### `backend/services/rag.py:_rerank_infinity()`

Current code around lines 249-252:

```python
async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
    r = await client.post(
        f"{provider.base_url}/v1/rerank",
        ...
    )
```

Change to:

```python
import time
...
async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
    _t0 = time.monotonic()
    r = await client.post(
        f"{provider.base_url}/v1/rerank",
        ...
    )
    r.raise_for_status()
    logger.debug("rerank _rerank_infinity: %.0fms", (time.monotonic() - _t0) * 1000)
```

`time` is already imported in `rag.py` (line 175 uses `time.monotonic()`).
No new import is needed in `rag.py`.

### Log level choice

Both log lines use `logger.debug`. This keeps them silent in production
(default log level is INFO) and visible when `LOG_LEVEL=DEBUG` is set.
A `logger.info` alternative is acceptable but would add noise to every
embedding call in production ingest.

---

## Blocking Unknowns (carry from validation A.md)

These must be treated as verification steps in tasks.md, not assumptions.

**BU-1: flash-attn startup confirmation on GPU tiers.**
After deploying the INI changes, check `docker logs hlh_chat | grep -i "flash"`.
If flash-attn initializes with an error (e.g., unsupported quant combination),
remove `flash-attn = on` from the affected section. The CUDA pre-built image
`ghcr.io/ggml-org/llama.cpp:server-cuda-b9603` may or may not have been
compiled with `GGML_CUDA_FA_ALL_QUANTS=ON`. Since K == V == q4_0, the
constraint is met without that flag, but a startup log check is required.

**BU-2: spec-ngram-mod-thsh parameter validity.**
Audit against the running b9603 binary before shipping. See procedure in the
`spec-ngram-mod-thsh audit` section above. If unrecognized: remove from both
copies.

**BU-3: draft-mtp CPU performance on cpu-min tier.**
`draft-mtp` works without GPU requirements. On a low-end CPU host, the MTP
head decode overhead may exceed the acceptance-rate speedup. This is
empirically unknown. Recommended: note in the change that cpu-min operators
can revert by adding `spec-type = ngram-mod` to `[qwen-chat]` if inference
speed regresses.

**BU-4: per-section spec-type override behavior.**
Confirmed by llama-server README:1644 for `--models-preset` router format,
which HLH uses (docker-compose.yml:15-16). Not a blocker but verify with a
startup log check (`docker logs hlh_chat | grep "spec"` or similar) after
the first restart.

---

## Guardrails

**Must Have:**
- Both copies of models.ini are updated identically for the sections they share.
- `spec-ngram-mod-thsh` is audited before shipping; a decision (keep or remove) is recorded.
- Latency log lines use `logger.debug`, not `logger.info` or `print`.
- `import time` is added to `embeddings.py` top-level imports (it is already present in `rag.py`).

**Must NOT Have:**
- No changes to `[qwen3-embed]`, `[qwen3-reranker]`, or `[gemma-tasks]` sections (tuning is for chat sections only, confirmed by validation A.md).
- No `EMBEDDING_*` env var changes.
- No schema changes.
- No changes to `useStream.js` or `inference.py` (streaming sentinel deferred).
- No `docker compose build` for A1 (INI is bind-mounted; container restart suffices). A2 DOES require `docker compose build --no-cache hlh_api`.

---

## Backward Compatibility

- INI changes: llama.cpp silently ignores unknown keys, so if flash-attn or
  draft-mtp are unsupported in a custom build, the binary degrades gracefully.
- Latency logging: additive only; no existing behavior changes.

---

## Implementation notes

**2026-06-14 -- A1.1 audit result:** `spec-ngram-mod-thsh` is NOT a recognized
parameter in the running b9603 binary. Confirmed by:
`docker exec hlh_chat /app/llama-server --help 2>&1 | grep -i ngram`
The recognized `--spec-ngram-mod-*` parameters are only `n-min`, `n-max`, and
`n-match`. The `spec-ngram-mod-thsh = 2` line was removed from the `[*]` section
of `hlh_chat/models.ini`. It was already absent from `hlh_orchestra/templates/models.ini`
(no action needed there).

**2026-06-14 -- F1 fix applied:** design.md updated to remove the in-function
`import time as _time` variant. Only the top-level `import time` form is shown.

**2026-06-14 -- F3 fix applied:** `logger.debug` in `_post()` placed AFTER
`r.raise_for_status()` (matching spec "after each successful call" and the A2.2
pattern). The tasks.md A2.1 task described the opposite order -- the implementation
follows the spec and plan-validation advisory fix A.md, not the tasks.md code snippet.

**A1.5 / A2.3 deferred to live deploy:** Container restart and `docker compose build
--no-cache hlh_api` cannot run in this editing session. See REMAINING LIVE VERIFICATION.
- Reverting A1 requires a single `git checkout hlh_chat/models.ini hlh_orchestra/templates/models.ini`
  followed by a container restart.
