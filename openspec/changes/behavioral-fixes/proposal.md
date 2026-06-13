# Proposal: Behavioral Fixes (A1, A3, A4, A6)

**Track:** Behavioral / Correctness  
**Priority:** P0 + P1  
**Status:** Draft  
**Date:** 2026-06-12

## Summary

Four behavioral bugs that cause silent data loss, safeguard bypass, and stale-lock conditions on the durable streaming path. All four are ship-blockers or high-severity regressions introduced during the Wave 1-4 harness work.

---

## A1 - Approval gate is non-functional on the durable streaming path (P0 Critical)

**What breaks today:**

When `should_request_approval()` returns `True` and durable streaming is enabled, the backend returns HTTP 202 with `status: "approval_pending"` but inserts no assistant row. Two downstream failures cascade from this:

1. `useDurableChat.sendMessage` only branches on `res?.status === 'streaming'`. The `approval_pending` response falls through to `setBusy(false)`, leaving the UI idle with the user's message silently discarded and no indication that approval is pending.

2. Because no assistant row exists, the 409 guard (`SELECT id FROM messages WHERE chat_id = $1 AND role = 'assistant' AND status = 'streaming'`) finds nothing. A second POST to `/api/chats/{id}/messages` starts inference immediately, bypassing the safeguard entirely.

**Root cause locations:**
- `backend/routers/chats.py` lines 1251-1264: the `202` branch returns without inserting a row.
- `backend/routers/chats.py` lines 1270-1279: the 409 guard only checks `status = 'streaming'`.
- `frontend/src/hooks/useDurableChat.js` lines 120-128: no branch for `approval_pending`.
- `backend/schema.sql` lines 603-607: `messages_status_check` does not include `approval_pending`.

**Fix scope:** backend row insertion, 409 guard widening, schema constraint update, frontend branch addition, verify script.

---

## A3 - compaction.py and vision.py bypass provider_client (P1)

**What breaks today:**

Both services hardcode `http://hlh_chat:9610`. On the `external` tier, `hlh_chat` is not running. Calls time out silently after 60 seconds (compaction) or 300 seconds (vision). Neither service routes through `provider_client.py`, so:

- De-identification is skipped for compaction summaries sent to an external provider.
- Auth headers are never added, so external providers that require an API key silently 401.
- The operator has no way to use an external summarization model for compaction.

**Root cause locations:**
- `backend/services/compaction.py` line 22: `CHAT_URL = "http://hlh_chat:9610/v1/chat/completions"`.
- `backend/services/vision.py` line 20: `VISION_URL = "http://hlh_chat:9610/v1/chat/completions"`.
- `backend/services/provider_client.py`: no resolver for the bundled chat role.

**Fix scope:** add `resolve_bundled_chat_provider()` to `provider_client.py`; rewrite `_generate_summary` and `_call_vision` to use it. Vision is bundled-only (requires mmproj) so it resolves to the bundled row or skips cleanly.

---

## A4 - Attached sources silently excluded by BM25 filter (P1)

**What breaks today:**

`retrieve_context` runs `_bm25_prefilter` over the entire workspace source list to get `bm25_ids`. The priority query (explicitly attached sources) then filters on `AND sc.id = ANY($4::uuid[])`, so chunks from attached sources that did not rank in the BM25 top-400 are silently dropped.

The code comment at line 393 says "Attached sources are retrieved separately so their chunks can't be crowded out" -- this intent is directly violated by the `AND sc.id = ANY(bm25_ids)` filter that still applies to the priority query. A document attached to a chat about a different topic than its content will contribute zero context.

**Root cause location:**
- `backend/services/rag.py` lines 396-413: `priority_rows` query includes `AND sc.id = ANY($4::uuid[])` when `bm25_ids` is set.

**Fix scope:** run BM25 only over non-priority source IDs. The priority query always fetches all chunks from priority sources ordered by vector distance, with no BM25 gate.

---

## A6 - Streaming row can remain status='streaming' forever under flush failure (P1)

**What breaks today:**

In `inference_job.py`, `_do_flush` catches and swallows all exceptions (line 193). If the DB pool is exhausted or temporarily unavailable during a flush, the row is never updated to `failed`, and the job continues without persisting content. In the worst case the job itself completes but the final `UPDATE ... SET status = 'complete'` also fails (the outer `except Exception` at line 478 calls `_mark_failed`, but if the pool is gone that call also fails -- line 485 catches and logs). The row stays `streaming` until the sweeper fires at 5 minutes.

During those 5 minutes the chat is locked by the 409 guard and the user cannot send any message. The sweeper at `main.py` lines 86-108 runs every 60 seconds but only catches rows older than 5 minutes.

There is no on-startup cleanup. If the process crashes mid-stream (OOM, SIGKILL), any `streaming` row from a previous process run locks the chat until the sweeper fires, and `started_at` is set at inference start (lines 58-60) so the 5-minute window is relative to a potentially stale timestamp.

**Root cause locations:**
- `backend/services/inference_job.py` lines 178-193: flush failures are always swallowed.
- `backend/main.py` lifespan: no startup sweep to clear `streaming` rows from prior process runs.

**Fix scope:** consecutive-failure tracking in `_do_flush` (surface after 3); add a one-shot startup UPDATE in `lifespan` before `yield`.

---

## Out of scope for this change

- Approval gate UI components (approval review panel, approve/reject buttons): deferred to a UI track.
- Vision on external tier (no mmproj available): `is_vision_available()` already gates this; A3 does not change that contract.
- BM25 tuning constants: `_BM25_CANDIDATE_MULTIPLIER`, `TOP_K_RETRIEVE`, `TOP_AFTER_RERANK` are unchanged.
