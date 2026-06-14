# Design: lift-durable-orchestration

**Date:** 2026-06-13

---

## E1 - Retry budget for orphaned streaming rows

### Problem

Both the background sweeper (`_streaming_sweeper`, `main.py:86-109`) and the
lifespan startup sweep (`main.py:127-143`) move `status='streaming'` rows
directly to `status='failed'` in a single step. There is no retry counter, so a
transient OOM or SIGKILL that resolves within seconds permanently fails the job
even though the frontend would have successfully resumed on the next client
reconnect (auto-resume is in place via `useStreamOrchestrator.js:88-98`).

The actual orphan window is at most ~6 minutes on a live system (60 s sweeper
sleep + 5-minute threshold). The lifespan sweep covers rows older than 10 minutes.
These windows are acceptable, but the direct-to-failed promotion is not.

### Design

Add two columns to `messages`:

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS retry_count  INT NOT NULL DEFAULT 0;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS max_retries  INT NOT NULL DEFAULT 3;
```

No `status` value changes are needed; `retry_count` and `max_retries` do not
affect the `messages_status_check` constraint. The CHECK constraint is NOT touched.

Update both sweepers with a two-branch UPDATE:

```sql
-- Branch 1: budget exhausted -> fail permanently
UPDATE messages
SET status = 'failed',
    finished_at = NOW(),
    error_message = 'inference timed out (retry budget exhausted)'
WHERE status = 'streaming'
  AND COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes'
  AND retry_count >= max_retries;

-- Branch 2: budget remaining -> increment and leave as streaming for client resume
UPDATE messages
SET retry_count = retry_count + 1
WHERE status = 'streaming'
  AND COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes'
  AND retry_count < max_retries;
```

The lifespan sweep uses the same two-branch pattern with the 10-minute threshold.

**Target maximum orphan window:** ~6 minutes on a live system (unchanged from
current behavior for the permanently-failed path). With `max_retries = 3` and
sweeper firing every 60 s, a row can remain `streaming` for up to ~3 sweeper
cycles (3 minutes) before the budget is exhausted -- at which point the frontend
auto-resume will have already retried via the `durable.busy` path. The final
`failed` transition happens at most 6 minutes from the crash.

### Verification

```bash
# After applying: columns exist
docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT column_name FROM information_schema.columns \
   WHERE table_name='messages' AND column_name IN ('retry_count','max_retries');"
# Expected: retry_count, max_retries (two rows)

# Manually insert a stale streaming row and wait two sweeper cycles
docker exec hlh_db psql -U hlh -d hlh -c \
  "INSERT INTO messages (chat_id, role, content, status, created_at)
   SELECT id, 'assistant', 'test', 'streaming', NOW() - INTERVAL '6 minutes'
   FROM chats LIMIT 1;"
# After 2 sweeper cycles (120 s), row should have retry_count=2 and still be streaming
# After 3 cycles (180 s), row should be status='failed'
docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT status, retry_count FROM messages WHERE content='test' ORDER BY created_at DESC LIMIT 1;"
```

---

## E2 - Cursor persistence for supervisor-worker and conductor

### Problem

`run_supervisor_worker` (`supervisor_worker.py:399-438`) holds `sub_questions`
and `answers` as pure in-memory locals. `WaveScheduler.run`
(`conductor.py:88-143`) holds `wave_index`, `done`, and `results` as local
variables. A process crash mid-wave discards all completed work and restarts
from zero on the next client reconnect.

`history_writer.py` is a pure markdown export helper (timestamp-slug +
`render_chat_markdown`). It does NOT manage `messages.status` flushes and is not
involved in cursor persistence. The cursor write must happen inside the inference
task path.

### Decision: cursor column lives in `messages`

E.md blocking unknown 5 asked for a decision between:
- `orchestration_cursor JSONB` column in `messages` (schema change, cursor
  co-located with the message row it describes)
- a `global_settings` row keyed to `(chat_id, run_id)` (no schema change)

**Decision: `messages` column.** The cursor describes the state of a specific
assistant message's multi-step job. Co-locating it on the message row ensures
it is cleaned up automatically on `messages` cascade delete and avoids a
`global_settings` key collision under concurrent chats. The column is nullable
so existing rows are unaffected.

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS orchestration_cursor JSONB;
```

### Cursor schema (JSONB)

For supervisor-worker:

```json
{
  "type": "supervisor_worker",
  "sub_questions": ["Q1", "Q2", "Q3"],
  "completed": {"Q1": "answer text", "Q2": "answer text"},
  "wave_index": null
}
```

For conductor WaveScheduler:

```json
{
  "type": "wave_scheduler",
  "sub_questions": null,
  "completed": {"step_id": "output text"},
  "wave_index": 2
}
```

### Write site: supervisor_worker

After each `_answer_sub_question` completes, write the cursor. The
`run_supervisor_worker` function signature already receives the
`assistant_message_id` (passed through `inference_job.py`). Add a `pool`
parameter or use the same connection passed to the calling context.

Pattern (asyncpg, `json.dumps` required per CLAUDE.md):

```python
await conn.execute(
    """
    UPDATE messages
    SET orchestration_cursor = $1::jsonb
    WHERE id = $2
    """,
    json.dumps(cursor_payload),
    assistant_message_id,
)
```

### Write site: conductor WaveScheduler

`WaveScheduler.run` does not currently receive a DB connection or message ID.
Add optional `conn` and `message_id` parameters (both `None` by default --
backward compatible). After each wave barrier completes, write the cursor if
both are provided.

### Resume logic

On `run_supervisor_worker` entry:

```python
existing_cursor = await conn.fetchval(
    "SELECT orchestration_cursor FROM messages WHERE id = $1",
    assistant_message_id,
)
if existing_cursor and existing_cursor.get("type") == "supervisor_worker":
    completed = existing_cursor.get("completed", {})
    sub_questions = existing_cursor.get("sub_questions", [])
    # skip already-completed sub_questions
```

### Verification

```bash
# Trigger a multi-step chat query, kill hlh_api mid-inference, restart
docker compose restart hlh_api
# Check that orchestration_cursor is non-null on the assistant message
docker exec hlh_db psql -U hlh -d hlh -tAc \
  "SELECT id, status, orchestration_cursor IS NOT NULL
   FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 5;"
```

---

## E3 - Stall and doom-loop detector

### Problem

`_answer_sub_question` and `WaveScheduler._run_step` have no guard against a
worker that repeatedly returns semantically identical low-information responses
or that calls the same tool with identical arguments on every turn. Both
conditions waste tokens and block wave progress.

### Source

`/home/samkintop/opt/forks/hive/core/framework/agent_loop/internals/stall_detector.py`

Two pure functions, no class dependencies, no external imports beyond `json`
(already a stdlib dependency):

- `is_stalled(recent_responses, threshold, similarity_threshold)`: Jaccard
  n-gram similarity across N consecutive responses.
- `is_tool_doom_loop(recent_tool_fingerprints, threshold)`: exact fingerprint
  match across N consecutive tool-call turns.

### Integration: new module

Copy the two functions verbatim into a new file:
`backend/services/stall_detector.py`

No changes to imports or signatures. Remove the `from __future__ import
annotations` line only if Python 3.12 does not require it (it does not hurt to
keep it).

### Integration: supervisor_worker

In `_answer_sub_question`, accumulate responses in a local `_recent_responses`
list (reset per call) and check `is_stalled` after each LLM response:

```python
from services.stall_detector import is_stalled

_STALL_THRESHOLD = 3
_STALL_SIMILARITY = 0.85

# After each content = await _llm_call(...):
_recent_responses.append(content)
if is_stalled(_recent_responses[-_STALL_THRESHOLD:], _STALL_THRESHOLD, _STALL_SIMILARITY):
    logger.warning("stall detected in sub-question worker, aborting: %s", sub_question[:80])
    return WorkerAnswer(
        sub_question=sub_question,
        answer="[Worker stalled: repeated low-information responses detected.]",
        error="stall_detected",
    )
```

Note: `_answer_sub_question` currently makes a single `_llm_call`. The stall
check is meaningful only if the worker becomes multi-turn in future. For now,
wire it so the infrastructure is in place and the check is a no-op (list length
will always be 1). The `is_tool_doom_loop` check applies once tool calls are
introduced to workers.

### Integration: conductor WaveScheduler

In `WaveScheduler._run_step` (or the `run` loop), accumulate per-step outputs
and check `is_stalled` across wave outputs:

```python
from services.stall_detector import is_stalled, is_tool_doom_loop

_WAVE_STALL_THRESHOLD = 3
_WAVE_STALL_SIMILARITY = 0.90

# In run(), after each wave's outputs are collected:
wave_outputs_window.append([o for o in outputs if isinstance(o, str)])
if len(wave_outputs_window) >= _WAVE_STALL_THRESHOLD:
    flat = [" ".join(w) for w in wave_outputs_window[-_WAVE_STALL_THRESHOLD:]]
    if is_stalled(flat, _WAVE_STALL_THRESHOLD, _WAVE_STALL_SIMILARITY):
        raise RuntimeError(
            f"conductor: wave stall detected at wave {wave_index} "
            f"(outputs are not progressing)"
        )
```

### Verification

```bash
python3 -c "
from backend.services.stall_detector import is_stalled, is_tool_doom_loop
# Stall: three identical responses
assert is_stalled(['the sky is blue', 'the sky is blue', 'the sky is blue'], 3, 0.85) == True
# No stall: different responses
assert is_stalled(['alpha', 'beta', 'gamma'], 3, 0.85) == False
# Doom loop: two identical fingerprints
fp = [('search', '{\"q\": \"test\"}')]
assert is_tool_doom_loop([fp, fp, fp], 3)[0] == True
print('stall_detector: all assertions pass')
"
```

---

## E4 - ContextHandoff for wave output concatenation (secondary)

### Problem

`WaveScheduler.run` builds a `results` dict of `{step_id: output_text}`. The
caller (typically an agentic router) receives the raw dict and may concatenate
all values for downstream context. For long multi-wave runs the concatenated text
grows unboundedly and exceeds token limits.

### Source

`/home/samkintop/opt/forks/hive/core/framework/orchestrator/context_handoff.py`

The extractive fallback (`_extractive_summary`) needs no LLM: it takes the first
and last assistant messages, truncates each to 500 chars, and joins them. This
maps naturally to the first and last wave output strings.

### Integration: new module

Create `backend/services/context_handoff.py`. The module needs only:

- `HandoffContext` dataclass (`source_node_id`, `summary`, `key_outputs`,
  `turn_count`, `total_tokens_used`)
- `extractive_summary(outputs: list[str], truncate: int = 500) -> str`: take
  first and last strings from `outputs`, truncate each to `truncate` chars,
  join with double newline.
- `format_as_input(source_id: str, summary: str, turn_count: int) -> str`:
  render the header block.

Do NOT port the `NodeConversation` dependency or the LLM abstractive path. The
homelabhealth version is a standalone extractive-only helper. The LLM path
(mapping to `provider_client`) is left for a future task with a clear reopen
trigger (when wave outputs routinely exceed 8 k tokens).

### Integration: conductor WaveScheduler

Add an optional `compress_context: bool = False` parameter to `WaveScheduler.run`.
When `True` and when the concatenated `results` values exceed a threshold (e.g.,
4000 chars), replace them with a `format_as_input` summary before the next wave.

This is a non-breaking, opt-in change. Default is `False`.

### Verification

```bash
python3 -c "
from backend.services.context_handoff import extractive_summary, format_as_input
outputs = ['First wave output ' * 50, 'Second wave output ' * 50, 'Third wave output ' * 50]
s = extractive_summary(outputs)
assert len(s) <= 1100  # 500 + 500 + separator
print('context_handoff: extractive_summary ok, len =', len(s))
header = format_as_input('wave-1', s, 3)
assert 'CONTEXT FROM' in header
print('context_handoff: format_as_input ok')
"
```

---

## Dependency ordering

1. E1 (schema + sweeper) -- no dependency, apply first.
2. E2 (schema + cursor writes) -- depends on schema migration from E1 being
   present (same migration block in `schema.sql`).
3. E3 (stall_detector module + wiring) -- no dependency on E1/E2.
4. E4 (context_handoff module + wiring) -- no dependency on E1/E2/E3.

E1 and E3/E4 can be applied in parallel by different agents. E2 must follow E1
(same `schema.sql` edit block). In practice, all four fit a single commit batch.

## Guardrails

**Must have:**
- All schema changes are `ADD COLUMN IF NOT EXISTS` (idempotent on existing DBs).
- `messages_status_check` constraint is NOT touched (status values unchanged).
- Cursor writes use `json.dumps(payload)` not raw dict (asyncpg JSONB rule).
- `stall_detector.py` and `context_handoff.py` have no imports outside stdlib
  and the homelabhealth package.
- E4 compression is opt-in (`compress_context=False` by default).

**Must NOT have:**
- A new sweeper task (augment existing `_streaming_sweeper` and lifespan sweep).
- A new `job_runs` or `cursor_store` table.
- `SELECT ... FOR UPDATE SKIP LOCKED` (not needed, single asyncio event loop).
- Any change to `history_writer.py`.
- Any LangGraph dependency.

## Backward compatibility

All schema changes are additive. Existing `messages` rows get `retry_count = 0`,
`max_retries = 3`, `orchestration_cursor = NULL`. The sweeper logic degrades
gracefully for rows with the default `retry_count = 0` (they will be retried up
to 3 times before failing, an improvement over the prior immediate-fail behavior).
