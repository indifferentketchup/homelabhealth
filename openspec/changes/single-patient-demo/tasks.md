# Tasks — Single-Patient Demo

## Status

Current state on 2026-06-12:

- Tasks 1-3 are complete from local code/doc verification.
- Task 4 is mostly complete in code, but still missing non-admin CTA hiding.
- Task 5 has not been executed against a running stack.

---

## Task 1: Clean up dead FHIR code in demo.py

**Priority:** P1
**Dependencies:** None

**What to do:**
- Remove `_fhir_bundle_to_text()` function from `backend/routers/demo.py`
- Remove `import json` from demo.py imports
- Simplify file iteration loop: remove `.json` branch, keep `.txt` only

**Files to modify:**
- `backend/routers/demo.py`

**Acceptance criteria:**
- [x] `grep -n '_fhir_bundle_to_text' backend/routers/demo.py` returns zero matches
- [x] `grep -n 'import json' backend/routers/demo.py` returns zero matches
- [x] `grep -n 'suffix == ".json"' backend/routers/demo.py` returns zero matches
- [x] `python3 -m py_compile backend/routers/demo.py` passes
- [x] File still has `import uuid`, `from typing import Any`, and all necessary imports

**Commit:** `chore: remove dead FHIR bundle parser from demo loader`

---

## Task 2: Rewrite demo data as first-person health journal entries

**Priority:** P1
**Dependencies:** None (parallel with Task 1)

**What to do:**
- Delete all 12 existing `.txt` files in `backend/demo_data/`
- Create 10 new `.txt` files with first-person journal entries
- Files named `YYYY-MM-DD Brief description.txt` for chronological sorting
- Each entry: 200-500 words, first-person voice, plain-language interpretation

**Narrative arc (Alex Taylor, DOB 1990):**
1. `2024-09-10 Post-surgery checkup.txt` — Gallbladder removal follow-up, abdominal ultrasound normal
2. `2024-09-27 Annual blood work.txt` — CBC shows anemia, glucose high, TSH normal
3. `2024-10-05 Head CT for headaches.txt` — CTA shows normal brain vessels, relief
4. `2024-11-15 Diabetes and cholesterol check.txt` — A1c improving (7.2%), cholesterol high
5. `2024-11-17 Brain MRI for headaches and swelling.txt` — White matter spots found, no tumor
6. `2024-12-12 First allergist visit.txt` — C4 and tryptase tests for swelling episodes
7. `2024-12-16 Follow-up allergy labs.txt` — C1 esterase inhibitor tests, both low
8. `2024-12-20 Putting together the puzzle.txt` — Connecting symptoms, researching hereditary angioedema
9. `2025-01-10 Starting new medication.txt` — Starting treatment plan, feeling hopeful
10. `2025-02-15 One month check-in.txt` — Reflecting on progress with new diagnosis

**Files to create:** 10 new `.txt` files in `backend/demo_data/`
**Files to delete:** 12 existing `.txt` files in `backend/demo_data/`

**Acceptance criteria:**
- [x] 10 `.txt` files exist in `backend/demo_data/`
- [x] All content is first-person ("I", "my", "me")
- [x] No clinical report formatting (no "QUEST DIAGNOSTICS", no reference range tables, no "IMPRESSION" sections)
- [x] Each file is 200-500 words
- [x] Same medical narrative preserved (Alex Taylor: diabetes, anemia, possible HAE, cholecystectomy)
- [x] `ls backend/demo_data/*.txt | wc -l` returns 10

**Commit:** `feat: rewrite demo data as first-person health journal entries`

---

## Task 3: Create openspec documentation

**Priority:** P1
**Dependencies:** None (parallel with Tasks 1-2)

**What to do:**
- Create `openspec/changes/single-patient-demo/proposal.md`
- Create `openspec/changes/single-patient-demo/design.md`
- Create `openspec/changes/single-patient-demo/tasks.md` (this file)

**Files to create:**
- `openspec/changes/single-patient-demo/proposal.md`
- `openspec/changes/single-patient-demo/design.md`
- `openspec/changes/single-patient-demo/tasks.md`

**Acceptance criteria:**
- [x] All three files exist
- [x] Follow convention per `openspec/README.md`
- [x] Slug is lowercase-hyphenated: `single-patient-demo`

**Commit:** `docs: add single-patient-demo openspec batch`

---

## Task 4: Add frontend "Try Demo" button

**Priority:** P1
**Dependencies:** Task 1 (backend cleanup) and Task 2 (demo data) should be complete before verifying end-to-end

**What to do:**
- Add `loadDemo` API wrapper to `frontend/src/api/workspaces.js`
- Add "Try Demo" button to `WorkspaceLanding` component in `frontend/src/pages/workspace/WorkspaceView.jsx`
- Button shown when workspace list is empty (as part of the empty state) AND as a secondary option below the workspace grid when workspaces exist
- Handle: loading, error, already-exists (navigate to existing), success (navigate to new)
- Hide the CTA for non-admin users

**UI specification:**
- Empty state: card with Stethoscope icon, "Try a demo" heading, "Load sample health records to see HomeLab Health in action" description, "Try Demo" button
- Non-empty state: subtle link/button below workspace grid: "New here? Try a demo workspace →"
- Loading: button shows spinner and "Loading demo data…"
- Error: inline error message below button
- Already exists: navigate to Demo workspace chat
- Success: navigate to Demo workspace chat

**Files to modify:**
- `frontend/src/api/workspaces.js` — add `loadDemo` export
- `frontend/src/pages/workspace/WorkspaceView.jsx` — add button + logic

**Acceptance criteria:**
- [x] `loadDemo` function exported from `frontend/src/api/workspaces.js`
- [x] Button visible on landing page when no workspaces exist
- [x] Button visible as secondary option when workspaces exist
- [x] Clicking button sends POST to `/api/demo/load`
- [x] On success, code navigates to `/workspace/<demo-id>`
- [x] On already-exists, code navigates to existing Demo workspace
- [x] Loading state shows spinner + text
- [x] Error state shows inline message
- [x] Button hidden for non-admin users
- [x] `npm run build` passes with no warnings

**Commit:** `feat: add Try Demo button to workspace landing page`

---

## Task 5 (B4): Fix demo loader atomicity

**Priority:** P1
**Dependencies:** Task 1 (dead code cleanup is prerequisite for a clean diff)

**What to do:**

Rewrite `load_demo` in `backend/routers/demo.py` to fix three bugs identified in architecture finding B4:

1. Wrap workspace INSERT and all source INSERTs in a single `conn.transaction()` block so a partial failure leaves no orphaned workspace.
2. Change idempotency check to detect partial/stuck state: if workspace exists but not all sources are `complete`, DELETE the workspace (CASCADE removes sources + chunks) and re-create from scratch.
3. Copy each demo file to `/data/uploads/{source_id}.txt` before the sources INSERT and populate `file_url` with that path.
4. Collect all `asyncio.create_task(...)` return values into a list to prevent GC-before-schedule. Fire tasks only after the transaction has committed.

See `design.md` section "Amendment: Demo Loader Atomicity (B4)" for pseudocode and the full idempotency state table.

**Files to modify:**
- `backend/routers/demo.py`

**Acceptance criteria:**
- [x] Workspace INSERT and all source INSERTs execute inside one `conn.transaction()` -- verified by reading the code
- [x] Idempotency check uses `bool_and(embedding_status = 'complete')` to distinguish clean vs. partial state
- [x] Partial state triggers DELETE + re-create (not early return)
- [x] Each source INSERT includes `file_url = '/data/uploads/{source_id}.txt'` -- `grep -n 'file_url' backend/routers/demo.py` returns a match inside the INSERT
- [x] `asyncio.create_task` calls are collected into a list (not fire-and-forget)
- [x] Ingest tasks are fired AFTER `conn.transaction()` context exits
- [x] `python3 -m py_compile backend/routers/demo.py` passes

**Commit:** `fix: demo loader atomicity -- transaction, idempotency, file_url, task refs`

---

## Task 6 (B4): Smoke-test atomicity fix against running stack

**Priority:** P2
**Dependencies:** Task 5 (B4) complete, Tasks 1-4 complete

**What to do:**
- Rebuild: `docker compose build --no-cache hlh_api`
- Confirm `/data/uploads` is writable by uid 1000 inside the container: `docker exec hlh_api python3 -c "import pathlib; pathlib.Path('/data/uploads/probe.txt').write_text('ok'); print('writable')"`
- POST `/api/demo/load` and verify 200 + `{status: "loaded", workspace_id: ..., documents: 10}`
- Verify each source has a non-null `file_url`: `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT file_url IS NOT NULL FROM sources WHERE workspace_id = (SELECT id FROM workspaces WHERE name = 'Demo') LIMIT 5;"` -- all rows should be `t`
- POST `/api/demo/load` again before ingest completes -- verify it returns `{status: "exists"}` or re-creates cleanly (depending on timing) without 500
- Wait for all sources to reach `embedding_status = 'complete'`: `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT embedding_status, count(*) FROM sources WHERE workspace_id = (SELECT id FROM workspaces WHERE name = 'Demo') GROUP BY 1;"`
- POST `/api/demo/load` once more -- verify `{status: "exists"}`
- DELETE `/api/demo/unload` -- verify `{status: "removed"}` and workspace is gone

**Acceptance criteria:**
- [ ] Load returns 200 with 10 documents
- [ ] All 10 sources have non-null `file_url` pointing to `/data/uploads/{uuid}.txt`
- [ ] Second load before completion either returns `exists` or triggers clean re-create (no 500, no orphaned workspace)
- [ ] After all sources complete, third load returns `{status: "exists"}`
- [ ] Unload clears the workspace

**Commit:** None (verification only)

---

## Task 7: Verify end-to-end

**Priority:** P2
**Dependencies:** Tasks 1-6 complete

**What to do:**
- Rebuild Docker image: `docker compose build --no-cache hlh_api` and `cd frontend && npm run build`
- Start fresh stack (or verify against running stack)
- POST `/api/demo/load` via curl and verify 200 + workspace_id + 10 documents
- Verify demo data files are ingested and embedded (check source status)
- Open frontend, verify "Try Demo" button appears, click it, verify navigation
- POST again — verify `{status: "exists"}` response
- DELETE `/api/demo/unload` — verify workspace removed
- Verify no FHIR code remains: `grep -r 'fhir_bundle\|_fhir_bundle' backend/` returns zero
- Verify import cleanup: `grep -n 'import json' backend/routers/demo.py` returns zero

**Acceptance criteria:**
- [ ] Demo load returns 200 with 10 documents
- [ ] "Try Demo" button works end-to-end
- [ ] Idempotent reload works (exists status)
- [ ] Unload removes Demo workspace
- [ ] Zero dead FHIR references in codebase
- [ ] Zero `import json` in demo.py

**Commit:** None (verification only)
