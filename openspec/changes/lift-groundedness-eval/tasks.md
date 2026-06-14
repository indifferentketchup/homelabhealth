# Tasks: lift-groundedness-eval

**Date:** 2026-06-13

Tasks are ordered by dependency. Tasks 1-3 are sequential prerequisites.
Tasks 4-8 can proceed after Task 3. Task 9 is independent.

---

## Task 1 -- Mount the eval router in main.py

- [x] In `backend/main.py`, add a standalone import statement AFTER the existing
      grouped import block (matching the `demo_router` pattern at line 39):
      `from routers.eval import router as eval_router`
      Do NOT add `eval as eval_router` inside the `from routers import (...)`
      parenthesized block -- `as` aliases are not valid in that form and `eval`
      would shadow the Python built-in. (V6/JD-006 correction.)
- [x] Immediately after line 330 (`api.include_router(demo_router, ...)`), add:
      `api.include_router(eval_router, prefix="/eval", tags=["eval"])`.
- [x] Run `python3 -m py_compile backend/main.py` and confirm no syntax errors.

**Acceptance criteria:**
```bash
# With stack running (docker compose up):
curl -s -X POST http://localhost:9600/api/eval/groundedness \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"00000000-0000-0000-0000-000000000000","query":"x","context":"x","response":"x"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('detail') != 'Not Found', 'still 404'; print('PASS')"
```
Expected: 403 (admin-only) or 401, NOT 404.

---

## Task 2 -- Create services/eval_judge.py

- [x] Create `backend/services/eval_judge.py`. The file must contain exactly:
    - `_parse_eval_response(raw: str) -> dict` -- copy verbatim from `eval.py:240-268`.
    - `_normalize_score(raw: Any) -> float | None` -- copy verbatim from `eval.py:271-279`.
    - `_build_eval_response(data: dict) -> dict` -- copy verbatim from `eval.py:282-298`.
    - `call_llm_as_judge(provider, model, system_prompt, user_prompt) -> dict`
      -- copy the body of `_call_llm_as_judge` from `eval.py:301-383`, renamed
      to remove the leading underscore.
    - `GROUNDEDNESS_SYSTEM_PROMPT` and `GROUNDEDNESS_USER_PROMPT` -- copy verbatim
      from `eval.py:88-137`. Keep `{context}` and `{response}` slots unchanged.
    - `resolve_judge_provider(workspace_id: uuid.UUID | None) -> tuple | None`
      -- uses workspace chat provider (not gemma-tasks) per V6/ctx DECISION in D.md.
- [x] Update `backend/routers/eval.py` to import from `services.eval_judge` rather
      than defining the helpers inline:
    - Replace the inline `_parse_eval_response`, `_normalize_score`,
      `_build_eval_response`, and `_call_llm_as_judge` definitions with imports
      from `services.eval_judge`. GROUNDEDNESS prompts imported from eval_judge.
- [x] Run `python3 -m py_compile backend/services/eval_judge.py backend/routers/eval.py`.

**Acceptance criteria:**
```bash
python3 -c "
from backend.services.eval_judge import call_llm_as_judge, resolve_judge_provider
print('PASS: imports resolved')
" 2>&1 || python3 -m py_compile backend/services/eval_judge.py && echo "PASS: py_compile"
```

---

## Task 3 -- Add groundedness_score column + global_settings keys

- [x] In `backend/schema.sql`, at the bottom of the file (after line 647), add:

```sql
-- Groundedness eval: async judge score per assistant message (lift-groundedness-eval, 2026-06-13).
-- Null for messages predating this feature or when eval is disabled/sampled out.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS groundedness_score FLOAT;

INSERT INTO global_settings (key, value) VALUES
    ('groundedness_eval_enabled',     'false'),
    ('groundedness_eval_sample_rate', '1.0')
ON CONFLICT (key) DO NOTHING;
```

- [x] Verify idempotency: run the two statements twice against the DB and confirm
      no error on the second run.

**Acceptance criteria:**
```bash
# Confirm column exists after schema apply:
docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT column_name FROM information_schema.columns WHERE table_name='messages' AND column_name='groundedness_score';" \
  | grep -q groundedness_score && echo "PASS: column exists" || echo "FAIL"

# Confirm settings keys exist:
docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT key FROM global_settings WHERE key IN ('groundedness_eval_enabled','groundedness_eval_sample_rate') ORDER BY key;" \
  | wc -l | grep -q 2 && echo "PASS: settings seeded" || echo "FAIL"
```

---

## Task 4 -- Add background task helper to chats.py

- [x] In `backend/routers/chats.py`, add a module-level set to hold background
      task references (prevent GC mid-flight):
      `_BG_EVAL_TASKS: set[asyncio.Task] = set()`.
      Note: `sources.py:293` uses bare `asyncio.create_task` without a set --
      the set+done-callback pattern is new here and more robust. (JD-007 correction.)
- [x] Add `_run_groundedness_eval` coroutine function at module level (not nested
      inside a route handler). It must:
      a. Accept `message_id: uuid.UUID`, `workspace_id: uuid.UUID`,
         `assistant_text: str`, `context_text: str`.
      b. Be wrapped in `try/except Exception` that logs at WARNING and returns.
      c. Call `resolve_judge_provider(workspace_id)` from `services.eval_judge`;
         return early if result is None.
      d. Truncate: `context_text[:4000]` and `assistant_text[:2000]` (workspace chat
         provider has large context window; V6/ctx DECISION uses workspace provider
         not gemma-tasks).
      e. Call `call_llm_as_judge(provider, model, GROUNDEDNESS_SYSTEM_PROMPT, user_prompt)`.
      f. On success, execute a single `UPDATE messages SET groundedness_score=$2,
         guard_flags = COALESCE(guard_flags,'{}')::jsonb || jsonb_build_object(...)
         WHERE id=$1::uuid`. Pass violations as `json.dumps(violations)`.
- [x] Add `_maybe_fire_groundedness_eval` async function that:
      a. Reads `groundedness_eval_enabled` from `global_settings` (live DB read).
      b. Returns immediately if disabled or if `context_text` is falsy (no RAG
         context means no groundedness check).
      c. Applies sample rate: `if random.random() > float(rate): return`.
      d. Calls `asyncio.create_task(_run_groundedness_eval(...))` and adds the
         task to `_BG_EVAL_TASKS` with a done callback to discard from the set.
      Note: V2 fix -- declared `async def`, awaited at call site; feature-flag
      DB reads are inside this async function.
- [x] import random added to chats.py imports (V4 fix).
- [x] Run `python3 -m py_compile backend/routers/chats.py`.

**Acceptance criteria:**
```bash
python3 -m py_compile backend/routers/chats.py && echo "PASS: py_compile"
grep -n "_BG_EVAL_TASKS\|_run_groundedness_eval\|_maybe_fire_groundedness_eval" \
  backend/routers/chats.py | wc -l | awk '{if($1>=3) print "PASS: symbols present"; else print "FAIL"}'
```

---

## Task 5 -- Extend _assembled_system_prompt and wire background task

**V1/JD-001 correction:** `rag_block` is local to `_assembled_system_prompt`
(line 243) and not returned. The function return at line 286 returns
`(assembled, sse_rag_meta)` only. The background task needs the raw RAG text
separately from the assembled system prompt. Two sub-tasks:

### Task 5a -- Extend _assembled_system_prompt return signature

- [x] In `backend/routers/chats.py`, changed return to `return assembled, sse_rag_meta, rag_block`.
      `rag_block = ""` initialization added BEFORE `rag_ok = (` (V5 fix -- covers all code paths).
- [x] Updated type hint to `tuple[str, dict[str, int] | None, str]`.
- [x] Updated call site in chats.py to unpack three values:
      `assembled, rag_sse_meta, rag_block_text = await _assembled_system_prompt(...)`.
- [x] Updated `services/inference_job.py:108` (V1 fix): `assembled, rag_sse_meta, _rag_block_text = await _assembled_system_prompt(...)`.
- [x] Updated `scripts/verify_safeguards_assembler.py:74,98` (V1 fix): both sites use `assembled, rag_meta, _rag_block = ...`.
- [x] Run `python3 -m py_compile backend/routers/chats.py`.

### Task 5b -- Wire _maybe_fire_groundedness_eval

- [x] Added `await _maybe_fire_groundedness_eval(...)` after `summarize_and_compress`
      and before the guard_alert SSE yield. V2 fix: declared async and awaited.
      Placement is after all pool.acquire() blocks in gen().
- [x] Confirmed the call is NOT inside any pool.acquire() block.
- [x] Run `python3 -m py_compile backend/routers/chats.py`.

**Acceptance criteria:**
```bash
# Enable eval in DB then send a test message (requires running stack):
docker exec hlh_db psql -U hlh -d hlh -c \
  "UPDATE global_settings SET value='true' WHERE key='groundedness_eval_enabled';"

# Send a message through the chat endpoint, wait 10s, check score was written:
# (Replace CHAT_ID and MSG_ID with actual UUIDs from a test chat.)
# docker exec hlh_db psql -U hlh -d hlh -tAc \
#   "SELECT groundedness_score FROM messages WHERE id='<MSG_ID>'::uuid;"
# Expected: a float between 0 and 1 (or NULL if gemma-tasks model not loaded).

docker logs hlh_api 2>&1 | grep "groundedness eval" | tail -5
# Expected: at least one "groundedness eval: msg=... score=..." log line.
```

---

## Task 6 -- Smoke test gemma-tasks routing

- [x] N/A: V6/ctx DECISION -- judge uses workspace chat provider, not gemma-tasks.
      gemma-tasks smoke test is moot. Live verification of judge JSON validity
      via the workspace provider remains as REMAINING LIVE VERIFICATION.
- [ ] Verify the `gemma-tasks` model slot is populated on the running stack:
```bash
docker exec hlh_api python3 -c "
import asyncio, httpx
async def check():
    r = await httpx.AsyncClient().get('http://hlh_chat:8080/v1/models')
    models = [m['id'] for m in r.json().get('data',[])]
    print('gemma-tasks present:', 'gemma-tasks' in models)
    print('models:', models)
asyncio.run(check())
"
```
- [ ] If `gemma-tasks` is NOT present (model not downloaded), document the result
      in a comment in `eval_judge.py` and confirm that `resolve_judge_provider`
      returns the bundled provider + `"gemma-tasks"` model string regardless (the
      LLM call will fail with a 400/404 from llama-server and `call_llm_as_judge`
      will soft-fail, returning `score=None`).
- [ ] Verify that a judge call with `model="gemma-tasks"` against a running
      `hlh_chat` returns valid JSON (or a graceful error), not a Python exception:
```bash
docker exec hlh_api python3 -c "
import asyncio, json, httpx

async def test():
    r = await httpx.AsyncClient(timeout=30.0).post(
        'http://hlh_chat:8080/v1/chat/completions',
        json={
            'model': 'gemma-tasks',
            'messages': [
                {'role': 'system', 'content': 'Reply with exactly: {\"score\": 0.9, \"explanation\": \"test\", \"violations\": []}'},
                {'role': 'user', 'content': 'Context: x\n\nResponse to evaluate: x\n\nEvaluate.'}
            ],
            'stream': False,
        },
    )
    print('status:', r.status_code)
    if r.status_code == 200:
        content = r.json()['choices'][0]['message']['content']
        print('response:', content[:200])
    else:
        print('error:', r.text[:200])

asyncio.run(test())
"
```
Expected: HTTP 200 and a response containing JSON. A 404 means gemma-tasks model
is not loaded; document and continue (the background task will soft-fail).

---

## Task 7 -- Verify reasoning_strip does not affect gemma-tasks output

- [x] N/A: V6/ctx DECISION -- judge uses workspace chat provider (MedGemma or Qwen).
      MedGemma wraps output in thought blocks. `_parse_eval_response` will try JSON
      fallback patterns if direct parse fails; `score=None` returned on parse failure
      (soft-fails). Full reasoning_strip integration is REMAINING LIVE VERIFICATION.
- [ ] Confirm `gemma-tasks` (Gemma 3 270M-IT) does NOT produce `<thought>` blocks
      by default (it lacks the MedGemma chain-of-thought training). Check by
      inspecting a real response from Task 6.
- [ ] If `<THINKING>` markers DO appear in the judge output (from `strip_thinking_text`
      wrapping), the JSON parse in `_parse_eval_response` will fail and return
      `score=None`. Verify this soft-fails gracefully by checking logs.
- [ ] No code change needed if Gemma 3 270M does not produce thinking blocks.
      If it does, add a `strip_thinking_text` call to `call_llm_as_judge` before
      passing to `_parse_eval_response`.

**Acceptance criteria:**
```bash
# After Task 6 smoke test: confirm no THINKING markers in judge output.
docker logs hlh_api 2>&1 | grep -i "thinking\|THINKING" | grep "groundedness" | head -5
# Expected: no output (no THINKING blocks from gemma-tasks).
```

---

## Task 8 -- Replace ResponseAnalysisBatch stub

- [x] Extended `ResponseAnalysisBatch.__init__` to accept `user_query: str = ""` and
      `assistant_response: str = ""` kwargs (JD-002 correction).
- [x] `process()` now returns `was_followed=None` instead of `was_followed=True`.
- [x] Added `process_async()` that calls `call_llm_as_judge` via `services.eval_judge`.
      Includes TODO comment for per-guideline structured parsing.
- [x] Confirmed zero call sites outside safeguards_engine.py (grep returns no output).
- [x] Run `python3 -m py_compile backend/services/safeguards_engine.py`.

**Acceptance criteria:**
```bash
python3 -m py_compile backend/services/safeguards_engine.py && echo "PASS: py_compile"
grep -n "was_followed.*True" backend/services/safeguards_engine.py
# Expected: no output (the unconditional True is gone).
```

---

## Task 9 -- Add verify script for eval endpoint

- [x] Create `backend/scripts/verify_groundedness_eval.sh` (executable,
      `set -euo pipefail`). The script must:
      1. Authenticate (POST `/api/auth/login` with admin credentials from env vars
         `HLH_ADMIN_USER` / `HLH_ADMIN_PASS`, capture the `hlh_session` cookie).
      2. Call `POST /api/eval/groundedness` with a known workspace ID, a short
         context, and a response that is clearly grounded.
      3. Assert HTTP 200 and that the `score` field is present in the JSON response
         (note: score may be null if `gemma-tasks` is not loaded -- assert the key
         exists, not that the value is non-null).
      4. Call the endpoint from a non-admin user and assert HTTP 403.
      5. Print PASS/FAIL counts and exit non-zero on any FAIL.
      Note (JD-005 correction): when `gemma-tasks` is absent, the script accepts
      `score: null` as a PASS with a WARNING log. The script cannot verify judge
      scoring correctness without the model loaded. Include a comment stating this
      is a smoke test and full correctness verification requires the model.
      Note (JD-003 correction): add a comment stating that groundedness scoring
      only fires on the non-durable streaming path. If `durable_streaming_enabled=true`,
      checking `messages.groundedness_score` via the API will always return null.

**Acceptance criteria:**
```bash
chmod +x backend/scripts/verify_groundedness_eval.sh
# With running stack and admin credentials in env:
# HLH_ADMIN_USER=admin HLH_ADMIN_PASS=<pass> bash backend/scripts/verify_groundedness_eval.sh
# Expected exit 0 with PASS lines.
```

---

## Cross-cutting verification

- [x] `python3 -m py_compile $(find backend -name '*.py')` -- no errors.
- [ ] `docker compose up --build -d` starts cleanly; `docker logs hlh_api` shows
      no import errors, no schema errors, and the eval router appears in the
      startup OpenAPI scan. (REMAINING LIVE VERIFICATION)
- [ ] `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='messages' AND column_name='groundedness_score';"` outputs `groundedness_score`. (REMAINING LIVE VERIFICATION)
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for each task.
