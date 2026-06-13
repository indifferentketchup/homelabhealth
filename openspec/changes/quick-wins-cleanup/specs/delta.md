# Delta spec: quick-wins-cleanup

**Date:** 2026-06-12

This document records the exact code-level changes for each item. Each section
lists the target file, the before state, and the after state at the relevant lines.

---

## A2 - chats.py source-selection INSERT

**File:** `backend/routers/chats.py`

**Before** (lines 716-724):
```python
for sid in body.source_ids:
    await conn.execute(
        """
        INSERT INTO chat_source_selections (chat_id, source_id)
        VALUES ($1::uuid, $2::uuid)
        """,
        chat_id,
        sid,
    )
```

**After:**
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

**New file:** `backend/scripts/verify_source_selection.sh`

Shell script (see tasks.md for behavioral spec). Must be `chmod +x`. Uses the
same header and `check()` / pass/fail pattern as `verify_providers_crud.sh`.
API base defaults to `http://localhost:9600/api` via `API` env var.

---

## A9 - chats.py hook context reset

**File:** `backend/routers/chats.py`

**Before** (line 1229):
```python
    set_hook_context(hook_ctx)
    await fire_on_user_prompt(user_message_text)

    # --- Approval gate ... ---
    ...
    # rest of function body, potentially hundreds of lines
```

**After:**
```python
    _hook_token = set_hook_context(hook_ctx)
    try:
        await fire_on_user_prompt(user_message_text)

        # --- Approval gate ... ---
        ...
        # rest of function body indented one level inside try
    finally:
        reset_hook_context(_hook_token)
```

The entire post-hook body through the final `return` or generator yield is wrapped
inside the `try`. The indentation increase applies to every line from
`await fire_on_user_prompt` to the last statement of the handler.

---

## S4 - Delete process_pool.py

**File deleted:** `backend/services/process_pool.py`

No other files change.

---

## S8 - Drop image_chunks from schema.sql

**File:** `backend/schema.sql`

**Before** (lines ~619-640):
```sql
-- ────────────────────────────────────────────────────────────────────────────
-- Phase A3: MedSigLIP vision embeddings (2026-05-27).
-- image_chunks stores per-image embeddings from MedSigLIP (1152-dim).
-- Separate from source_chunks (text, 1024-dim bge-m3).
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS image_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID REFERENCES sources(id) ON DELETE CASCADE,
    embedding       vector(1152),
    page_number     INT,
    image_path      TEXT,
    description     TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_image_chunks_embedding
    ON image_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_image_chunks_source_id
    ON image_chunks (source_id);
```

**After** (replace entire block):
```sql
-- ────────────────────────────────────────────────────────────────────────────
-- Phase A3: MedSigLIP removed v1.2.11. Drop residual table and indexes.
-- ────────────────────────────────────────────────────────────────────────────
DROP INDEX IF EXISTS idx_image_chunks_embedding;
DROP INDEX IF EXISTS idx_image_chunks_source_id;
DROP TABLE IF EXISTS image_chunks;
```

---

## S10 - Delete ai-elements directory

**Directory deleted:** `frontend/src/components/ai-elements/` (all 49 files)

No import updates. No other files change.

---

## C4 + C9 - model_puller.py lock and ready-check

**File:** `backend/services/model_puller.py`

These two fixes are applied as a single edit to the `pull_model` function.

**Before** (lines 482-487):
```python
    cancel_event = asyncio.Event()
    _CANCEL_EVENTS[str(model_uuid)] = cancel_event

    try:
        async with _PULL_LOCK:
            await _mark_pulling(pool_or_conn, model_uuid)
```

**After:**
```python
    cancel_event = asyncio.Event()

    try:
        async with _PULL_LOCK:
            current = await _read_row(pool_or_conn, model_uuid)
            if current and current["status"] == "ready":
                logger.info(
                    "model_puller: %s already ready, skipping pull", model_uuid
                )
                return dict(current)
            _CANCEL_EVENTS[str(model_uuid)] = cancel_event
            await _mark_pulling(pool_or_conn, model_uuid)
```

The `finally: _CANCEL_EVENTS.pop(str(model_uuid), None)` at line 581 is
unchanged.

---

## C7 - useStreamOrchestrator.js chat-switch resume

**File:** `frontend/src/hooks/useStreamOrchestrator.js`

**Before** (lines 88-98):
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

**After** (insert a new effect immediately after the existing one):
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

  // Reset resume guard and stop any in-progress durable stream when the active
  // chat changes. This ensures the reconnect effect above can fire for the new
  // chat once durable.busy clears.
  useEffect(() => {
    resumedRef.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId])
```

The `durable.stop()` call is not included in this effect because `stop` is async
and its identity changes on every render. Instead, the existing
`effectiveStop`/`durable.stop()` path in the chat-switch cleanup effect (lines
~184-200) already handles aborting the previous stream when `activeChatId`
changes. Resetting `resumedRef` is sufficient to allow the reconnect effect to
re-evaluate for the new chat once `durable.busy` becomes false.

**File:** `frontend/src/hooks/useDurableChat.js`

No changes. The `if (busy) return` guard in `resume` (line 189) is the correct
final backstop and must not be removed.
