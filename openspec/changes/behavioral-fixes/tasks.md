# Tasks: Behavioral Fixes (A1, A3, A4, A6)

**Date:** 2026-06-12

---

## A1 - Approval gate fix

- [x] **A1-1** `backend/schema.sql`: replace the `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object` guard for `messages_status_check` with the idempotent `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` pattern. Add `approval_pending` to the allowed set: `('streaming', 'complete', 'failed', 'cancelled', 'approval_pending')`.
- [x] **A1-2** `backend/schema.sql`: add `CREATE INDEX IF NOT EXISTS messages_chat_status_pending_idx ON messages (chat_id, status) WHERE status IN ('streaming', 'approval_pending')`.
- [x] **A1-3** `backend/routers/chats.py`: in the `202` approval_pending branch (lines 1251-1264), insert an assistant message row with `status='approval_pending'` before returning. Include `assistant_message_id` in the response body.
- [x] **A1-4** `backend/routers/chats.py`: widen the 409 guard query (lines 1270-1279) from `status = 'streaming'` to `status IN ('streaming', 'approval_pending')`.
- [x] **A1-5** `frontend/src/hooks/useDurableChat.js`: add branch in `sendMessage` for `res?.status === 'approval_pending'`: call `setStreamingMessageId(res.assistant_message_id)`, `setStreamingStatus('approval_pending')`, `setBusy(true)`, start polling. Branch must appear before the `setBusy(false)` fallthrough.
- [x] **A1-6** `backend/scripts/verify_approval_gate.sh`: create verify script per the design. Test: 202 with assistant_message_id, row exists with approval_pending status, second POST returns 409. -- verified: script created and made executable
- [x] **A1-7** Compile-check: `python3 -m py_compile backend/routers/chats.py`.
- [x] **A1-8** Build-check frontend: `cd frontend && npm run build`.

---

## A3 - provider_client resolver for bundled chat

- [x] **A3-1** `backend/services/provider_client.py`: add `resolve_bundled_chat_provider() -> tuple[Provider, str] | None`. Returns `(provider, model_alias)` for the bundled chat row at the active tier, or `None` on external tier / setup incomplete / row missing. Import `TIER_CHAT_MODELS` lazily inside the function body.
- [x] **A3-2** `backend/services/compaction.py`: remove the `CHAT_URL` module constant. Rewrite `_generate_summary` to call `resolve_bundled_chat_provider()` and use the returned provider's base URL and `build_headers`. Return `None` when the resolver returns `None`.
- [x] **A3-3** `backend/services/vision.py`: remove the `VISION_URL` module constant. Rewrite `_call_vision` to call `resolve_bundled_chat_provider()` and use the returned provider's base URL and `build_headers`. Keep `VISION_MODEL = "medgemma"` as the request model. Return `None` when the resolver returns `None`.
- [x] **A3-4** Verification: `grep -rn 'http://hlh_chat' backend/services/` returns zero matches.
- [x] **A3-5** Compile-check: `python3 -m py_compile backend/services/provider_client.py backend/services/compaction.py backend/services/vision.py`.

---

## A4 - Partitioned BM25 for priority sources

- [x] **A4-1** `backend/services/rag.py` `retrieve_context`: compute `non_priority_ids = [sid for sid in source_ids if sid not in priority_set]` before the BM25 prefilter call.
- [x] **A4-2** `backend/services/rag.py`: pass `non_priority_ids` (not `source_ids`) to `_bm25_prefilter`. Guard the call with `if non_priority_ids:` to avoid passing an empty list (which the function already handles, but the guard makes intent explicit).
- [x] **A4-3** `backend/services/rag.py`: pass `non_priority_ids` to the general pool vector query instead of `source_ids`. Update the `$4::uuid[]` bind parameter accordingly.
- [x] **A4-4** `backend/services/rag.py`: replace the conditional `if bm25_ids: ... else: ...` priority query block with a single unconditional query that has no `AND sc.id = ANY(...)` clause. The priority query always operates on `priority_set` source IDs without a BM25 gate.
- [x] **A4-5** Compile-check: `python3 -m py_compile backend/services/rag.py`.

---

## A6 - Flush failure surfacing and startup sweep

- [x] **A6-1** `backend/services/inference_job.py`: add `_flush_fail_count = 0` as a nonlocal variable in the enclosing `run_inference_job` scope. Modify `_do_flush` to increment the counter on failure, log the attempt number, and re-raise on the third consecutive failure. Reset the counter to 0 on success.
- [x] **A6-1b** `backend/services/inference_job.py` lines 287-291: replace the bare `except Exception: pass` around `await last_flush_task` with `except Exception: raise`. This surfaces the re-raised exception from `_do_flush` (on 3rd failure) to the outer `except Exception as exc` handler at line 478, which calls `_mark_failed`.
- [x] **A6-2** `backend/main.py`: add a one-shot startup sweep in the `lifespan` function after `apply_schema()`. UPDATE messages with `status = 'streaming'` and `COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'` to `status = 'failed'` with `error_message = 'process restart: inference interrupted'`. Log the count of swept rows.
- [x] **A6-3** Compile-check: `python3 -m py_compile backend/services/inference_job.py backend/main.py`.

---

## Cross-cutting

- [x] **X1** Full compile sweep after all changes: `python3 -m py_compile $(find backend -name '*.py')`.
- [x] **X2** Frontend build: `cd frontend && npm run build` -- must complete with no errors.
- [ ] **X3** Smoke test: `docker compose up --build -d`, tail `docker logs -f hlh_api` and confirm startup completes without errors.
- [x] **X4** Update `CHANGELOG.md` `[Unreleased]` section with entries for A1, A3, A4, A6.
