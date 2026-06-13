# Tasks: quick-wins-cleanup

**Date:** 2026-06-12

Each task is independent. They may be implemented in any order or in parallel
except where noted.

---

## A2 - Source-selection INSERT missing position column

- [x] In `backend/routers/chats.py` `put_source_selection`, change the INSERT loop
      to use `enumerate(body.source_ids)` and pass the ordinal as the `position`
      parameter. Column list becomes `(chat_id, source_id, position)` with
      placeholders `($1::uuid, $2::uuid, $3)`.
- [x] Create `backend/scripts/verify_source_selection.sh` (executable, `set -euo
      pipefail`). Script must: authenticate or skip auth if the stack is in
      single-user mode, create a test workspace and two test sources, call
      `PUT /api/chats/{id}/sources`, assert 200 and correct `source_ids` in the
      response, call `GET /api/chats/{id}/sources` and assert both IDs are present,
      clean up test rows, print PASS/FAIL counts, exit non-zero on any failure.
- [x] Run `python -m py_compile backend/routers/chats.py` to confirm no syntax
      errors.
- [ ] Smoke-test: with the stack running, call the endpoint and confirm no
      NOT NULL error in `docker logs hlh_api`.

---

## A9 - Hook context token never reset

- [ ] In `backend/routers/chats.py` `post_messages`, change line 1229 to capture
      the return value: `_hook_token = set_hook_context(hook_ctx)`.
- [ ] Wrap the remaining body of the function (from the `set_hook_context` call to
      the last `return`) in a `try: ... finally: reset_hook_context(_hook_token)`
      block. All existing early-return branches must remain inside the `try`.
- [ ] Run `python -m py_compile backend/routers/chats.py`.
- [ ] Verify indentation is consistent throughout the wrapped block.

---

## S4 - Delete dead process_pool.py

- [x] Confirm zero importers: `grep -rn process_pool backend/ | grep -v
      'process_pool.py'` must produce no output.
- [x] Delete `backend/services/process_pool.py`.
- [x] Run `python -m py_compile $(find backend -name '*.py')` to confirm no import
      breakage.

---

## S8 - Drop dead image_chunks table and HNSW index

- [x] In `backend/schema.sql`, immediately before the `-- Phase A3` comment block
      (line 619), insert:
      ```sql
      DROP INDEX IF EXISTS idx_image_chunks_embedding;
      DROP INDEX IF EXISTS idx_image_chunks_source_id;
      DROP TABLE IF EXISTS image_chunks;
      ```
- [x] Remove the now-unreachable `CREATE TABLE IF NOT EXISTS image_chunks` block
      and its two `CREATE INDEX IF NOT EXISTS` statements (lines 624-640) to avoid
      schema drift confusion.
- [x] Do NOT touch any CHECK constraint, `providers_role_check`, or any other
      table.
- [ ] Verify idempotency: run the DROP block twice against a running DB and confirm
      no errors on the second run (`IF EXISTS` guarantees this, but confirm).

---

## S10 - Delete dead ai-elements component suite

- [x] Confirm zero external consumers: `grep -rn ai-elements
      frontend/src/ | grep -v 'frontend/src/components/ai-elements/'` must produce
      no output.
- [x] Delete the entire `frontend/src/components/ai-elements/` directory.
- [x] Run `cd frontend && npm run build` and confirm no missing-module errors.

---

## C4 - model_puller cancel event registered before the lock

- [x] In `backend/services/model_puller.py` `pull_model`, move the line
      `_CANCEL_EVENTS[str(model_uuid)] = cancel_event` from before the `try:` /
      `async with _PULL_LOCK:` to immediately after `async with _PULL_LOCK:`,
      before `await _mark_pulling(...)`.
- [x] Confirm the `finally: _CANCEL_EVENTS.pop(str(model_uuid), None)` remains
      outside the lock at the end of the `try` block (no change needed there).
- [x] Run `python -m py_compile backend/services/model_puller.py`.

  Note: apply this task together with C9 since both edits touch the same block.

---

## C7 - useDurableChat.resume() silently dropped on chat switch

- [x] In `frontend/src/hooks/useStreamOrchestrator.js`, add a `useEffect` that
      depends only on `activeChatId`. Inside it: set `resumedRef.current = null`
      and call `durable.stop()` if `durable.busy` is true. Add an ESLint disable
      comment if needed to suppress the exhaustive-deps warning for `durable.stop`.
      Place this effect immediately before or after the existing reconnect effect
      (lines 88-98).
- [x] Confirm the existing reconnect effect dependency array still includes
      `durable.busy` so it re-fires once `stop()` resolves and `busy` becomes
      false.
- [x] No changes to `frontend/src/hooks/useDurableChat.js` are required (the
      `if (busy) return` guard in `resume` is correct as a backstop).
- [x] Run `cd frontend && npm run build` to confirm no type or import errors.
- [ ] Manual smoke test: open two chats where one has a `status: 'streaming'`
      assistant row (simulate by pausing the backend mid-stream), switch between
      them, and confirm the second chat resumes correctly.

---

## C9 - Double-submitted pull re-downloads a completed model

- [x] In `backend/services/model_puller.py` `pull_model`, immediately after
      `async with _PULL_LOCK:`, add a re-read of the DB row using `_read_row` and
      return early if `status == 'ready'`. Log at INFO level before returning.
- [x] This edit is applied in the same block as C4 (the top of `async with
      _PULL_LOCK:`). Apply C4 first, then insert the status check below the newly
      moved `_CANCEL_EVENTS` assignment.
- [x] Run `python -m py_compile backend/services/model_puller.py`.
- [ ] Smoke test: trigger two rapid pulls of the same model UUID and confirm only
      one HTTP download occurs in the logs.

---

## Cross-cutting verification

- [x] After all tasks are applied: `python -m py_compile $(find backend -name
      '*.py')` produces no errors.
- [x] `cd frontend && npm run build` produces no errors.
- [ ] `docker compose up --build -d` starts cleanly; `docker logs hlh_api` shows
      no import errors or schema errors on startup.
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for each fix.
