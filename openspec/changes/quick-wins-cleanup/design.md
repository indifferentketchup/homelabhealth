# Design: quick-wins-cleanup

**Date:** 2026-06-12

---

## A2 - Source-selection INSERT missing NOT NULL position column

### Problem

`backend/routers/chats.py` `put_source_selection` (line ~717) inserts into
`chat_source_selections` without the `position` column, which is declared
`INTEGER NOT NULL` in `schema.sql` (line 143). The INSERT fails at runtime with a
NOT NULL constraint violation for every call to `PUT /api/chats/{id}/sources`.

### Fix

Change the INSERT loop to use `enumerate` and pass the ordinal as `position`:

```python
for i, sid in enumerate(body.source_ids):
    await conn.execute(
        """
        INSERT INTO chat_source_selections (chat_id, source_id, position)
        VALUES ($1::uuid, $2::uuid, $3)
        """,
        chat_id,
        sid,
        i,
    )
```

### Verify script

Add `backend/scripts/verify_source_selection.sh`. The script:

1. Creates a workspace and two sources via the API.
2. Calls `PUT /api/chats/{id}/sources` with both source IDs.
3. Asserts HTTP 200 and that the response `source_ids` array matches.
4. Calls `GET /api/chats/{id}/sources` and asserts the same two IDs are returned.
5. Prints PASS/FAIL counts and exits non-zero on any failure.

---

## A9 - Hook context token never reset

### Problem

In `backend/routers/chats.py` (line 1229), `set_hook_context(hook_ctx)` is called
but the returned `contextvars.Token` is discarded. `reset_hook_context` (imported
at line 48) is never called. This means the hook context set for one request leaks
into other coroutines that share the same asyncio Task, and the ContextVar stack
grows unboundedly under concurrent requests.

### Fix

Capture the token, then reset it in a `finally` block wrapping the downstream work
from the hook call onward. The hook call and fire already sit near the top of the
post-guard section; wrapping from there to the end of the handler body covers all
exit paths (approval-pending early returns, durable path, SSE path):

```python
_hook_token = set_hook_context(hook_ctx)
try:
    await fire_on_user_prompt(user_message_text)
    # ... rest of handler ...
finally:
    reset_hook_context(_hook_token)
```

Because `post_messages` is an async function with many early-return branches, the
`finally` must wrap the entire post-hook body to cover every branch.

---

## S4 - Delete dead process_pool.py

### Problem

`backend/services/process_pool.py` has no importers. `grep -rn process_pool
backend/` returns only self-references within the file. The module was superseded
but never removed.

### Fix

Delete `backend/services/process_pool.py`. No other files change.

---

## S8 - Drop dead image_chunks table and HNSW index

### Problem

`backend/schema.sql` (lines 624-640) creates `image_chunks` and two indexes
(`idx_image_chunks_embedding` HNSW, `idx_image_chunks_source_id`). This table was
added for MedSigLIP (removed v1.2.11). The table is empty on all running
instances. The HNSW index is expensive to maintain on every startup that inspects
the schema.

### Fix

Prepend idempotent DROP statements before the `CREATE TABLE IF NOT EXISTS
image_chunks` block:

```sql
DROP INDEX IF EXISTS idx_image_chunks_embedding;
DROP INDEX IF EXISTS idx_image_chunks_source_id;
DROP TABLE IF EXISTS image_chunks;
```

The existing `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` lines
that follow are left in place but become no-ops after the DROPs run. Alternatively,
remove the CREATE lines entirely; either approach is correct, but removing them
avoids schema drift confusion. The DROP-then-omit approach is preferred.

Do NOT touch any CHECK constraint, any `providers_role_check` constraint, or any
other table.

---

## S10 - Delete dead ai-elements component suite

### Problem

`frontend/src/components/ai-elements/` contains 49 files. `grep -rn ai-elements
frontend/src/` returns zero hits outside the directory itself. The suite is
unreferenced and adds ~49 files of maintenance noise.

### Fix

Delete the entire `frontend/src/components/ai-elements/` directory. No import
updates are needed because there are no consumers.

---

## C4 - model_puller cancel event registered before the lock

### Problem

In `backend/services/model_puller.py` `pull_model` (lines 482-483):

```python
cancel_event = asyncio.Event()
_CANCEL_EVENTS[str(model_uuid)] = cancel_event   # <- outside lock

try:
    async with _PULL_LOCK:
        ...
finally:
    _CANCEL_EVENTS.pop(str(model_uuid), None)     # <- also outside lock
```

If task A is about to acquire the lock (suspended on `async with _PULL_LOCK`) and
task B completes and runs its `finally` pop, the pop removes A's `cancel_event`
from the dict because A registered it before B released the lock. A cancellation
sent while A holds the lock will no longer be deliverable.

### Fix

Move the `_CANCEL_EVENTS` assignment to inside the lock body, immediately after
`async with _PULL_LOCK:`:

```python
cancel_event = asyncio.Event()

try:
    async with _PULL_LOCK:
        _CANCEL_EVENTS[str(model_uuid)] = cancel_event
        await _mark_pulling(pool_or_conn, model_uuid)
        ...
finally:
    _CANCEL_EVENTS.pop(str(model_uuid), None)
```

The `finally` pop remains outside the lock (correct: it should always clean up
even if the lock was never fully entered, though in practice the lock is the first
thing entered).

---

## C7 - useDurableChat.resume() silently dropped on chat switch

### Problem

In `frontend/src/hooks/useStreamOrchestrator.js` (lines 88-98):

```js
const resumedRef = useRef(null)
useEffect(() => {
  if (!durableEnabled || durable.busy || !activeChatId || !messages.length) return
  if (resumedRef.current === activeChatId) return
  const streaming = messages.find((m) => m.role === 'assistant' && m.status === 'streaming')
  if (streaming) {
    resumedRef.current = activeChatId
    durable.resume(activeChatId, streaming.id)
  }
}, [durableEnabled, durable.busy, activeChatId, messages])
```

When the user switches to a new chat that has a `status: 'streaming'` assistant
row, `durable.busy` may still be `true` from the previous chat. The effect returns
early on line 3 (`if (!durableEnabled || durable.busy || ...)`), so `resume` is
never called. `resumedRef` is never reset on chat switch, so even after `busy`
clears the second condition (`resumedRef.current === activeChatId`) will never fire
for the new chat if any prior attempt was made.

In `frontend/src/hooks/useDurableChat.js` (line 188-189):

```js
const resume = useCallback((chatId, assistantMessageId) => {
  if (busy) return
```

The `busy` guard is the correct final defense, but it is hit too early when the
caller is the reconnect effect above.

### Fix

Two changes:

1. In `useStreamOrchestrator.js`: add a second `useEffect` that fires when
   `activeChatId` changes, resets `resumedRef.current` to `null`, and calls
   `durable.stop()` so that `durable.busy` is cleared before the reconnect effect
   tries `resume`:

   ```js
   useEffect(() => {
     resumedRef.current = null
     if (durable.busy) {
       durable.stop()
     }
   }, [activeChatId])
   ```

   Note: `durable.stop()` is intentionally not listed as a dependency; including
   it would fire on every render. Use `// eslint-disable-next-line` or extract a
   stable ref.

2. In `useDurableChat.js`: the `resume` guard `if (busy) return` stays in place as
   a final backstop. No change needed here beyond ensuring `stop()` (which calls
   `setBusy(false)`) is called synchronously before the reconnect effect runs.
   Because `stop()` is async (it awaits `stopChatInference`), the `busy` state
   will not be `false` synchronously. The reconnect effect dependency on
   `durable.busy` means it will re-fire once `busy` drops to `false` after `stop`
   completes, picking up the resume naturally. The key fix is that `resumedRef` is
   reset on chat switch so the `resumedRef.current === activeChatId` guard is
   cleared.

---

## C9 - Double-submitted pull re-downloads a completed model

### Problem

In `backend/services/model_puller.py` `pull_model` (line 486), after acquiring
`_PULL_LOCK` the function immediately calls `_mark_pulling` without first checking
whether the model is already `ready`. If two callers race on a just-completed pull
(e.g., a retry click while the success write is committing) the second caller
acquires the lock and starts a full re-download.

### Fix

After `async with _PULL_LOCK:`, re-read the DB row and return early if the status
is already `ready`:

```python
async with _PULL_LOCK:
    current = await _read_row(pool_or_conn, model_uuid)
    if current and current["status"] == "ready":
        logger.info("model_puller: %s already ready, skipping pull", model_uuid)
        return dict(current)
    _CANCEL_EVENTS[str(model_uuid)] = cancel_event   # moved here per C4
    await _mark_pulling(pool_or_conn, model_uuid)
    ...
```

The C4 and C9 fixes to `model_puller.py` are applied together in the same edit
since they both modify the top of the `async with _PULL_LOCK:` block.
