# Design: Behavioral Fixes (A1, A3, A4, A6)

**Date:** 2026-06-12

---

## A1 - Approval gate fix

### Backend: insert approval_pending row before returning 202

In `backend/routers/chats.py`, the block at lines 1251-1264 that returns 202 must first insert an assistant message row and include its ID in the response body.

The INSERT uses the same shape as the normal durable-streaming placeholder at lines 1282-1290, differing only in `status`:

```python
assist_id = uuid.uuid4()
async with pool.acquire() as conn:
    await conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, content, model, ai_generated, status)
        VALUES ($1::uuid, $2::uuid, 'assistant', '', $3, TRUE, 'approval_pending')
        """,
        assist_id, chat_id, effective_model,
    )
return JSONResponse(
    status_code=202,
    content={
        "user_message_id": str(user_msg_id),
        "assistant_message_id": str(assist_id),
        "status": "approval_pending",
        "approval": {
            "reason": _req.reason,
            "prompt": _req.prompt,
            "options": _req.options,
            "timeout_s": _req.timeout_s,
        },
    },
)
```

The `pool` reference at this point in the handler is the same `pool` acquired from `db.get_pool()` earlier in the function. Use `pool.acquire()` -- do not reuse the existing `conn` that holds the user message INSERT, because that connection has already been released.

### Backend: widen the 409 guard

At lines 1270-1279, change the query from:

```sql
SELECT id FROM messages
WHERE chat_id = $1::uuid AND role = 'assistant' AND status = 'streaming'
```

to:

```sql
SELECT id FROM messages
WHERE chat_id = $1::uuid AND role = 'assistant'
  AND status IN ('streaming', 'approval_pending')
```

This prevents a second POST from bypassing the approval gate by racing through while no row existed. The `messages_chat_status_streaming_idx` partial index at schema line 615 only covers `status = 'streaming'`; that index is not used for the widened query. A new partial index covering both statuses should be added (see schema section below).

### Schema: add approval_pending to the CHECK constraint

The existing pattern at schema lines 603-607 uses a `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$` guard. This pattern cannot modify an existing constraint -- it is insert-or-skip, not replace. To change the allowed set, use the idempotent drop-then-add pattern:

```sql
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_status_check;
ALTER TABLE messages ADD CONSTRAINT messages_status_check
  CHECK (status IN ('streaming', 'complete', 'failed', 'cancelled', 'approval_pending'));
```

Also update the inline `CREATE TABLE messages` definition for fresh-init DBs. In the `CREATE TABLE IF NOT EXISTS messages` block, the `status` column does not currently have an inline CHECK (the constraint is added via `ALTER TABLE` later). No change is needed to the CREATE TABLE block itself. The ALTER TABLE drop+re-add at the end of the migration section is sufficient for both fresh and existing DBs.

Add a new partial index to cover the widened 409 guard:

```sql
CREATE INDEX IF NOT EXISTS messages_chat_status_pending_idx
  ON messages (chat_id, status)
  WHERE status IN ('streaming', 'approval_pending');
```

Note: PostgreSQL partial indexes support `IN` clauses for the WHERE predicate only from version 14+. The stack uses PostgreSQL 16, so this is safe.

### Frontend: handle approval_pending in sendMessage

In `frontend/src/hooks/useDurableChat.js`, `sendMessage` currently has a single branch at lines 120-128:

```js
if (res?.status === 'streaming' && res.assistant_message_id) {
  setStreamingMessageId(res.assistant_message_id)
  setStreamingStatus('streaming')
  pollRef.current = setTimeout(
    () => pollOnce(chatId, res.assistant_message_id),
    POLL_FAST_MS,
  )
  return res
}
setBusy(false)
return res
```

Add a new branch immediately before the `setBusy(false)` fallthrough:

```js
if (res?.status === 'approval_pending' && res.assistant_message_id) {
  setStreamingMessageId(res.assistant_message_id)
  setStreamingStatus('approval_pending')
  setBusy(true)
  pollRef.current = setTimeout(
    () => pollOnce(chatId, res.assistant_message_id),
    POLL_FAST_MS,
  )
  return res
}
```

`pollOnce` already handles the `approval_pending` status correctly: the row exists in the DB, polling will keep checking, and when the approval is resolved the row will transition to `streaming` (if approved) or `cancelled` (if rejected). No changes to `pollOnce` are required.

### Verify script

Add `backend/scripts/verify_approval_gate.sh`. The script should:

1. POST a message that triggers the safeguard (a message containing a term that the test safeguard matches as HIGH/CRITICAL).
2. Assert the response is HTTP 202 with `status: "approval_pending"` and a non-null `assistant_message_id`.
3. Hit `GET /api/chats/{id}/messages` and assert the returned list contains a row with that ID and `status: "approval_pending"`.
4. POST a second message and assert it returns HTTP 409.
5. Hit `DELETE /api/chats/{id}/messages/{id}/stop` (or the discard endpoint) to clean up.

Use `docker exec hlh_api python -c "import asyncio, httpx; ..."` for all HTTP calls per CLAUDE.md conventions.

---

## A3 - provider_client resolver for bundled chat

### New function in provider_client.py

Add after `resolve_reranker_provider`:

```python
async def resolve_bundled_chat_provider() -> tuple[Provider, str] | None:
    """Return the bundled chat provider row and tier-appropriate model alias,
    or None if the system is on the external tier or setup is incomplete.

    Used by services that are always bundled (compaction, vision) and need
    a resolved provider without a workspace context. Returns None rather than
    raising so callers can skip gracefully instead of failing hard.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.name, p.base_url, p.api_key, p.enabled,
                   sp.tier
              FROM providers p
              JOIN system_profile sp ON sp.id = 1
             WHERE p.is_bundled = TRUE
               AND p.role = 'chat'
               AND p.bundle_group = 'homelab-health-ai'
             LIMIT 1
            """,
        )
    if row is None:
        return None
    if not bool(row["enabled"]):
        return None
    provider = Provider(
        id=row["id"],
        name=row["name"],
        base_url=(row["base_url"] or "").rstrip("/"),
        api_key=None,  # bundled has no key
        enabled=True,
    )
    # Derive model alias from tier using TIER_CHAT_MODELS
    from services.bundled_providers import TIER_CHAT_MODELS
    model = TIER_CHAT_MODELS.get(row["tier"] or "")
    if not model:
        return None
    return provider, model
```

The import of `TIER_CHAT_MODELS` is inside the function to avoid a circular import between `provider_client` and `bundled_providers` at module load time.

### compaction.py

Replace the module-level `CHAT_URL` constant and `_generate_summary` HTTP call:

```python
async def _generate_summary(conversation_text: str, existing_summary: str | None) -> str | None:
    from services.provider_client import resolve_bundled_chat_provider, build_headers

    binding = await resolve_bundled_chat_provider()
    if binding is None:
        logger.info("compaction: no bundled chat provider available; skipping summary")
        return None
    provider, model = binding

    prompt_parts = []
    if existing_summary:
        prompt_parts.append(f"Previous conversation summary:\n{existing_summary}\n")
    prompt_parts.append(f"Conversation to summarize:\n{conversation_text}")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    url = f"{provider.base_url}/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=SUMMARY_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=build_headers(provider))
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.error("compaction summary LLM call failed: %s", exc)
        return None
```

Remove the `CHAT_URL` module constant. Keep `SUMMARY_TIMEOUT`.

### vision.py

Replace the module-level `VISION_URL` constant and `_call_vision` HTTP call:

```python
async def _call_vision(image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> str | None:
    from services.provider_client import resolve_bundled_chat_provider, build_headers

    binding = await resolve_bundled_chat_provider()
    if binding is None:
        logger.warning("vision: bundled chat provider not available")
        return None
    provider, _model = binding
    # Vision always uses the 'medgemma' alias -- the llama-server router dispatches
    # by this name to the multimodal preset. The tier model alias from the resolver
    # is not used here because only medgemma loads the mmproj.
    url = f"{provider.base_url}/v1/chat/completions"

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    try:
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=build_headers(provider))
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception as exc:
        logger.warning("vision call failed: %s", exc)
        return None
```

Remove the `VISION_URL` module constant. Keep `VISION_TIMEOUT` and `VISION_MODEL`.

### Verification

After the change, `grep -rn 'http://hlh_chat' backend/services/` must return zero matches.

---

## A4 - Partitioned BM25 for priority sources

### Change in retrieve_context

The BM25 prefilter call at line 344 currently passes `source_ids` -- the full workspace source list including priority sources. Change it to pass only non-priority source IDs:

```python
non_priority_ids = [sid for sid in source_ids if sid not in priority_set]

bm25_ids: list[uuid.UUID] | None = None
if bool(settings.get("rag_bm25_enabled", True)):
    bm25_top_k = TOP_K_RETRIEVE * _BM25_CANDIDATE_MULTIPLIER
    if non_priority_ids:
        bm25_ids = await _bm25_prefilter(query, non_priority_ids, bm25_top_k)
```

Then rewrite the priority query to always use the unconditional form (no `bm25_ids` filter), regardless of whether `bm25_ids` is set for the general pool:

```python
priority_rows = []
if priority_set:
    priority_rows = await conn.fetch(
        """
        SELECT sc.id, sc.text, sc.source_id, s.name AS source_name
        FROM source_chunks sc
        JOIN sources s ON s.id = sc.source_id
        WHERE sc.source_id = ANY($3::uuid[])
          AND sc.embedding IS NOT NULL
        ORDER BY sc.embedding <=> $2::vector
        LIMIT $1
        """,
        TOP_K_RETRIEVE,
        q_vec,
        [uuid.UUID(sid) for sid in priority_set],
    )
```

The general pool query (lines 357-392) is unchanged -- it continues to apply `AND sc.id = ANY($5::uuid[])` when `bm25_ids` is set and to exclude priority source IDs via `source_ids` (note: `source_ids` already includes priority sources in the current code; if we want to avoid double-fetching priority chunks in the general pool, pass `non_priority_ids` to the general pool query instead of `source_ids`). The dedup at lines 435-441 already handles overlap via `seen_chunks`, so double-fetching is harmless but wasteful.

Preferred approach: pass `non_priority_ids` to the general pool query as well. This makes the partition clean -- each query operates on a distinct source set.

```python
general_source_uuids = [uuid.UUID(sid) for sid in non_priority_ids]
# ... general pool query uses general_source_uuids instead of source_ids
```

The merge-and-dedup logic at lines 435-441 is unchanged.

---

## A6 - Flush failure surfacing and startup sweep

### Consecutive-failure counter in _do_flush

Replace the current `_do_flush` closure with a version that counts consecutive failures and re-raises on the third:

```python
_flush_fail_count = 0

async def _do_flush(content_snapshot: str, prev_task: asyncio.Task | None) -> None:
    nonlocal _flush_fail_count
    if prev_task is not None:
        try:
            await prev_task
        except Exception:
            pass
    try:
        encrypted = encrypt_column(content_snapshot, str(assistant_id))
        async with pool.acquire() as flush_conn:
            await flush_conn.execute(
                "UPDATE messages SET content = $2 WHERE id = $1::uuid",
                assistant_id,
                encrypted,
            )
        _flush_fail_count = 0
    except Exception as exc:
        _flush_fail_count += 1
        logger.warning(
            "inference_job: flush failed (attempt %d/3) assistant_id=%s: %s",
            _flush_fail_count, assistant_id, exc,
        )
        if _flush_fail_count >= 3:
            raise
```

When `_do_flush` raises on the third consecutive failure, the `asyncio.create_task` that wraps it will store the exception. However, the current code at lines 287-291 wraps `await last_flush_task` in `try: ... except Exception: pass`, which swallows the exception. The fix MUST also modify that block so the flush exception reaches the outer `except Exception` at line 478 (which calls `_mark_failed`).

Replace the bare `except Exception: pass` at lines 287-291 with a check of `last_flush_task.exception()`: if the task failed, re-raise so the outer handler catches it and calls `_mark_failed`. This is the minimal change that surfaces flush failures.

```python
if last_flush_task is not None:
    try:
        await last_flush_task
    except Exception:
        # If _do_flush re-raised after 3 consecutive failures, surface it
        # so the outer except Exception handler calls _mark_failed.
        raise
```

The `raise` here is safe because `last_flush_task` was created by `asyncio.create_task(_do_flush(...))`. When `_do_flush` raises on the third failure, `await last_flush_task` re-raises that exception. The bare `except Exception` block must re-raise so it propagates to the outer `except Exception as exc` at line 478, which calls `_mark_failed`.

### Startup sweep in lifespan

In `backend/main.py`, inside the `lifespan` function, after `await apply_schema()` and before `yield`, add:

```python
async with pool.acquire() as conn:
    swept = await conn.fetch(
        """
        UPDATE messages
        SET status = 'failed',
            finished_at = NOW(),
            error_message = 'process restart: inference interrupted'
        WHERE status = 'streaming'
          AND COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'
        RETURNING chat_id
        """,
    )
    if swept:
        logger.info(
            "lifespan: cleared %d stale streaming rows from prior process run",
            len(swept),
        )
```

The 10-minute threshold is intentionally more conservative than the running sweeper's 5-minute threshold. The sweeper handles freshly-stale rows during normal operation; the startup sweep is a last resort for rows that survived a process crash. Setting the threshold higher avoids false-positives during fast restarts where an in-progress job might legitimately be less than 5 minutes old at the moment the new process starts.

Note: the startup sweep runs after `apply_schema()` so the `status` column is guaranteed to exist.
