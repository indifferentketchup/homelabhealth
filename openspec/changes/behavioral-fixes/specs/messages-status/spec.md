# Delta spec: messages-status (A1 + A6)

**Date:** 2026-06-12

## ADDED Requirements

### Requirement: Messages status column SHALL support approval_pending value

The `messages.status` column SHALL accept the value `approval_pending` in addition to `streaming`, `complete`, `failed`, and `cancelled`. The CHECK constraint `messages_status_check` SHALL enforce `status IN ('streaming', 'complete', 'failed', 'cancelled', 'approval_pending')`.

The constraint SHALL be applied via the idempotent pattern:

```sql
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_status_check;
ALTER TABLE messages ADD CONSTRAINT messages_status_check
  CHECK (status IN ('streaming', 'complete', 'failed', 'cancelled', 'approval_pending'));
```

The `DEFAULT 'complete'` ensures user messages inserted without an explicit status land in `complete`.

#### Scenario: Fresh database gets approval_pending in CHECK constraint

- **WHEN** `schema.sql` is applied to a fresh database
- **THEN** `messages_status_check` SHALL accept `approval_pending` as a valid value

#### Scenario: Existing database gets constraint replaced idempotently

- **WHEN** `schema.sql` is applied to a database that already has `messages_status_check`
- **THEN** the old constraint SHALL be dropped and the new one added without error
- **AND** existing rows with values in `('streaming', 'complete', 'failed', 'cancelled')` SHALL remain valid

### Requirement: Approval gate SHALL insert a row before returning 202

When `should_request_approval()` returns `True`, the backend SHALL INSERT an assistant message row with `status = 'approval_pending'` and empty content before returning HTTP 202. The response body SHALL include `assistant_message_id` referencing the inserted row.

#### Scenario: Approval gate returns 202 with existing assistant row

- **WHEN** a message triggers the approval gate and durable streaming is enabled
- **THEN** the backend SHALL INSERT a row into `messages` with `role = 'assistant'`, `status = 'approval_pending'`, and empty content
- **AND** the HTTP 202 response SHALL include `assistant_message_id` matching the inserted row
- **AND** `GET /api/chats/{id}/messages` SHALL return a row with that ID and `status = 'approval_pending'`

#### Scenario: Second POST blocked while approval is pending

- **WHEN** a chat has a row with `status IN ('streaming', 'approval_pending')`
- **AND** a second `POST /api/chats/{id}/messages` arrives
- **THEN** the backend SHALL return HTTP 409

### Requirement: 409 guard SHALL check both streaming and approval_pending

The 409 guard query SHALL check for `status IN ('streaming', 'approval_pending')`, not only `status = 'streaming'`. A new partial index `messages_chat_status_pending_idx` SHALL cover both statuses.

```sql
CREATE INDEX IF NOT EXISTS messages_chat_status_pending_idx
  ON messages (chat_id, status)
  WHERE status IN ('streaming', 'approval_pending');
```

#### Scenario: Guard blocks new inference while approval is pending

- **WHEN** a chat has a row with `status = 'approval_pending'`
- **AND** a second `POST /api/chats/{id}/messages` arrives
- **THEN** the 409 guard SHALL detect the existing row and return HTTP 409

#### Scenario: Guard blocks new inference while streaming

- **WHEN** a chat has a row with `status = 'streaming'`
- **AND** a second `POST /api/chats/{id}/messages` arrives
- **THEN** the 409 guard SHALL detect the existing row and return HTTP 409

### Requirement: Frontend SHALL handle approval_pending status in sendMessage

`useDurableChat.sendMessage` SHALL branch on `res?.status === 'approval_pending'` to set `streamingMessageId`, `setStreamingStatus('approval_pending')`, call `setBusy(true)`, and begin polling. This branch SHALL appear before the `setBusy(false)` fallthrough.

#### Scenario: UI shows pending state after approval gate triggers

- **WHEN** `sendMessage` receives a response with `status = 'approval_pending'`
- **THEN** the UI SHALL set `busy = true` and start polling for status changes
- **AND** the UI SHALL NOT fall through to `setBusy(false)`

### Requirement: Startup sweep SHALL clear stale streaming rows

On process startup, the lifespan function SHALL update any `messages` rows with `status = 'streaming'` and a `started_at` (or `created_at` fallback) older than 10 minutes to `status = 'failed'` with `error_message = 'process restart: inference interrupted'`. This sweep SHALL run after `apply_schema()`.

#### Scenario: Stale streaming rows from prior process are swept on startup

- **WHEN** the process starts
- **AND** `messages` contains rows with `status = 'streaming'` where `COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'`
- **THEN** those rows SHALL be updated to `status = 'failed'`
- **AND** `error_message` SHALL be `'process restart: inference interrupted'`
- **AND** the count of swept rows SHALL be logged

#### Scenario: Recent streaming rows are not swept on startup

- **WHEN** the process starts
- **AND** `messages` contains a row with `status = 'streaming'` and `started_at` less than 10 minutes ago
- **THEN** that row SHALL NOT be updated

### Requirement: State machine transitions SHALL be forward-only

Status transitions on assistant messages SHALL be forward only. No status may regress to a prior state. The sweeper in `main.py` and the startup sweep enforce this by only moving rows forward (to `failed`).

#### Scenario: Streaming transitions to complete

- **WHEN** inference finishes successfully
- **THEN** the assistant message status SHALL change from `streaming` to `complete`

#### Scenario: Streaming transitions to failed on error

- **WHEN** inference encounters an error or 3 consecutive flush failures
- **THEN** the assistant message status SHALL change from `streaming` to `failed`

#### Scenario: Streaming transitions to cancelled on user stop

- **WHEN** the user stops inference via `DELETE /api/chats/{id}/messages/{id}/stop`
- **THEN** the assistant message status SHALL change from `streaming` to `cancelled`

#### Scenario: Approval pending transitions to streaming on approval

- **WHEN** approval is granted for a pending message
- **THEN** the assistant message status SHALL change from `approval_pending` to `streaming`

#### Scenario: Approval pending transitions to cancelled on rejection

- **WHEN** approval is rejected for a pending message
- **THEN** the assistant message status SHALL change from `approval_pending` to `cancelled`

### Requirement: Polling SHALL handle each status appropriately

`useDurableChat.pollOnce` SHALL handle each status value with the correct frontend action:

| Status | Action |
|---|---|
| `streaming` | Update `streamingContent`, continue polling |
| `approval_pending` | Hold `busy=true`, continue polling |
| `complete` | Clear streaming state, invalidate query cache, stop polling |
| `failed` | Clear streaming state, set `sendError`, stop polling |
| `cancelled` | Clear streaming state, stop polling |

#### Scenario: Polling continues while approval is pending

- **WHEN** polling checks a message with `status = 'approval_pending'`
- **THEN** the UI SHALL keep `busy = true` and continue polling

#### Scenario: Polling stops when status becomes complete

- **WHEN** polling checks a message with `status = 'complete'`
- **THEN** the UI SHALL clear streaming state and stop polling
