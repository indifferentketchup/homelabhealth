# Tasks: lift-durable-orchestration

**Date:** 2026-06-13

Tasks are grouped by item. E1 and E3/E4 are independent and may be applied in
parallel. E2 depends on the schema block from E1 being present.

---

## E1-1 - Add retry_count and max_retries columns to messages

- [x] In `backend/schema.sql`, after the existing durable-streaming ALTER TABLE
      block (after line 609, `ALTER TABLE messages ADD COLUMN IF NOT EXISTS
      error_message TEXT;`), add:
      ```sql
      -- E1: retry budget for orphaned streaming rows (lift-durable-orchestration, 2026-06-13).
      ALTER TABLE messages ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
      ALTER TABLE messages ADD COLUMN IF NOT EXISTS max_retries INT NOT NULL DEFAULT 3;
      ```
- [x] Run `python3 -m py_compile $(find backend -name '*.py')` -- schema.sql is
      not Python; this confirms no Python breakage.
- [ ] Verify idempotency: apply the ALTER TABLE block twice against the running DB
      (via `docker exec hlh_db psql -U hlh -d hlh`) and confirm no error on the
      second run. (LIVE STACK REQUIRED)

**Acceptance:** `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT column_name
FROM information_schema.columns WHERE table_name='messages' AND column_name IN
('retry_count','max_retries');"` returns two rows.

---

## E1-2 - Update background sweeper with two-branch retry logic

- [x] In `backend/main.py`, replace the body of `_streaming_sweeper` (lines
      86-109) with the two-branch UPDATE pattern described in design.md E1:
      Branch 1 (budget exhausted): `WHERE status='streaming' AND
      COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes' AND
      retry_count >= max_retries` -> set `status='failed'`, `finished_at=NOW()`,
      `error_message='inference timed out (retry budget exhausted)'`.
      Branch 2 (budget remaining): same WHERE but `retry_count < max_retries` ->
      `SET retry_count = retry_count + 1` only (leave `status='streaming'`).
      Log both branches with count at INFO level.
- [x] Confirm the `for row in swept: await job_registry.cancel(...)` call remains
      only on the Branch 1 (failed) rows, not on Branch 2 rows (retried rows
      still have a live client).
- [x] Run `python3 -m py_compile backend/main.py`.

**Acceptance:** Insert a test `streaming` row with `created_at = NOW() - INTERVAL
'6 minutes'` and `retry_count = 0`. After one sweeper cycle (60 s), confirm
`retry_count = 1` and `status = 'streaming'`. After three more cycles, confirm
`status = 'failed'`.

---

## E1-3 - Update lifespan startup sweep with two-branch retry logic

- [x] In `backend/main.py`, replace the lifespan startup sweep block (lines
      127-143) with the same two-branch logic using a 10-minute threshold.
      Branch 1: `retry_count >= max_retries` -> fail. Branch 2: increment
      `retry_count`.
- [x] Log at INFO level for each branch.
- [x] Run `python3 -m py_compile backend/main.py`.

**Acceptance:** `docker compose up --build -d` starts cleanly. `docker logs
hlh_api` shows no errors in the lifespan sweep section.

---

## E2-1 - Add orchestration_cursor column to messages

- [x] In `backend/schema.sql`, directly after the E1 columns added in E1-1, add:
      ```sql
      -- E2: orchestration cursor for supervisor-worker and conductor resume
      -- (lift-durable-orchestration, 2026-06-13).
      ALTER TABLE messages ADD COLUMN IF NOT EXISTS orchestration_cursor JSONB;
      ```
- [ ] Verify idempotency: apply twice, no error on second run. (LIVE STACK REQUIRED)

**Acceptance:** `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT column_name
FROM information_schema.columns WHERE table_name='messages' AND
column_name='orchestration_cursor';"` returns one row.

---

## E2-2 - Write cursor in run_supervisor_worker after each worker completes

- [x] In `backend/services/supervisor_worker.py`, update `run_supervisor_worker`
      to accept two new optional keyword parameters: `conn` (asyncpg connection,
      default `None`) and `message_id` (UUID, default `None`).
- [x] After `asyncio.gather(*worker_tasks)` returns, build a cursor payload dict
      from the full `answers` list and write it to the DB. (V1 fix applied:
      cursor is written after gather completes, not per-worker.)
      Only write if `conn` and `message_id` are not `None`.
- [x] Add resume logic at the top of `run_supervisor_worker`: if `conn` and
      `message_id` are provided, read `orchestration_cursor` from the messages
      row; if it has `type='supervisor_worker'` and non-empty `completed`, skip
      those sub-questions. If cursor sub_questions do not match the new
      decomposition, resume silently falls through to a full re-gather (V2 fix).
- [x] `import json` was already present in `supervisor_worker.py`.
- [x] Run `python3 -m py_compile backend/services/supervisor_worker.py`.

**Acceptance:** `grep -n 'orchestration_cursor\|json.dumps' backend/services/supervisor_worker.py`
returns hits. A test multi-step query leaves a non-null `orchestration_cursor`
on the assistant message row after completion: `docker exec hlh_db psql -U hlh
-d hlh -tAc "SELECT orchestration_cursor IS NOT NULL FROM messages WHERE
role='assistant' ORDER BY created_at DESC LIMIT 1;"` returns `t`.

---

## E2-3 - Write cursor in WaveScheduler.run after each wave barrier

- [x] In `backend/services/conductor.py`, add `conn` and `message_id` optional
      keyword parameters to `WaveScheduler.run` (both default `None`).
- [x] After each wave completes, build a cursor payload and write it to the DB
      using the same pattern as E2-2. The payload type is `'wave_scheduler'`.
      V3 note added in docstring: this is a no-op until called from a path that
      has a message ID (run_analysis creates no durable message row).
- [x] `import json` added at the top of `conductor.py`.
- [x] Run `python3 -m py_compile backend/services/conductor.py`.

**Acceptance:** `grep -n 'orchestration_cursor' backend/services/conductor.py`
returns hits. After a conductor-driven multi-wave inference, the assistant
message row shows a non-null `orchestration_cursor` with `type='wave_scheduler'`.

---

## E3-1 - Create backend/services/stall_detector.py

- [x] Created `backend/services/stall_detector.py` with all four functions
      verbatim from hive stall_detector.py: `ngram_similarity`, `is_stalled`,
      `fingerprint_tool_calls`, `is_tool_doom_loop`. Kept `from __future__ import
      annotations` and `import json`. Module docstring added.
- [x] Run `python3 -m py_compile backend/services/stall_detector.py`.
- [x] Inline assertions from design.md E3 verification block: all pass.

**Acceptance:** `python3 -c "from services.stall_detector import is_stalled,
is_tool_doom_loop; print('ok')"` (run from `backend/`) returns `ok`.

---

## E3-2 - Wire stall detector into _answer_sub_question

- [x] Added `from services.stall_detector import is_stalled` at the top of
      `supervisor_worker.py`.
- [x] Added module-level constants `_STALL_THRESHOLD = 3` and `_STALL_SIMILARITY = 0.85`.
- [x] In `_answer_sub_question`, added `_recent_responses: list[str] = []` local
      list. Appends `content` to it, calls `is_stalled(...)`, returns stall
      `WorkerAnswer` if True.
- [x] No-op with single _llm_call (list length 1); hook is in place for future
      multi-turn workers.
- [x] Run `python3 -m py_compile backend/services/supervisor_worker.py`.

**Acceptance:** `grep -n 'is_stalled\|_STALL_THRESHOLD' backend/services/supervisor_worker.py`
returns hits.

---

## E3-3 - Wire doom-loop detector into WaveScheduler.run

- [x] Added `from services.stall_detector import is_stalled, is_tool_doom_loop`
      at the top of `conductor.py`.
- [x] Added module-level constants `_WAVE_STALL_THRESHOLD = 3` and
      `_WAVE_STALL_SIMILARITY = 0.90`.
- [x] In `WaveScheduler.run`, added `wave_outputs_window: list[list[str]] = []`.
      After each wave, appends string outputs; checks `is_stalled` across last
      threshold entries; raises `RuntimeError` on stall.
- [x] Run `python3 -m py_compile backend/services/conductor.py`.

**Acceptance:** `grep -n 'is_stalled\|wave_outputs_window' backend/services/conductor.py`
returns hits.

---

## E4-1 - Create backend/services/context_handoff.py (secondary)

- [x] Created `backend/services/context_handoff.py` with:
      - `_TRUNCATE_CHARS = 500` constant.
      - `extractive_summary(outputs, truncate) -> str`: first + last truncated,
        joined with double newline. "Empty conversation." for empty input.
      - `format_as_input(source_id, summary, turn_count) -> str`: header block.
      No external imports beyond stdlib.
- [x] Run `python3 -m py_compile backend/services/context_handoff.py`.
- [x] Inline assertions from design.md E4 verification block: all pass.

**Acceptance:** `python3 -c "from services.context_handoff import
extractive_summary, format_as_input; print('ok')"` (from `backend/`) returns
`ok`.

---

## E4-2 - Wire ContextHandoff into WaveScheduler.run (secondary)

- [x] Added `from services.context_handoff import extractive_summary, format_as_input`
      at the top of `conductor.py`.
- [x] Added `compress_context: bool = False` keyword parameter to `WaveScheduler.run`.
- [x] After each wave, if `compress_context=True` and total results length exceeds
      4000 chars, replaces results with `extractive_summary(...)` under
      `"_context_summary"`. Logs at DEBUG level when compression fires.
- [x] Default `False` -- no behavior change for existing callers.
- [x] Run `python3 -m py_compile backend/services/conductor.py`.

**Acceptance:** `grep -n 'compress_context\|extractive_summary' backend/services/conductor.py`
returns hits. Instantiate `WaveScheduler` with a mock provider in a unit test
(or via `python3 -c`) and confirm `compress_context=False` produces unchanged
behavior.

---

## Cross-cutting verification

- [x] `python3 -m py_compile $(find backend -name '*.py')` -- no errors.
- [ ] `docker compose up --build -d` -- stack starts cleanly. (LIVE STACK REQUIRED)
- [ ] `docker logs hlh_api` -- no import errors, no schema errors, no CHECK
      constraint violations on startup. (LIVE STACK REQUIRED)
- [ ] `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT column_name FROM
      information_schema.columns WHERE table_name='messages' ORDER BY
      column_name;"` -- `max_retries`, `orchestration_cursor`, `retry_count` all
      present. (LIVE STACK REQUIRED)
- [ ] Submit a multi-step chat query; confirm `orchestration_cursor IS NOT NULL`
      on the resulting assistant message row (E2 end-to-end). (LIVE STACK REQUIRED)
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for E1, E2, E3,
      E4 grouped under `## AI`.
