# Delta spec: eval-router

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: eval router SHALL be mounted at /api/eval/

`backend/main.py` SHALL import `backend/routers/eval.py` as `eval_router` and
call `api.include_router(eval_router.router, prefix="/eval", tags=["eval"])`.
This mount SHALL appear after the existing router mounts at lines 310-331.

The eval router already defines three endpoints with `Depends(require_admin)`:
- `POST /eval/groundedness`
- `POST /eval/helpfulness`
- `POST /eval/retrieval-relevance`

No auth changes are required. The endpoints SHALL return 403 for non-admin
callers and 200 for admin callers on the running stack.

#### Scenario: Eval endpoint returns 403 not 404 after mount

- **WHEN** a non-admin user POSTs to `http://localhost:9600/api/eval/groundedness`
  with a valid JSON body
- **THEN** the HTTP response status SHALL be 403 (Forbidden)
- **AND** the status SHALL NOT be 404 (Not Found)

#### Scenario: Admin caller receives structured eval response

- **WHEN** an admin user POSTs `{"workspace_id":"<uuid>","query":"x","context":"x","response":"x"}`
  to `/api/eval/groundedness` with a valid admin session cookie
- **THEN** the response status SHALL be 200
- **AND** the response JSON SHALL contain keys `score`, `explanation`, and `violations`

#### Scenario: py_compile passes after router mount

- **WHEN** `python3 -m py_compile backend/main.py` is run after the import and
  include_router line are added
- **THEN** the exit code SHALL be 0

#### Scenario: eval router import uses standalone statement form

- **WHEN** the import is added to `main.py`
- **THEN** it SHALL appear as a standalone `from routers.eval import router as eval_router`
  statement (matching the `demo_router` pattern at line 39)
- **AND** it SHALL NOT be inside the grouped `from routers import (...)` block
  (V6/JD-006 correction: `as` aliases are invalid inside that form)
