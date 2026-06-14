## MODIFIED Requirements

### Requirement: run_background_extraction writes extracted facts to workspace_patient_profile

`backend/services/memory_hooks.py:run_background_extraction` SHALL accept optional
keyword-only parameters `workspace_id: str | None = None`, `pool: object | None = None`,
and `signal_type: str | None = None`.
When both `workspace_id` and `pool` are provided AND `extract_from_exchange` returns
at least one fact, the function SHALL acquire a DB connection via
`async with pool.acquire() as conn:` and call `apply_fact_updates` from
`services.patient_profile` to upsert those facts into `workspace_patient_profile`.
The existing SQLite CoreTier write via `eng.manage()` inside `extract_from_exchange`
SHALL remain (dual-write, not migration).
`extract_from_exchange` in `backend/services/memory_extraction.py` is NOT changed
(no new parameters, no Postgres writes). It stays side-effect-free relative to
Postgres; all DB-pool work is owned by `run_background_extraction`.
When `workspace_id` or `pool` is `None`, the Postgres profile write SHALL be
silently skipped.
**Reason**: C.md item 2 -- extracted facts must populate the structured Postgres
profile. The MD5-keyed SQLite CoreTier cannot resolve contradictions. Keeping
`extract_from_exchange` side-effect-free (no conn/workspace_id params) preserves
its testability and avoids threading a DB connection into a function that already
owns an LLM round-trip.
**Evidence**: `backend/services/memory_extraction.py:130-146` -- only calls
`eng.manage(action="create")` which writes to SQLite CoreTier. No Postgres write.
`backend/services/memory_hooks.py:83-113` -- `run_background_extraction` calls
`extract_from_exchange` and returns facts; the Postgres write belongs here.

#### Scenario: Extraction with workspace_id populates profile facts
- **WHEN** `memory_auto_extract_enabled = 'true'` and a user sends the message
  "I take metformin 500mg daily"
- **THEN** within 15 seconds, `GET /api/workspaces/{workspace_id}/patient-profile`
  returns a profile with at least one entry in `profile.facts`

#### Scenario: Extraction without workspace_id skips profile write
- **WHEN** `run_background_extraction` is called without `workspace_id`
- **THEN** no write to `workspace_patient_profile` occurs and no exception is raised

#### Scenario: CoreTier write still occurs alongside profile write
- **WHEN** extraction runs with `workspace_id` provided
- **THEN** `eng.manage(action="create")` is still called for each extracted fact
  inside `extract_from_exchange` (SQLite CoreTier receives the write as before).
  Do NOT remove the `eng.manage()` call from `memory_extraction.py`; this is the
  dual-write design and removing it would break the CoreTier path.

### Requirement: Conflict resolution pass gated by global_settings flag

The extraction pipeline SHALL call `resolve_conflicts` (an LLM pass) before
applying new facts to the profile when
`global_settings.memory_conflict_resolution_enabled = 'true'`.
When the flag is `'false'` (default), new facts SHALL be appended without a
conflict-resolution LLM call.
`resolve_conflicts` SHALL use the same provider as the active inference provider
(`resolve_provider_for_workspace` from `services/provider_client.py`).
On any LLM call failure or JSON parse error, `resolve_conflicts` SHALL fall back to
`(new_facts, [])` (append-only) and log a warning.
**Reason**: C.md item 1 / blocking unknown #2 -- MD5 duplicate problem. Two facts
with different text for the same attribute accumulate indefinitely. Patient-safety
impact (conflicting medication doses). Must be gated: expensive on 4b bundled model.
**Evidence**: `backend/services/memory/core_tier.py:432` -- `hashlib.md5(content.encode()).hexdigest()`
as PK; two facts with different text get distinct IDs and both survive.

#### Scenario: Conflict resolution off by default
- **WHEN** `memory_conflict_resolution_enabled = 'false'` (default)
- **THEN** no conflict-resolution LLM call is made during extraction
- **AND** new facts are appended to `profile.facts` without removing any existing facts

#### Scenario: Conflict resolution supersedes contradictory medication dose
- **WHEN** `memory_conflict_resolution_enabled = 'true'`
- **AND** the profile contains fact `"Patient takes metformin 500mg daily"`
- **AND** extraction yields `"Patient takes metformin 1000mg daily"`
- **THEN** after extraction completes, `GET /api/workspaces/{id}/patient-profile`
  returns a profile where the 500mg fact is absent and the 1000mg fact is present

#### Scenario: Conflict resolution LLM failure falls back to append-only
- **WHEN** `memory_conflict_resolution_enabled = 'true'`
- **AND** the LLM call for conflict resolution fails (timeout, parse error, etc.)
- **THEN** a warning is logged and new facts are appended without removing any
  existing facts (no exception propagates to the inference path)

### Requirement: apply_fact_updates and resolve_conflicts are in patient_profile module

`backend/services/patient_profile.py` SHALL export:
- `async def apply_fact_updates(conn, workspace_id, new_facts, facts_to_remove) -> None`
  that fetches the current profile, merges new_facts into `profile["facts"]`,
  removes facts by ID from `facts_to_remove`, and upserts via `upsert_profile`.
- `async def resolve_conflicts(profile, new_facts, provider, model) -> tuple[list, list]`
  that returns `(facts_to_add, ids_to_remove)`. Falls back to `(new_facts, [])` on error.
All JSONB writes SHALL pass profile as `json.dumps(profile)` with `::jsonb` cast.
**Reason**: Single-responsibility; all profile mutation logic in one module.
**Evidence**: design.md C1b section.

#### Scenario: apply_fact_updates removes fact by ID
- **WHEN** `apply_fact_updates` is called with `facts_to_remove=["<existing-id>"]`
- **THEN** the fact with that ID is absent from `profile["facts"]` after the call

#### Scenario: JSONB write uses json.dumps convention
- **WHEN** `upsert_profile` is called
- **THEN** the SQL parameter is a JSON string (not a raw dict), cast with `::jsonb`
