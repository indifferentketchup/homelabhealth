# Delta spec: cursor-persistence (E2)

**Date:** 2026-06-13

## Why

`run_supervisor_worker` (`supervisor_worker.py:399-438`) holds sub-questions and
completed answers entirely in memory. `WaveScheduler.run` (`conductor.py:88-143`)
holds `wave_index` and `results` in local variables. A process crash mid-wave
discards all completed work and restarts the entire multi-step job from zero on
the next client reconnect. Adding `orchestration_cursor` to the `messages` table
and writing it incrementally enables crash-recovery resume.

`history_writer.py` is a pure markdown export helper and is not involved.
Cursor writes happen inside the inference task path.

Validation source: E.md item 3 (confirmed gap; column lives in `messages` not
`global_settings`; `history_writer.py` confusion resolved).

## ADDED Requirements

### Requirement: messages table SHALL have orchestration_cursor column

`backend/schema.sql` SHALL add `orchestration_cursor JSONB` to the `messages`
table via idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. The column SHALL
be nullable so existing non-orchestrated rows are unaffected.

#### Scenario: column is present after migration

- **WHEN** `schema.sql` is applied to any DB
- **THEN** `orchestration_cursor` SHALL exist as a nullable JSONB column on `messages`
- **AND** existing rows SHALL have `orchestration_cursor = NULL`
- **AND** the migration SHALL be idempotent (no error on second application)

### Requirement: run_supervisor_worker SHALL write orchestration_cursor after the worker gather completes

`run_supervisor_worker` in `backend/services/supervisor_worker.py` SHALL accept
optional `conn` and `message_id` parameters. When both are provided, after the
`asyncio.gather` call returns with the full answers list, it SHALL execute:

```
UPDATE messages SET orchestration_cursor = $1::jsonb WHERE id = $2
```

with a JSON payload `{"type": "supervisor_worker", "sub_questions": [...],
"completed": {sub_question: answer, ...}, "wave_index": null}`.

The `json.dumps` call SHALL be used (not a raw dict) per asyncpg JSONB convention.

#### Scenario: cursor is written after gather completes

- **WHEN** `run_supervisor_worker` is called with valid `conn` and `message_id`
- **AND** the worker gather completes
- **THEN** `orchestration_cursor` on the message row SHALL be non-null
- **AND** the payload type SHALL be "supervisor_worker"

#### Scenario: cursor is not written when conn is None

- **WHEN** `run_supervisor_worker` is called without `conn` or `message_id`
- **THEN** no DB write is attempted and the function completes normally

### Requirement: run_supervisor_worker SHALL resume from existing cursor

`run_supervisor_worker` in `backend/services/supervisor_worker.py` SHALL read
`orchestration_cursor` from the message row when `conn` and `message_id` are
provided. If the cursor has `type='supervisor_worker'` and non-empty `completed`
entries, sub-questions already present in `completed` SHALL be skipped and only
remaining sub-questions SHALL be dispatched to new workers.

#### Scenario: completed sub-questions are skipped on resume

- **WHEN** the message row has a cursor with `completed = {"Q1": "answer1"}`
  and `sub_questions = ["Q1", "Q2"]`
- **WHEN** `run_supervisor_worker` is called
- **THEN** only Q2 SHALL be dispatched to a new worker
- **AND** Q1's answer SHALL be used from the cursor

### Requirement: WaveScheduler.run SHALL accept conn and message_id and write cursor

`WaveScheduler.run` in `backend/services/conductor.py` SHALL accept optional
`conn` and `message_id` parameters (both default `None`). After each wave barrier
completes, if both are provided, it SHALL write the cursor with payload
`{"type": "wave_scheduler", "sub_questions": null, "completed": {step_id: output},
"wave_index": wave_index}`.

#### Scenario: wave cursor is written after wave barrier

- **WHEN** `WaveScheduler.run` is called with `conn` and `message_id`
- **AND** a wave completes
- **THEN** `orchestration_cursor` on the message row SHALL be non-null with type
  `"wave_scheduler"`

#### Scenario: backward compatibility when conn is None

- **WHEN** `WaveScheduler.run` is called without `conn` or `message_id`
- **THEN** behavior is identical to the current implementation (no cursor writes)
