# Delta spec: eval-background-task

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: messages table SHALL have a groundedness_score FLOAT column

`backend/schema.sql` SHALL include an idempotent migration at the end of the
migration block:

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS groundedness_score FLOAT;

INSERT INTO global_settings (key, value) VALUES
    ('groundedness_eval_enabled',     'false'),
    ('groundedness_eval_sample_rate', '1.0')
ON CONFLICT (key) DO NOTHING;
```

The column SHALL be nullable. Existing rows SHALL not be affected (no DEFAULT
that triggers a table rewrite). The `global_settings` keys SHALL use `ON CONFLICT
DO NOTHING` so existing operator-configured values are preserved.

#### Scenario: Column exists after schema apply on fresh DB

- **WHEN** the schema is applied against a fresh database
- **THEN** `SELECT column_name FROM information_schema.columns WHERE table_name='messages' AND column_name='groundedness_score'`
  SHALL return one row

#### Scenario: Schema apply is idempotent on existing DB

- **WHEN** the migration block is applied twice against an existing DB
  that already has the `groundedness_score` column
- **THEN** both runs SHALL complete without error

#### Scenario: global_settings keys are seeded with defaults

- **WHEN** the schema is applied on a fresh DB
- **THEN** `SELECT value FROM global_settings WHERE key='groundedness_eval_enabled'`
  SHALL return `'false'`
- **AND** `SELECT value FROM global_settings WHERE key='groundedness_eval_sample_rate'`
  SHALL return `'1.0'`

### Requirement: _assembled_system_prompt SHALL return the raw rag_block as a third value

`_assembled_system_prompt` in `backend/routers/chats.py` SHALL be modified to
return `(assembled, sse_rag_meta, rag_block)` where `rag_block` is the raw
retrieved context string (empty string when no RAG context was retrieved).

The variable `rag_block` SHALL be initialized to `""` before the retrieval block
so it is always defined. The return type annotation SHALL be updated to
`tuple[str, dict[str, int] | None, str]`. Every call site in `chats.py` SHALL
be updated to unpack three values.

(V1/JD-001 correction: `rag_block` is currently a local variable inside
`_assembled_system_prompt` at line 243 and is NOT returned. The background task
needs the raw RAG text, not the assembled system prompt which mixes in workspace
instructions, memory facts, and custom instructions.)

#### Scenario: _assembled_system_prompt returns three values

- **WHEN** `_assembled_system_prompt` is called for a workspace with indexed sources
- **THEN** the return value SHALL unpack as `(assembled, sse_rag_meta, rag_block)`
- **AND** `rag_block` SHALL be a non-empty string containing the retrieved chunk text

#### Scenario: _assembled_system_prompt returns empty rag_block when no sources indexed

- **WHEN** `_assembled_system_prompt` is called for a workspace with no indexed sources
- **THEN** the third return value SHALL be `""`

### Requirement: chats.py SHALL fire an async groundedness eval task after all pool.acquire() blocks

`backend/routers/chats.py` SHALL add a module-level `_BG_EVAL_TASKS: set` to
hold task references and prevent GC mid-flight. This is a new pattern -- the
set+done-callback approach is not currently used in `sources.py:293` (which uses
bare `create_task`); `_BG_EVAL_TASKS` is more robust.

`_maybe_fire_groundedness_eval` SHALL be called after `summarize_and_compress`
at line 1836 and before the guard_alert SSE yield at line 1838. This is the only
point in `gen()` after all `pool.acquire()` blocks. (V5 correction: line 1733
is inside an active `pool.acquire()` block.)

`_maybe_fire_groundedness_eval` SHALL:
1. Return if `context_text` is falsy (no RAG context means no groundedness check).
2. Read `groundedness_eval_enabled` from `global_settings`; return if `'false'`.
3. Read `groundedness_eval_sample_rate`; apply `random.random() > float(rate)` skip.
4. Fire `asyncio.create_task(_run_groundedness_eval(...))` and add to `_BG_EVAL_TASKS`
   with a done-callback that removes the task from the set.
5. SHALL NOT await the task. SHALL NOT raise.

`_run_groundedness_eval` coroutine SHALL:
1. Call `resolve_judge_provider(workspace_id)` from `services.eval_judge`;
   log INFO and return if result is None.
2. Truncate inputs: `context_text[:4000]`, `assistant_text[:2000]`.
   (V6/ctx correction: larger caps for the workspace chat provider context window.)
3. Call `call_llm_as_judge(provider, model, GROUNDEDNESS_SYSTEM_PROMPT, user_prompt)`.
4. Write `groundedness_score` and violations to the messages row via a single
   `UPDATE` that merges violations into `guard_flags` JSONB using `||`.
5. Pass violations list as `json.dumps(violations_list)` (asyncpg JSONB convention).
6. Be fully wrapped in `try/except Exception` that logs WARNING on failure.

#### Scenario: Score written for grounded response when eval enabled

- **WHEN** `groundedness_eval_enabled=true` is set in global_settings
- **AND** a user sends a query with RAG context retrieved
- **THEN** within 60 seconds `messages.groundedness_score` for the assistant row
  SHALL be a float between 0.0 and 1.0

#### Scenario: Eval disabled by default produces null scores

- **WHEN** `groundedness_eval_enabled=false` (the seeded default)
- **AND** a user sends 5 messages
- **THEN** all 5 assistant rows SHALL have `groundedness_score IS NULL`

#### Scenario: Eval skipped when RAG context is empty

- **WHEN** `groundedness_eval_enabled=true`
- **AND** a user sends a message with no sources in the workspace (empty context)
- **THEN** no `groundedness eval` log line SHALL appear in `docker logs hlh_api`
  for that message

#### Scenario: Eval task soft-fails without affecting streaming response

- **WHEN** the `hlh_chat` service is unavailable during the eval task
- **AND** eval is enabled
- **THEN** the streaming response to the user SHALL complete normally
- **AND** a WARNING log line SHALL appear: `groundedness eval failed (non-fatal): ...`
- **AND** `messages.groundedness_score` SHALL remain null

#### Scenario: Violations stored in guard_flags without overwriting existing entries

- **WHEN** an assistant message has existing `guard_flags` entries from `scan_output`
- **AND** the eval task writes violations
- **THEN** the `guard_flags` JSONB SHALL contain both the original scan entries
  AND the `groundedness_violations` key

#### Scenario: Background task reference is retained to prevent GC

- **WHEN** `asyncio.create_task` is called in `_maybe_fire_groundedness_eval`
- **THEN** the task object SHALL be stored in `_BG_EVAL_TASKS` until the task
  completes (done callback removes it)

#### Scenario: Durable streaming path deferred (explicit non-requirement)

- **GIVEN** `durable_streaming_enabled=true` in global_settings
- **WHEN** a user sends a message and the durable streaming path handles it
- **THEN** no groundedness eval task fires (durable path does not reach the
  `gen()` fire point at line 1836 -- this is explicit deferred scope, not a bug)

#### Scenario: Inputs are truncated to the configured workspace-provider caps

- **WHEN** `_run_groundedness_eval` is called with `context_text` longer than 4000 chars
- **THEN** the `{context}` slot SHALL be filled with `context_text[:4000]` only
- **AND** the `{response}` slot SHALL be filled with `assistant_text[:2000]` only
