# Tasks: lift-patient-memory

**Date:** 2026-06-13

Tasks are ordered by dependency. C1 (schema + service) must precede C2, C3, C4.
C3 depends on C1b. C4 depends on C1b. C2 depends on C1b.
Within each group, tasks are independent.

---

## C1a -- Add `workspace_patient_profile` table to schema.sql

- [x] In `backend/schema.sql`, after the `workspace_memory` index line (line ~303),
      insert the following block exactly:
      ```sql
      CREATE TABLE IF NOT EXISTS workspace_patient_profile (
          workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
          profile JSONB NOT NULL DEFAULT '{}',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );

      -- Backfill profile rows for workspaces created before this migration.
      INSERT INTO workspace_patient_profile (workspace_id, profile)
      SELECT id, '{}'::jsonb FROM workspaces
      ON CONFLICT (workspace_id) DO NOTHING;
      ```
- [x] Add the two global_settings seeds after the existing settings seed block
      (after line ~647):
      ```sql
      INSERT INTO global_settings (key, value) VALUES
          ('memory_conflict_resolution_enabled', 'false'),
          ('memory_injection_token_budget', '1500')
      ON CONFLICT (key) DO NOTHING;
      ```
- [ ] Verify idempotency: connect to the running DB and run the CREATE TABLE and
      INSERT blocks a second time; confirm no errors.
      ```
      docker exec hlh_db psql -U hlh -d hlh -c "
        CREATE TABLE IF NOT EXISTS workspace_patient_profile (
          workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
          profile JSONB NOT NULL DEFAULT '{}',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );"
      ```
      Expected: `CREATE TABLE` or `NOTICE: relation ... already exists`.
      NOTE: Requires running stack. Listed as REMAINING LIVE VERIFICATION.

---

## C1b -- Create `backend/services/patient_profile.py`

- [x] Create `backend/services/patient_profile.py` with the following public API:
      - `EMPTY_PROFILE: dict` -- the canonical empty profile shape (all fields null/empty
        as documented in design.md).
      - `async def get_profile(conn, workspace_id) -> dict` -- fetches by PK, returns
        `EMPTY_PROFILE.copy()` if absent. Profile stored as JSONB; use
        `json.loads(row["profile"])` after asyncpg returns a string or dict.
      - `async def upsert_profile(conn, workspace_id, profile: dict) -> None` -- upserts
        via `INSERT ... ON CONFLICT (workspace_id) DO UPDATE`. Pass
        `json.dumps(profile)` as the value with `::jsonb` cast.
      - `async def apply_fact_updates(conn, workspace_id, new_facts: list, facts_to_remove: list) -> None`
        -- calls `get_profile`, mutates `profile["facts"]` (remove by ID, append new),
        sets `updated_at` on each new fact, calls `upsert_profile`.
      - `async def resolve_conflicts(profile, new_facts, provider, model) -> tuple[list, list]`
        -- LLM call per specs/conflict-resolution-prompt.md. Returns
        `(facts_to_add, ids_to_remove)`. Falls back to `(new_facts, [])` on any error.
      - `def format_profile_for_injection(profile: dict, token_budget: int = 1500) -> str`
        -- renders structured fields first, then facts sorted by confidence desc,
        char/4 token estimator, hard-truncates at budget. Returns `""` for empty profile.
- [x] Run `python3 -m py_compile backend/services/patient_profile.py`.
      Expected: no output (success). -- VERIFIED OK

---

## C1c -- Wire profile injection into `_assembled_system_prompt`

- [x] In `backend/routers/chats.py`, function `_assembled_system_prompt` (line ~112),
      after the `workspace_memory` try/except block (lines ~156-166), insert a new
      try/except block that:
      1. Imports `get_profile` and `format_profile_for_injection` from
         `services.patient_profile` inside the block.
      2. Fetches the token budget from `global_settings` (key
         `'memory_injection_token_budget'`), defaulting to 1500 if absent.
      3. Calls `get_profile(conn, workspace_id)` and
         `format_profile_for_injection(profile, budget)`.
      4. If result is non-empty, appends `f"### Patient Profile\n{_profile_text}"`
         to `parts`.
      5. On any exception, logs warning and continues (does not re-raise).
      Guard the entire block with `if workspace_id is not None:` (already in scope).
      V4 note: injected before the retrieve_memory_facts RAG block (~line 168),
      so the structured profile always lands before similarity-gated content.
- [x] Run `python3 -m py_compile backend/routers/chats.py`.
      Expected: no output. -- VERIFIED OK

---

## C1d -- Add profile CRUD endpoints to `routers/workspaces.py`

- [x] In `backend/routers/workspaces.py`, add two route handlers:
      - `GET /{workspace_id}/patient-profile`: fetch conn from pool, call
        `get_profile(conn, workspace_id)`, return
        `{"workspace_id": str(workspace_id), "profile": profile, "updated_at": ...}`.
        Return 404 if the workspace row does not exist (check workspaces table first).
        Auth: require valid session via `deps.get_current_user`.
      - `PUT /{workspace_id}/patient-profile`: accept body `{"profile": dict}`,
        call `upsert_profile(conn, workspace_id, body.profile)`, return
        `{"workspace_id": str(workspace_id), "updated_at": "..."}`.
        Auth: require valid session.
      Both endpoints follow the existing pattern in `routers/workspaces.py`
      (router prefix, pool dependency, auth dependency).
- [x] Run `python3 -m py_compile backend/routers/workspaces.py`.
      Expected: no output. -- VERIFIED OK

---

## C3a -- Add debounce/dedup to `memory_hooks.py`

- [x] In `backend/services/memory_hooks.py`:
      1. Add `import asyncio`, `import re`, `import json` and `from uuid import uuid4`
         if not already present.
      2. Add a module-level dict `_pending_extraction: dict[str, asyncio.Task] = {}`.
      3. Add pure-Python functions `_detect_correction(text: str) -> bool` and
         `_detect_reinforcement(text: str) -> bool` per design.md C3 regex patterns.
      4. Add async function `schedule_extraction(workspace_id, user_message_text,
         assistant_text, provider, model, pool, *, debounce_seconds=10.0, signal_type: str | None = None)` that:
         a. Returns immediately if `workspace_id` is falsy (workspace-less chat).
         b. Cancels any existing non-done task in `_pending_extraction[workspace_id]`.
         c. Creates a new asyncio.Task that sleeps `debounce_seconds` then calls
            `run_background_extraction(...)`.
         d. Stores the task in `_pending_extraction[workspace_id]`.
         e. Registers a done_callback that pops the key ONLY if the stored task
            is the same object (identity check, not equality):
            `if _pending_extraction.get(workspace_id) is t: _pending_extraction.pop(workspace_id, None)`.
            This prevents the cancelled-old-task callback from popping the
            replacement task (see design.md C3 -- identity check rationale).
         NOTE (V2 fix applied): `signal_type: str | None = None` added to
         `schedule_extraction` keyword-only params and threaded through `_delayed()`
         into `run_background_extraction`. Without this, the call in C3b would
         raise TypeError at runtime.
      5. `run_background_extraction` gains optional keyword args
         `workspace_id: str | None = None`, `pool: Any | None = None`,
         `signal_type: str | None = None`.
         When `workspace_id` and `pool` are provided and `extract_from_exchange`
         returns at least one fact, acquire a connection via
         `async with pool.acquire() as conn:` and call
         `apply_fact_updates` (with optional conflict-resolution pass) as shown in
         design.md C3b pseudocode. `extract_from_exchange` itself is NOT changed.
         IMPORTANT: do NOT remove the existing `eng.manage()` SQLite write in
         `memory_extraction.py` -- this is the dual-write design (V6 note).
- [x] Run `python3 -m py_compile backend/services/memory_hooks.py`.
      Expected: no output. -- VERIFIED OK

---

## C3b -- Wire `schedule_extraction` into `inference_job.py`

Note: `memory_extraction.py` is NOT changed in this task.
The profile write lives in `run_background_extraction` (memory_hooks.py), not
in `extract_from_exchange` (memory_extraction.py). See design.md C3b.

- [x] In `backend/services/inference_job.py`, in the background extraction block
      (lines ~478-498):
      1. Replace the deferred import `from services.memory_hooks import run_background_extraction`
         and the bare `asyncio.create_task(run_background_extraction(...))` call
         with a deferred import and call to `schedule_extraction`.
      2. Detect signal type before calling `schedule_extraction`:
         ```python
         from services.memory_hooks import schedule_extraction, _detect_correction, _detect_reinforcement
         _ws_id = str(chat_record.get("workspace_id") or "")
         _signal = None
         if _detect_correction(user_message_text):
             _signal = "correction"
         elif _detect_reinforcement(user_message_text):
             _signal = "reinforcement"
         asyncio.create_task(
             schedule_extraction(
                 workspace_id=_ws_id,
                 user_message_text=user_message_text,
                 assistant_text=assistant_text,
                 provider=provider,
                 model=effective_model,
                 pool=pool,
                 signal_type=_signal,
             ),
             name=f"mem_schedule_{_ws_id or 'none'}",
         )
         ```
      3. Do NOT add this task to `_background_tasks` -- `schedule_extraction` is
         nearly instant (it cancels+creates a sleeping task; no long work). The
         sleeping inner task is held by `_pending_extraction`.
      4. Keep the `_background_tasks` set and pattern unchanged for other tasks.
      Note: `_ws_id = ""` (falsy) for workspace-less chats; `schedule_extraction`
      returns immediately in that case (safe -- no error).
- [x] Run `python3 -m py_compile backend/services/inference_job.py`.
      Expected: no output. -- VERIFIED OK

---

## C2 -- Implement full `resolve_conflicts` body in `patient_profile.py`

Note: C1b creates the stub signature; this task implements the full behavior.

- [x] Implement `resolve_conflicts` in `backend/services/patient_profile.py`:
      - System prompt: `_CONFLICT_RESOLUTION_PROMPT` (see specs/conflict-resolution-prompt/spec.md
        for the full prompt text, JSON schema, and example).
      - User message: `f"EXISTING FACTS:\n{json.dumps(existing_facts, indent=2)}\n\nNEW FACTS:\n{json.dumps(new_facts, indent=2)}"`.
      - POST to `{provider.base_url}/v1/chat/completions` using
        `services.provider_client.build_headers(provider)` for headers.
        Parameters: `stream: false`, `max_tokens: 512`, `temperature: 0.0`.
      - Strip markdown fences from response (same logic as `_parse_extraction_response`
        in `memory_extraction.py` -- import or inline).
      - Parse JSON. Extract `factsToRemove` (list of str IDs) and `newFacts` (list of dicts).
      - Validate: discard any ID in `factsToRemove` not found in the existing profile
        facts (prevents phantom deletes from hallucinated IDs).
      - On any exception (httpx error, JSONDecodeError, KeyError): log warning, return
        `(new_facts, [])`.
- [x] The conflict-flag check and `apply_fact_updates` call live in
      `run_background_extraction` (per design.md C3b pseudocode), not here.
      C2 only adds the implementation of `resolve_conflicts` itself.
- [x] Run `python3 -m py_compile backend/services/patient_profile.py`.
      Expected: no output. -- VERIFIED OK

---

## C4 -- Token-budgeted formatter (implement and verify)

- [x] Confirm `format_profile_for_injection` in `patient_profile.py` implements:
      - Renders structured fields (name, date_of_birth, blood_type,
        active_diagnoses, current_medications, allergies, lab_baselines) as
        labeled lines, skipping null/empty fields.
      - Renders facts sorted by `confidence` DESC, then `created_at` DESC.
      - Accumulates `len(rendered_line) // 4` tokens per line.
      - Stops adding content when accumulated tokens would exceed `token_budget`.
      - Returns `""` when the profile dict is `{}` or contains only null/empty fields.
- [x] Write a quick inline Python smoke test (no test runner needed).
      Run from the `backend/` directory (not the project root) so the
      `services.*` import path resolves correctly:
      ```
      cd backend && python3 -c "
      from services.patient_profile import format_profile_for_injection, EMPTY_PROFILE
      assert format_profile_for_injection({}) == ''
      assert format_profile_for_injection(EMPTY_PROFILE) == ''
      p = {'active_diagnoses': ['Type 2 diabetes'], 'facts': []}
      result = format_profile_for_injection(p, token_budget=1500)
      assert 'Type 2 diabetes' in result
      print('C4 smoke: PASS')
      "
      ```
      Expected output: `C4 smoke: PASS`. -- VERIFIED OK

---

## Cross-cutting verification

- [x] `python3 -m py_compile $(find backend -name '*.py')` -- no errors. VERIFIED OK
- [ ] `cd frontend && npm run build` -- no errors (frontend not changed; confirm
      import of new endpoints has no effect on build). REMAINING LIVE VERIFICATION.
- [ ] `docker compose up --build -d` -- stack starts cleanly.
      Verify with `docker logs hlh_api | grep -E "ERROR|CRITICAL"` -- no errors.
      REMAINING LIVE VERIFICATION.
- [ ] Run `backend/scripts/verify_patient_memory.sh` with the stack running.
      Script exercises S1-S3 and S7 from specs/requirements.md scenarios.
      Expected: PASS printed, exit 0. REMAINING LIVE VERIFICATION.
- [ ] Check cascade delete: create a workspace, confirm patient-profile row exists
      via API, delete workspace, confirm `GET /api/workspaces/{id}/patient-profile`
      returns 404. REMAINING LIVE VERIFICATION (covered by verify script).
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for C1-C4. DONE.

---

## Write `backend/scripts/verify_patient_memory.sh`

- [x] Create `backend/scripts/verify_patient_memory.sh` (executable, `set -euo pipefail`).
      Script must:
      1. Accept `BASE_URL` env var, default `http://localhost:9600`.
      2. Login via `POST /api/auth/login` with env vars `HLH_TEST_USER` / `HLH_TEST_PASS`
         (defaults: `admin` / `admin`); capture session cookie.
      3. Create a workspace via `POST /api/workspaces`; capture `workspace_id`.
      4. Assert `GET /api/workspaces/{workspace_id}/patient-profile` returns HTTP 200
         and `profile` field is `{}` or empty object.
      5. `PUT /api/workspaces/{workspace_id}/patient-profile` with
         `{"profile": {"active_diagnoses": ["test-diagnosis-abc"]}}`.
      6. Assert GET returns `active_diagnoses` containing `"test-diagnosis-abc"`.
      7. Delete workspace via `DELETE /api/workspaces/{workspace_id}`.
      8. Assert `GET /api/workspaces/{workspace_id}/patient-profile` returns 404.
      9. Print `PASS: <count>` and `FAIL: <count>`. Exit non-zero if any FAIL.
      Note: per CLAUDE.md, assertions go via API JSON, not psql -c -v substitution.
      Note: per CLAUDE.md, use `PASS=$((PASS+1))` not `((PASS++))` with `set -e`.
      V5 note: live extraction test (steps 6-7 in design.md) requires a running
      stack with memory_auto_extract_enabled=true and a configured provider.
      Listed as REMAINING LIVE VERIFICATION.
- [x] `chmod +x backend/scripts/verify_patient_memory.sh`. DONE.
- [ ] Run the script against the running stack; confirm exit 0 and `FAIL: 0`.
      REMAINING LIVE VERIFICATION.
