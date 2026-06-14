# Design: lift-groundedness-eval

**Date:** 2026-06-13

---

## Step 0 -- Mount the eval router

### Problem

`backend/routers/eval.py` defines `router = APIRouter()` with three POST
endpoints (`/groundedness`, `/helpfulness`, `/retrieval-relevance`). None appear
in the `api.include_router(...)` chain in `backend/main.py` (lines 310-331).
All three endpoints 404 on the running stack.

### Fix

Add one line to `backend/main.py`, grouped with the other router mounts:

```python
from routers import eval as eval_router          # add to imports block
api.include_router(eval_router.router, prefix="/eval", tags=["eval"])
```

The router already uses `Depends(require_admin)` on every endpoint, so no
auth change is needed.

### Verify

```bash
curl -s -X POST http://localhost:9600/api/eval/groundedness \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"00000000-0000-0000-0000-000000000000","query":"x","context":"x","response":"x"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','ok'))"
```
Expected: 403 Forbidden (admin-only, not 404).

---

## Step 1 -- Extract eval_judge service module

### Problem

`_call_llm_as_judge`, `_parse_eval_response`, and `_build_eval_response` live
inside `backend/routers/eval.py`. If `chats.py` imports from a router module,
it creates a coupling from core business logic to an HTTP-layer module. FastAPI
also discourages importing across routers. The circular-import risk is real:
`eval.py` imports from `deps.py` which imports from `db.py`; `chats.py` is in
the same import graph.

### Fix

Create `backend/services/eval_judge.py` containing:

- `_parse_eval_response(raw: str) -> dict` -- verbatim copy from eval.py
- `_normalize_score(raw: Any) -> float | None` -- verbatim copy
- `_build_eval_response(data: dict) -> dict` -- verbatim copy
- `call_llm_as_judge(provider, model, system_prompt, user_prompt) -> dict`
  -- renamed to public (no leading underscore), verbatim logic copy
- `GROUNDEDNESS_SYSTEM_PROMPT` / `GROUNDEDNESS_USER_PROMPT` -- verbatim copy
  from eval.py. The user prompt uses `{context}` and `{response}` slots (NOT
  `{outputs}` -- the openevals RAG_GROUNDEDNESS_PROMPT uses `{outputs}` but
  eval.py's medical-domain prompt uses `{response}`; keep `{response}` to match
  the existing prompt without a rename that breaks the endpoint).
- `resolve_judge_provider(workspace_id: uuid.UUID | None) -> tuple[Provider, str]`
  -- helper that picks the right provider: on bundled tier use `gemma-tasks`
  (270M, fast); on external tier fall back to the workspace provider.

Then update `eval.py` to import from `services.eval_judge` rather than
re-defining the helpers. No endpoint behavior changes.

### gemma-tasks routing

`hlh_chat/models.ini` section `[gemma-tasks]` is a Gemma 3 270M-IT model with
`ctx-size = 512`. At 512 tokens the groundedness prompt + short context fits
comfortably. The bundled provider's `base_url` is the same `hlh_chat` service
used for chat; the only difference is the `"model"` field in the request payload
(`"gemma-tasks"` instead of the chat model alias).

`resolve_judge_provider` logic:

```python
async def resolve_judge_provider(
    workspace_id: uuid.UUID | None,
) -> tuple[Provider, str] | None:
    """
    Bundled tier: use gemma-tasks slot (fast 270M model, avoids blocking chat).
    External tier: use workspace provider.
    Returns None if no provider can be resolved (caller soft-fails).
    """
    from services.provider_client import (
        resolve_bundled_chat_provider,
        resolve_provider_for_workspace,
    )
    bundled = await resolve_bundled_chat_provider()
    if bundled is not None:
        provider, _chat_model = bundled
        return provider, "gemma-tasks"
    if workspace_id is not None:
        try:
            return await resolve_provider_for_workspace(workspace_id)
        except Exception:
            return None
    return None
```

Note: `resolve_bundled_chat_provider` returns `(provider, chat_model_alias)`.
We override the model to `"gemma-tasks"` because the bundled provider serves all
model slots from the same `hlh_chat` base URL.

### Prompt slot note

eval.py's `GROUNDEDNESS_USER_PROMPT` uses `{context}` and `{response}`. The
openevals source prompt uses `{outputs}` instead of `{response}`. This design
retains `{response}` throughout (both in `eval_judge.py` and in the background
task call) to keep the medical-domain prompt unchanged. No rename is needed.

---

## Step 2 -- Schema: groundedness_score column

### Problem

There is no column to store the numeric judge output on a message. The existing
`guard_flags JSONB` column (added at `schema.sql:569`) stores regex scan
findings from `scan_output`. Violations from the groundedness judge are
semantically related to guard findings and fit in the same JSONB. The score
itself (0.0-1.0 float) is better stored in a typed column for future queries
(`WHERE groundedness_score < 0.5`).

### Fix

Add one idempotent `ALTER TABLE` to `backend/schema.sql`, at the bottom of the
migration block, after the durable-streaming additions:

```sql
-- Groundedness eval: async judge score per assistant message (lift-groundedness-eval).
-- Null for messages created before this feature, or when eval is disabled/sampled out.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS groundedness_score FLOAT;
```

Violations from the judge are written into `guard_flags` JSONB using the key
`"groundedness_violations"`. The background task does a partial JSONB merge:

```sql
UPDATE messages
SET guard_flags = COALESCE(guard_flags, '{}'::jsonb)
                  || jsonb_build_object(
                       'groundedness_score', $2::float,
                       'groundedness_violations', $3::jsonb
                     ),
    groundedness_score = $2
WHERE id = $1::uuid
```

This preserves existing `guard_flags` entries (regex scan results) while
appending the eval results. Using `||` (jsonb concatenate) is idempotent on
re-run.

### Convention check

CLAUDE.md: "asyncpg + JSONB: pass Python dicts as `json.dumps(d)` strings; do
not pass dicts directly." The background task must pass
`json.dumps(violations_list)` for the `$3` parameter, not the raw list.

---

## Step 3 -- Background task in chats.py

### Problem

After the assistant message INSERT at `chats.py:1718-1733`, no evaluation of
response quality occurs. The `scan_output` call at line 1712 runs sync regex
checks only.

### Context text availability -- V1/JD-001 correction

`_assembled_system_prompt` (`chats.py:112-286`) returns `(assembled, sse_rag_meta)`.
The raw `rag_block` local variable (line 243) is NOT returned; it is folded into
`assembled` alongside workspace instructions, memory facts, and custom instructions.
`sse_rag_meta` contains only `{"count": N, "chars": N}` -- no text.

**Resolution:** Modify `_assembled_system_prompt` to return a third value -- the
raw `rag_block` string (or `""` when no RAG context was retrieved). The return
signature changes from `tuple[str, dict | None]` to `tuple[str, dict | None, str]`.
Every call site in `chats.py` that unpacks the return must be updated. Confirmed
call sites: line 1451 (non-durable path). The durable streaming path must also be
checked. When `rag_block` is empty or `None`, the background task skips scoring.

New return at `chats.py:286`:

```python
return assembled, sse_rag_meta, rag_block   # rag_block may be "" if no RAG
```

Call site update at `chats.py:1451`:

```python
assembled, rag_sse_meta, rag_block_text = await _assembled_system_prompt(
    rag_conn, chat,
    user_query_for_rag=user_message_text,
    include_site_private=True,
)
```

### Fix

After `await summarize_and_compress(str(chat_id), p)` at line 1836, and before
the guard_alert SSE yield at line 1838, add:

```python
# Groundedness eval -- async background task, never inline.
_maybe_fire_groundedness_eval(
    message_id=assist_id,
    workspace_id=workspace_id,
    assistant_text=assistant_text,
    context_text=rag_block_text,
)
```

This placement is AFTER all `pool.acquire()` blocks (the last is inside
`summarize_and_compress` at line 1836), satisfying the "fire outside any
pool.acquire() block" guardrail (V5 correction). The generator is still open
(we have not yielded `[DONE]` yet), so `asyncio.create_task` is valid.

`_maybe_fire_groundedness_eval` is a module-level function in `chats.py` that:

1. Returns immediately if `context_text` is falsy (no RAG context).
2. Reads `groundedness_eval_enabled` from `global_settings`; returns if `false`.
3. Reads `groundedness_eval_sample_rate`; applies `random.random() > float(rate)` skip.
4. Fires `asyncio.create_task(_run_groundedness_eval(...))` and stores the task
   object in the module-level `_BG_EVAL_TASKS: set` with a done-callback to
   remove it on completion. This is a NEW pattern (sources.py:293 uses bare
   `create_task` without a set; this is more robust to prevent GC mid-flight).
5. Never awaits; never raises.

`_run_groundedness_eval` coroutine:

```python
async def _run_groundedness_eval(
    message_id: uuid.UUID,
    workspace_id: uuid.UUID,
    assistant_text: str,
    context_text: str,
) -> None:
    try:
        from services.eval_judge import (
            call_llm_as_judge,
            resolve_judge_provider,
            GROUNDEDNESS_SYSTEM_PROMPT,
            GROUNDEDNESS_USER_PROMPT,
        )
        result = await resolve_judge_provider(workspace_id)
        if result is None:
            logger.info("groundedness eval: no provider, skipping msg %s", message_id)
            return
        provider, model = result
        # V2/JD-004 correction: gemma-tasks ctx-size=512 tokens total.
        # System prompt ~150 tokens, chat template ~20 tokens.
        # Remaining budget ~340 tokens ~ 1360 chars combined.
        # Safe caps: context 900 chars, response 400 chars.
        user_prompt = GROUNDEDNESS_USER_PROMPT.format(
            context=context_text[:900],
            response=assistant_text[:400],
        )
        eval_result = await call_llm_as_judge(
            provider, model, GROUNDEDNESS_SYSTEM_PROMPT, user_prompt
        )
        score = eval_result.get("score")
        violations = eval_result.get("violations") or []
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET groundedness_score = $2,
                    guard_flags = COALESCE(guard_flags, '{}'::jsonb)
                                  || jsonb_build_object(
                                       'groundedness_violations', $3::jsonb
                                     )
                WHERE id = $1::uuid
                """,
                message_id,
                score,
                json.dumps(violations),
            )
        logger.info(
            "groundedness eval: msg=%s score=%s violations=%d",
            message_id, score, len(violations),
        )
    except Exception as exc:
        logger.warning("groundedness eval failed (non-fatal): %s", exc)

### global_settings keys

Two new keys seeded with idempotent INSERT in `schema.sql`:

```sql
INSERT INTO global_settings (key, value) VALUES
    ('groundedness_eval_enabled',     'false'),
    ('groundedness_eval_sample_rate', '1.0')
ON CONFLICT (key) DO NOTHING;
```

Default `false` means the feature is opt-in. Operators enable it via
`PUT /api/settings` (existing settings endpoint; no new endpoint needed).

---

## Step 4 -- gemma-tasks slot routing (in eval_judge.py)

Already described in Step 1's `resolve_judge_provider` design. Key constraint:
`gemma-tasks` has `ctx-size = 512` tokens (confirmed: `hlh_chat/models.ini:43`).

**V2/JD-004 correction -- token budget math:**
At ~4 chars/token (English average):
- `GROUNDEDNESS_SYSTEM_PROMPT` (~600 chars) = ~150 tokens
- Chat template overhead (BOS, role tags) = ~20 tokens
- Remaining budget for context + response = 512 - 170 = ~342 tokens = ~1368 chars

Safe caps (with 10% margin): context `[:900]` chars (~225 tokens), response
`[:400]` chars (~100 tokens). Total ~325 tokens. This fits under 512.

The prior design stated "4000 chars context + 2000 chars response" which totals
~1600 tokens against a 512-token window -- that was a self-contradictory error
corrected here.

---

## Step 5 -- Replace ResponseAnalysisBatch stub

### Problem

`backend/services/safeguards_engine.py:685-696`:

```python
def process(self) -> BatchResult:
    ...
    metadata={"batch_type": "response_analysis", "was_followed": True},
```

Every guideline unconditionally reports `was_followed=True`. The class has zero
call sites. Replacing it now is safe and prevents accidental wiring of the
broken version.

### JD-002 correction -- process_async prompt data sources

`PROMPT_TEMPLATE` (lines 661-676) uses `{user_query}`, `{assistant_response}`, and
`{guidelines_text}`. The current constructor only takes `guideline_matches`. The
constructor must be extended to accept `user_query: str = ""` and
`assistant_response: str = ""` so `process_async` can build the prompt.

### Fix

Extend the constructor and implement both methods:

```python
def __init__(
    self,
    guideline_matches: list[GuidelineMatch],
    user_query: str = "",
    assistant_response: str = "",
) -> None:
    self._guideline_matches = guideline_matches
    self._user_query = user_query
    self._assistant_response = assistant_response

async def process_async(self) -> BatchResult:
    """Real response analysis via LLM judge. Returns was_followed=None when
    no provider is available or judge parse fails."""
    from services.eval_judge import call_llm_as_judge, resolve_judge_provider
    result = await resolve_judge_provider(workspace_id=None)
    if result is None:
        return BatchResult(matches=[
            GuidelineMatch(
                guideline=m.guideline, score=m.score,
                rationale="Response analysis skipped: no judge provider",
                metadata={"batch_type": "response_analysis", "was_followed": None},
            )
            for m in self._guideline_matches
        ])
    provider, model = result
    guidelines_text = "\n".join(
        f"- {m.guideline.content.condition}" for m in self._guideline_matches
    )
    prompt = self.PROMPT_TEMPLATE.format(
        user_query=self._user_query[:500],
        assistant_response=self._assistant_response[:400],
        guidelines_text=guidelines_text,
    )
    eval_result = await call_llm_as_judge(provider, model, "", prompt)
    # TODO: parse per-guideline was_followed from structured eval output.
    return BatchResult(matches=[
        GuidelineMatch(
            guideline=m.guideline, score=m.score,
            rationale=f"Response analysis (judge score={eval_result.get('score')}): "
                      f"{eval_result.get('explanation', '')[:200]}",
            metadata={"batch_type": "response_analysis", "was_followed": None},
        )
        for m in self._guideline_matches
    ])

def process(self) -> BatchResult:
    """Synchronous stub -- returns was_followed=None (not evaluated)."""
    return BatchResult(matches=[
        GuidelineMatch(
            guideline=m.guideline, score=m.score,
            rationale="Response analysis: synchronous stub (not evaluated)",
            metadata={"batch_type": "response_analysis", "was_followed": None},
        )
        for m in self._guideline_matches
    ])
```

The class is still not wired into any call site in this change. Task 8 verifies
zero call sites outside `safeguards_engine.py`.

---

## Guardrails

**Must Have:**
- Background task MUST NOT raise into the streaming response path under any
  circumstances. The `try/except Exception` wrapper is not optional.
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is mandatory. Bare `ALTER TABLE`
  without `IF NOT EXISTS` will error on existing DBs.
- The eval router import in `main.py` MUST be a separate statement:
  `from routers.eval import router as eval_router` (matching the `demo_router`
  pattern at `main.py:39`). Do NOT add `eval` to the grouped
  `from routers import (...)` block -- `as` aliases are not valid inside that
  form and `eval` would shadow the Python built-in. (V6/JD-006 correction.)
- `gemma-tasks` context caps: context `[:900]` chars, response `[:400]` chars.
  Total ~325 tokens against 512-token limit. (V2/JD-004 correction.)
- `_assembled_system_prompt` return signature must be extended to return a third
  value `rag_block: str` so the background task has access to the raw RAG text.
  (V1/JD-001 correction.)
- The background task fire point MUST be after `summarize_and_compress` at line
  1836 and before the guard_alert yield at line 1838. This is the only point
  after all `pool.acquire()` blocks in the `gen()` generator. (V5 correction.)

**Must NOT Have:**
- Do not import the `openevals` package. Extract prompt strings only.
- Do not add langchain or langsmith to `requirements.txt`.
- Do not wire `ResponseAnalysisBatch.process_async` into any call site.
- Do not make the groundedness check synchronous or blocking.
- Do not use `ALTER TABLE ADD COLUMN` without `IF NOT EXISTS` in schema.sql.
- Do not cite `sources.py:293` as the background-task set pattern -- that file
  uses bare `create_task` without a set. The `_BG_EVAL_TASKS` set+done-callback
  pattern is new. (JD-007 correction.)

## Deferred scope (explicitly out of this change)

**Durable streaming path (JD-003):** The background task wiring targets only the
non-durable SSE `gen()` path. The durable streaming path (lines 1325-1415 in
`chats.py`) inserts a placeholder row and delegates to `services/inference_job.py`;
it never reaches the fire point at line 1836. When `durable_streaming_enabled=true`,
no groundedness eval fires. This is an explicit deferral, not an oversight. The
verify script must note this limitation. Future work: wire into `inference_job.py`
post-persist path.

## Backward compatibility

- `groundedness_score` column is nullable; all existing rows are unaffected.
- `guard_flags` JSONB merge uses `||` which is non-destructive to existing keys.
- Eval endpoints are new routes under `/api/eval/`; no existing routes change.
- `ResponseAnalysisBatch.process()` signature is preserved (returns `BatchResult`);
  behavior changes from `was_followed=True` to `was_followed=None`. Zero call
  sites means no consumer is affected.
- `_assembled_system_prompt` return type changes from `tuple[str, dict|None]`
  to `tuple[str, dict|None, str]`. All call sites in `chats.py` must be updated
  to unpack three values.
