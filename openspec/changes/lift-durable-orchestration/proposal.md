# Proposal: lift-durable-orchestration

**Date:** 2026-06-13
**Status:** proposed

## Summary

Harden the durable-streaming and multi-step orchestration subsystems so that
a process crash, OOM, or mid-wave failure leaves no permanent data loss and no
doom-looping worker. Four targeted additions to existing machinery -- no new
tables, no new sweeper loops, no new dependencies beyond pure Python logic
already proven in the hive reference implementation.

## Motivation

The E-cluster adversarial validation (2026-06-13,
`/home/samkintop/opt/forks/_hlh_lift/validation/E.md`) confirmed four real gaps
and overturned one headline claim:

**Corrected claim:** Orphaned `status='streaming'` rows are NOT silently lost
forever. `main.py` already has a 60 s background sweeper (5-minute threshold)
and a startup sweep (10-minute threshold). The frontend `useStreamOrchestrator.js`
auto-resumes any `streaming` row on page load. The actual orphan window is at
most ~6 minutes on a live system (sweeper sleep + threshold), not indefinite.

**Confirmed gap E1 -- retry budget.** The sweeper transitions all orphaned rows
directly to `status='failed'` in one step. There is no `retry_count` guard, so a
transient OOM that clears within seconds permanently fails the job. Adding
`retry_count` + `max_retries` columns lets the sweeper retry up to N times and
only promote to `failed` when the budget is exhausted. The target maximum orphan
window stays ~6 minutes (unchanged), but recovery from transient crashes is now
automatic.

**Confirmed gap E2 -- cursor persistence.** `run_supervisor_worker` (lines
399-438, `supervisor_worker.py`) holds sub-questions and completed answers
entirely in memory. `WaveScheduler.run` (`conductor.py` lines 88-143) holds
`wave_index` and `results` in a local dict. A mid-wave crash discards all
completed sub-questions and restarts from zero. Adding an `orchestration_cursor`
JSONB column to `messages` and writing it after each worker or wave completes
enables resume-from-cursor on restart. The cursor write lives inside the
inference task -- `history_writer.py` is a markdown export helper and is not
involved.

**Confirmed gap E3 -- stall and doom-loop detection.** `_answer_sub_question`
and `WaveScheduler._run_step` have no guard against a worker that repeatedly
returns the same low-information response or repeatedly calls the same tool with
identical arguments. The hive `stall_detector.py` provides two pure functions
(`is_stalled`, `is_tool_doom_loop`) with zero class dependencies that can be
dropped in.

**Secondary -- ContextHandoff.** The conductor currently concatenates raw wave
outputs end-to-end (lines ~400-470, `conductor.py`). For long multi-wave runs
this grows unboundedly. The hive `context_handoff.py` extractive fallback
(first + last assistant turn, truncated to 500 chars each) needs no LLM call and
fits cleanly as an opt-in compression step between waves.

## Source references

- Retry/dead-letter pattern: hive `progress_db.py:424-470`
- Cursor persistence: hive `cursor_persistence.py:123-157`
- Stall detector: hive `stall_detector.py:1-106`
- ContextHandoff (extractive path): hive `context_handoff.py:1-188`
- Validation report: `/home/samkintop/opt/forks/_hlh_lift/validation/E.md`

## Scope

| ID  | Files touched                                                              | Type             |
|-----|----------------------------------------------------------------------------|------------------|
| E1  | `backend/schema.sql`, `backend/main.py`                                    | Bug fix / hardening |
| E2  | `backend/schema.sql`, `backend/services/supervisor_worker.py`, `backend/services/conductor.py` | Bug fix |
| E3  | new `backend/services/stall_detector.py`, `backend/services/supervisor_worker.py`, `backend/services/conductor.py` | Feature (pure drop-in) |
| E4  | new `backend/services/context_handoff.py`, `backend/services/conductor.py` | Feature (secondary) |

## Out of scope

- Per-tool HITL interrupt: LangGraph-bound, no homelabhealth tool-call
  architecture exists yet.
- RuntimeLogger: requires storage-layer redesign (file-backed JSONL incompatible
  with `read_only: true` containers).
- TaskStore: `asyncio.gather` already provides implicit wait-for-all;
  dependency graph adds no value without conditional branching.
- Swarm active-agent handoff: LangGraph dependency is a non-starter.
- New sweeper loop or new `job_runs` table: the messages table already carries
  all required columns.
- `SELECT ... FOR UPDATE SKIP LOCKED`: not needed, single-process asyncio event
  loop.

## Risk

Low to medium. E1 and E2 are schema-additive (idempotent `ADD COLUMN IF NOT
EXISTS`). E3 adds a new module with no side effects; the integration touch-points
are two async functions. E4 (secondary) is a single new module plus a one-line
call in `WaveScheduler.run`. The messages `status` CHECK constraint
(`messages_status_check`) must be re-dropped and re-added whenever the constraint
inline list changes; E1 does not change the `status` values, so the constraint is
not touched.
