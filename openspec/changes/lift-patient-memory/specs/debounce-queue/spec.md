## MODIFIED Requirements

### Requirement: Background extraction is debounced per workspace

`backend/services/memory_hooks.py` SHALL maintain a module-level dict
`_pending_extraction: dict[str, asyncio.Task]` keyed by workspace_id string.
A new function `schedule_extraction(workspace_id, user_message_text, assistant_text,
provider, model, *, debounce_seconds=10.0)` SHALL:
1. Cancel any existing non-done task in `_pending_extraction[workspace_id]`.
2. Create a new asyncio.Task that sleeps `debounce_seconds` then calls
   `run_background_extraction`.
3. Store the task in `_pending_extraction[workspace_id]`.
4. Register a done_callback that removes the workspace_id key from the dict.
At most one pending extraction task per workspace SHALL exist at any time.
Task cancellation failure (task already done) SHALL be handled silently.
**Reason**: C.md item 3 -- current code creates one asyncio.Task per message with
no dedup. Rapid exchanges accumulate overlapping extraction tasks.
**Evidence**: `backend/services/inference_job.py:486` -- bare `asyncio.create_task`
keyed by `assistant_id` (not workspace_id); no cancellation of prior tasks.
`backend/services/memory/queue.py` -- `threading.Timer` pattern is unsafe in asyncio.

#### Scenario: Rapid exchanges produce only one extraction run
- **WHEN** two messages are sent to the same workspace within 5 seconds
  (less than `debounce_seconds`)
- **THEN** `docker logs hlh_api` shows only one `mem_extract_{workspace_id}` task
  completing (the second scheduled task; the first is cancelled)

#### Scenario: Extraction task cancellation does not raise
- **WHEN** a new message arrives for a workspace that already has a pending extraction
  task that is already done
- **THEN** no exception is raised and a new task is scheduled normally

### Requirement: inference_job.py uses schedule_extraction

`backend/services/inference_job.py` SHALL replace the bare `asyncio.create_task(run_background_extraction(...))`
call (line ~486) with a call to `schedule_extraction` imported from
`services.memory_hooks`, passing `workspace_id=str(chat_record.get("workspace_id") or "")`
and `pool=pool`.
The `_background_tasks` set SHALL no longer hold the extraction task (the debounce
dict owns its lifetime).
`run_background_extraction` SHALL accept optional keyword args `workspace_id: str | None = None`
and `pool: object | None = None`; when provided, it acquires a DB connection and
calls `apply_fact_updates` after extraction.
**Reason**: Centralise debounce ownership; pass workspace_id for Postgres profile write.
**Evidence**: `backend/services/inference_job.py:1367` -- `chat_record["workspace_id"]`
is available. `backend/services/inference_job.py:486` -- current extraction task held
in `_background_tasks`, no workspace-level dedup.

#### Scenario: workspace_id flows from inference_job to extraction
- **WHEN** a message is sent in a workspace
- **THEN** `schedule_extraction` receives a non-empty `workspace_id` matching the
  workspace UUID

#### Scenario: extraction failure does not crash inference job
- **WHEN** `schedule_extraction` raises an exception
- **THEN** the exception is caught by the try/except in inference_job.py line ~478
  and logged as a warning, not re-raised

### Requirement: Correction and reinforcement signals are detected before extraction

Before scheduling extraction, `run_background_extraction` SHALL call pure-Python
regex functions `_detect_correction(text)` and `_detect_reinforcement(text)` on
the last user message.
The detected signal type (`"correction"`, `"reinforcement"`, or `None`) SHALL be
passed as metadata to `extract_from_exchange`.
No external dependencies SHALL be introduced for signal detection.
**Reason**: C.md item 7 -- correction signals should influence extraction priority
and confidence weighting.
**Evidence**: `backend/services/memory_hooks.py:83-113` -- `run_background_extraction`
has no correction/reinforcement detection. All exchanges treated identically.

#### Scenario: Correction signal detected from user message
- **WHEN** the user message contains "no, that's wrong, I take 1000mg not 500mg"
- **THEN** `_detect_correction` returns `True`
- **AND** the extraction call receives `signal_type="correction"` in metadata

#### Scenario: No signal returns None metadata
- **WHEN** the user message is a routine question with no correction/reinforcement language
- **THEN** `_detect_correction` and `_detect_reinforcement` both return `False`
- **AND** the extraction call receives `signal_type=None` in metadata
