# Delta spec: retry-budget (E1)

**Date:** 2026-06-13

## Why

The background sweeper (`main.py:86-109`) and lifespan startup sweep
(`main.py:127-143`) both transition orphaned `status='streaming'` messages
directly to `status='failed'` in one step. A transient OOM or SIGKILL that
resolves within seconds permanently fails the job, even though the frontend
would have resumed successfully on the next client reconnect. Adding a retry
budget lets transient failures recover automatically without operator action.

Validation source: E.md item 1 (orphan window bounded ~6 min, retry layer
confirmed missing).

## ADDED Requirements

### Requirement: messages table SHALL have retry_count and max_retries columns

`backend/schema.sql` SHALL add two columns to the `messages` table via
idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`:

- `retry_count INT NOT NULL DEFAULT 0`
- `max_retries INT NOT NULL DEFAULT 3`

The `messages_status_check` constraint SHALL NOT be modified. No new status
values are introduced.

#### Scenario: columns are present after schema migration

- **WHEN** `schema.sql` is applied against any DB (fresh or existing)
- **THEN** `retry_count` and `max_retries` columns SHALL exist on the `messages` table
- **AND** existing rows SHALL have `retry_count = 0` and `max_retries = 3`
- **AND** no error SHALL be raised on a second application (idempotent)

#### Scenario: default values apply to new message rows

- **WHEN** a new assistant message row is inserted without specifying `retry_count`
- **THEN** `retry_count` SHALL be `0` and `max_retries` SHALL be `3`

### Requirement: background sweeper SHALL use two-branch retry logic

`_streaming_sweeper` in `backend/main.py` SHALL replace its single-UPDATE body
with two UPDATE statements per cycle:

Branch 1 (budget exhausted): rows WHERE `status='streaming'` AND
`COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes'` AND
`retry_count >= max_retries` SHALL be set to `status='failed'`,
`finished_at=NOW()`, `error_message='inference timed out (retry budget exhausted)'`.

Branch 2 (budget remaining): rows matching the same time condition AND
`retry_count < max_retries` SHALL have `retry_count` incremented by 1.
`status` SHALL remain `'streaming'`.

`job_registry.cancel` SHALL be called only for Branch 1 (permanently failed) rows.

#### Scenario: first sweeper pass increments retry_count

- **WHEN** a `streaming` row has `retry_count=0` and `created_at = NOW() - 6min`
- **AND** the sweeper fires
- **THEN** `retry_count` SHALL be `1` and `status` SHALL remain `'streaming'`

#### Scenario: budget exhausted transitions to failed

- **WHEN** a `streaming` row has `retry_count=3` (equal to `max_retries`) and
  `created_at = NOW() - 6min`
- **AND** the sweeper fires
- **THEN** `status` SHALL be `'failed'` and `retry_count` SHALL remain `3`

#### Scenario: fresh row below time threshold is not touched

- **WHEN** a `streaming` row has `created_at = NOW() - 1min`
- **AND** the sweeper fires
- **THEN** neither `status` nor `retry_count` SHALL change

### Requirement: lifespan startup sweep SHALL use the same two-branch retry logic

The startup sweep block in `lifespan` in `backend/main.py` SHALL apply the same
two-branch pattern using a 10-minute time threshold.

#### Scenario: startup sweep increments retry_count on restart within 10min

- **WHEN** a `streaming` row has `retry_count=0` and is older than 10 minutes
- **AND** the app restarts
- **THEN** if `retry_count < max_retries`, `retry_count` SHALL be incremented
- **AND** `status` SHALL remain `'streaming'` if budget is not exhausted
