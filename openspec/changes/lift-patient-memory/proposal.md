# Proposal: lift-patient-memory

**Date:** 2026-06-13
**Status:** proposed

## Why

Health conversations contain durable facts: medications, diagnoses, allergies, lab
baselines. Today those facts are extracted into a SQLite CoreTier (per C.md item 1)
using `hashlib.md5(content)` as the primary key. Two facts that are contradictory
but textually different -- "Patient takes metformin 500mg" vs "Patient takes
metformin 1000mg" -- generate distinct MD5 hashes and live as separate active
entries indefinitely. There is no resolution, no structure, and no confidence
ordering. The system prompt assembler (`_assembled_system_prompt` in
`routers/chats.py`) injects `workspace_memory` rows as a flat bullet list with no
token budget and no priority ordering.

The validation report (validation/C.md) confirms the gap and resolves the blocking
unknown: the existing `workspace_memory` table (a multi-row TEXT store) and
`memory_entries` table (flat TEXT + pgvector) cannot hold a structured patient
profile. A new table is required.

## What

Introduce a workspace-scoped structured patient profile in PostgreSQL as a single
JSONB document per workspace. Wire the extraction pipeline to upsert that document
in place rather than accumulate duplicate SQLite facts. Inject the profile into the
system prompt unconditionally (no similarity gate), ranked by confidence, inside a
token budget.

Scope covers four work items from C.md:

- **C1**: New `workspace_patient_profile` table + system-prompt injection.
- **C2**: LLM conflict-resolution pass (gate behind `memory_conflict_resolution_enabled`).
- **C3**: asyncio debounce/dedup of background extraction + correction/reinforcement signal detection.
- **C4**: Token-budgeted ranked memory-injection formatter.

## Scope

| ID  | Files touched                                                                               | Type              |
|-----|---------------------------------------------------------------------------------------------|-------------------|
| C1a | `backend/schema.sql`                                                                        | Schema add        |
| C1b | `backend/services/patient_profile.py` (new)                                                 | New service       |
| C1c | `backend/routers/chats.py` (`_assembled_system_prompt`)                                     | Injection wiring  |
| C1d | `backend/routers/chats.py` or `backend/routers/memory.py` (profile CRUD endpoints)         | New endpoints     |
| C2  | `backend/services/patient_profile.py` (conflict resolver in same module)                   | New function      |
| C2s | `backend/schema.sql` (global_settings seed for `memory_conflict_resolution_enabled`)       | Settings seed     |
| C3a | `backend/services/memory_hooks.py` (`run_background_extraction` + new debounce dict)        | Refactor          |
| C3b | `backend/services/memory_extraction.py` (`extract_from_exchange`, saves to profile)        | Refactor          |
| C4  | `backend/services/patient_profile.py` (`format_profile_for_injection`)                     | New function      |
| C4s | `backend/schema.sql` (global_settings seed for `memory_injection_token_budget`)            | Settings seed     |
| Vfy | `backend/scripts/verify_patient_memory.sh` (new)                                           | Verify script     |

## Out of scope

- No changes to the SQLite CoreTier or `MemoryEngine` class hierarchy -- those remain
  as-is. The new profile is additive; consolidation of all three stores is future work.
- No DeepDream overnight consolidation (item 5 from C.md): requires resolving the
  `DailyTier` filesystem-vs-DB question under `read_only: true` containers first.
- No episodic clinical reasoning schema (item 6): deferred to Phase C2.
- No frontend UI for editing the profile: read via API is sufficient for v1.
- No pgvector index on the JSONB column: profile is always fetched by primary key.
- No changes to `routers/memory.py` `memory_entries` path: that path is unchanged.

## Risk

Medium overall. The schema change is idempotent (`CREATE TABLE IF NOT EXISTS`).
The extraction path change routes newly extracted facts into the Postgres profile;
the old CoreTier continues to function for any code that calls `MemoryEngine`
directly. The debounce dict is module-level in `inference_job.py` -- failure to
cancel a pending task is non-fatal (both tasks complete, second upsert is idempotent).
Conflict-resolution LLM call is gated behind a flag, defaulting to disabled, to
protect bundled 4b model users from latency spikes.

## Follow-up (not this change)

- Unify SQLite CoreTier with the Postgres profile (migrate extraction writes entirely).
- DeepDream LLM consolidation (blocked on DailyTier file-vs-DB resolution).
- Episodic clinical episode schema in a `workspace_clinical_episodes` append-only table.
- Frontend profile editor (Settings tab or dedicated panel).
