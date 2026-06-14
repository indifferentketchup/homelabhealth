# Tasks: lift-inference-tuning

**Date:** 2026-06-13

Tasks may be executed in the order listed. A1 tasks are independent of A2
tasks and may be done in either order, but A1.3 (audit) must complete before
A1.4 (INI edits) so the audit result can inform whether to remove
`spec-ngram-mod-thsh`.

---

## A1.1 - Audit spec-ngram-mod-thsh in the running binary (VERIFY FIRST)

This must run before A1.4 to decide whether to remove `spec-ngram-mod-thsh`.

- [x] Run the following command against the running hlh_chat container:
      `docker exec hlh_chat /app/llama-server --help 2>&1 | grep -i ngram`
      If the binary is not running, use:
      `docker run --rm --entrypoint /app/llama-server ghcr.io/ggml-org/llama.cpp:server-cuda-b9603 --help 2>&1 | grep -i ngram`
- [x] Record which `--spec-ngram-*` parameters appear in the output.
      RESULT: recognized params are --spec-ngram-mod-n-min, --spec-ngram-mod-n-max,
      --spec-ngram-mod-n-match only. `--spec-ngram-mod-thsh` is NOT recognized.
- [x] Decision gate:
  - `--spec-ngram-mod-thsh` did NOT appear. Parameter is unrecognized.
    DECISION: REMOVE. `spec-ngram-mod-thsh = 2` removed from `hlh_chat/models.ini`
    [*] section. Confirmed already absent from `hlh_orchestra/templates/models.ini`
    (no change needed there).

**Acceptance criteria:** The audit result is recorded and the decision (keep
or remove) is applied to `hlh_chat/models.ini` before A1.4 ships.

---

## A1.2 - Add V-cache quant and flash-attn to [medgemma] (hlh_chat/models.ini)

- [x] In `hlh_chat/models.ini`, in the `[medgemma]` section, add immediately
      after the `jinja = 1` line:
      ```
      cache-type-v = q4_0
      flash-attn = on
      spec-ngram-mod-n-max = 96
      ```
      The section should become:
      ```ini
      [medgemma]
      model = /models/active-medgemma.gguf
      mmproj = /models/vision/active-mmproj.gguf
      ctx-size = 8192
      n-gpu-layers = auto
      jinja = 1
      cache-type-v = q4_0
      flash-attn = on
      spec-ngram-mod-n-max = 96
      ```

**Acceptance criteria:** `grep -A 12 '^\[medgemma\]' hlh_chat/models.ini`
shows all three new lines present. No other sections are modified. VERIFIED.

---

## A1.3 - Add V-cache quant, flash-attn, and draft-mtp to [qwen-chat] (hlh_chat/models.ini)

- [x] In `hlh_chat/models.ini`, in the `[qwen-chat]` section, add immediately
      after the `jinja = 1` line:
      ```
      cache-type-v = q4_0
      flash-attn = on
      spec-type = draft-mtp
      ```
      The section should become:
      ```ini
      [qwen-chat]
      model = /models/active-qwen.gguf
      ctx-size = 4096
      n-gpu-layers = auto
      jinja = 1
      cache-type-v = q4_0
      flash-attn = on
      spec-type = draft-mtp
      ```

**Acceptance criteria:** `grep -A 9 '^\[qwen-chat\]' hlh_chat/models.ini`
shows all three new lines present. No other sections are modified. VERIFIED.

---

## A1.4 - Mirror all A1 changes to hlh_orchestra/templates/models.ini

Apply the identical section changes to `hlh_orchestra/templates/models.ini`.
The template copy has the same section stubs as the primary.

- [x] In `hlh_orchestra/templates/models.ini`, in the `[medgemma]` section,
      add the same three lines after `jinja = 1`:
      `cache-type-v = q4_0`, `flash-attn = on`, `spec-ngram-mod-n-max = 96`.
- [x] In `hlh_orchestra/templates/models.ini`, in the `[qwen-chat]` section,
      add the same three lines after `jinja = 1`:
      `cache-type-v = q4_0`, `flash-attn = on`, `spec-type = draft-mtp`.
- [x] A1.1 confirmed `spec-ngram-mod-thsh` unrecognized; already absent from
      template (no action needed). Confirmed.
- [x] Diff check: `diff hlh_chat/models.ini hlh_orchestra/templates/models.ini`
      shows only the expected [*] section differences (primary has full global
      tuning block; template has only sleep-idle-seconds). Both [medgemma] and
      [qwen-chat] sections are line-for-line identical. VERIFIED.

**Acceptance criteria:** The diff shows no unexpected divergence in
`[medgemma]` or `[qwen-chat]` sections between the two files. VERIFIED.

---

## A1.5 - Restart hlh_chat and verify startup logs

- [ ] Restart the inference container (no rebuild needed for INI changes):
      `docker compose restart hlh_chat`
- [ ] Wait for the container to start (approximately 10-30 seconds), then:
      `docker logs hlh_chat 2>&1 | head -80`
- [ ] Check for flash-attn initialization (BU-1):
      `docker logs hlh_chat 2>&1 | grep -i "flash"` must show no error.
      Expected: either "flash attention enabled" or silence (no flash-attn
      error lines).
- [ ] Check for spec-type override (BU-4):
      `docker logs hlh_chat 2>&1 | grep -i "spec"`. The [medgemma] model
      should show ngram-mod (global) and [qwen-chat] should show draft-mtp
      (section override). The exact log format depends on the llama.cpp build
      but any "spec" error should be visible here.
- [ ] Confirm the API is still responding:
      `docker exec hlh_api python -c "import asyncio, httpx; asyncio.run(httpx.AsyncClient().aclose())"` and
      `curl -s http://localhost:9600/api/health` returns 200.

**Acceptance criteria:** No flash-attn errors in startup logs. API health
check returns 200. If flash-attn errors appear, remove `flash-attn = on` from
the affected section and restart again.

---

## A2.1 - Add time import and latency logging to embeddings.py:_post()

- [x] In `backend/services/embeddings.py`, add `import time` to the top-level
      imports block (alongside `import logging` and `import os`, alphabetically:
      `import logging`, `import os`, `import time`).
- [x] In `backend/services/embeddings.py:_post()`, add timing around the
      `await client.post(...)` call. Per plan-validation fix F3/A.md, the
      `logger.debug` line is placed AFTER `r.raise_for_status()` (not before),
      consistent with "after each successful call" spec requirement and A2.2 pattern.

      Implemented as:
      ```python
      _t0 = time.monotonic()
      r = await client.post(...)
      r.raise_for_status()
      logger.debug("embed _post: n=%d %.0fms", len(inputs), (time.monotonic() - _t0) * 1000)
      ```

      NOTE: tasks.md code snippet placed logger.debug before raise_for_status;
      the implementation follows the spec and plan-validation A.md advisory fix
      instead (logger.debug after raise_for_status).

- [x] Run `python3 -m py_compile backend/services/embeddings.py` to confirm
      no syntax errors. PASSED.

**Acceptance criteria:** `grep -n "monotonic" backend/services/embeddings.py`
shows the new timing lines. `python3 -m py_compile backend/services/embeddings.py`
exits 0. VERIFIED.

---

## A2.2 - Add latency logging to rag.py:_rerank_infinity()

- [x] In `backend/services/rag.py:_rerank_infinity()`, add a `_t0 = time.monotonic()`
      immediately before the `await client.post(...)` call and a
      `logger.debug("rerank _rerank_infinity: %.0fms", (time.monotonic() - _t0) * 1000)`
      immediately after `r.raise_for_status()`. Implemented as specified.

      Note: `time` is already imported in `rag.py` (line 9). No new import needed.

- [x] Run `python3 -m py_compile backend/services/rag.py` to confirm no
      syntax errors. PASSED.

**Acceptance criteria:** `grep -n "monotonic" backend/services/rag.py`
shows both the existing settings-cache use and the new rerank timing line.
`python3 -m py_compile backend/services/rag.py` exits 0. VERIFIED.

---

## A2.3 - Rebuild hlh_api and verify latency logging

- [ ] Rebuild the API container with no-cache per CLAUDE.md hard rule 5:
      `docker compose build --no-cache hlh_api`
- [ ] Bring up the updated container:
      `docker compose up -d hlh_api`
- [ ] Confirm no import errors on startup:
      `docker logs hlh_api 2>&1 | grep -i "error\|import\|traceback"` must
      show no new errors.
- [ ] Trigger an embedding call by uploading a short document or sending a
      chat message, then check:
      `docker logs hlh_api 2>&1 | grep "embed _post"`
      At `LOG_LEVEL=DEBUG` this should show a line like
      `embed _post: n=1 42ms`.
      At default INFO level the line will not appear, which is correct behavior.
      Confirm the feature flag works by temporarily testing with:
      `docker exec hlh_api env LOG_LEVEL=DEBUG python3 -c "import logging; logging.basicConfig(level=logging.DEBUG); import asyncio; from services.embeddings import embed_text; asyncio.run(embed_text('test'))"`
      and verifying output includes the debug timing line.

**Acceptance criteria:** No import errors in `docker logs hlh_api`. The debug
timing line appears when log level is DEBUG.

---

## Cross-cutting verification

- [x] `python3 -m py_compile $(find backend -name '*.py')` produces no errors. PASSED.
- [x] `diff hlh_chat/models.ini hlh_orchestra/templates/models.ini` shows only
      the expected structural differences in `[*]` (template has minimal global
      section). Both `[medgemma]` and `[qwen-chat]` sections are line-for-line
      identical. VERIFIED.
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for A1 (models.ini
      tuning: V-cache quant, flash-attn, draft-mtp, ngram n-max) and A2
      (embed/rerank latency logging). DONE.

---

## Deferred (YAGNI)

**Streaming loading-sentinel:** Requires `inference.py:_stream_openai_chat_completions`
to read `reasoning_content` from stream deltas (currently reads only `content`).
This touches the fragile durable-streaming path guarded by CLAUDE.md. Reopen
trigger: when a separate ticket is opened for `inference.py` streaming changes.

**Background health-monitor:** Requires a new asyncio background task in
`main.py` lifespan that polls `hlh_chat` and surfaces failure via
`/api/system/health`. Scope must be "detect and surface" only (no auto-restart;
HLH does not manage the hlh_chat process). Failure threshold is 3 consecutive
failures (not 2 as stated in the upstream report; corrected from `sidecar.go:203`).
Reopen trigger: when a health/observability ticket is opened for the bundled stack.
