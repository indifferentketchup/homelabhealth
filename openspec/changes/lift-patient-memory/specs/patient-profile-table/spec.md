## ADDED Requirements

### Requirement: workspace_patient_profile table exists and is idempotent

`backend/schema.sql` SHALL define a `workspace_patient_profile` table with columns
`workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE`,
`profile JSONB NOT NULL DEFAULT '{}'`, and
`updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
The CREATE statement SHALL use `CREATE TABLE IF NOT EXISTS`.
A backfill INSERT (`SELECT id FROM workspaces ON CONFLICT DO NOTHING`) SHALL ensure
every existing workspace has a profile row after any DB restart.
**Reason**: C.md item 2 -- `workspace_memory` is a multi-row TEXT table; no JSONB
profile column exists anywhere in schema.sql. Structured durable facts require a
new table.
**Evidence**: `backend/schema.sql:296-303` -- `workspace_memory` is plain TEXT, no
structured profile. Confirmed no `workspace_patient_profile` in schema.sql.

#### Scenario: Fresh DB has profile row for new workspace
- **WHEN** a new workspace is created on a fresh DB
- **THEN** `GET /api/workspaces/{workspace_id}/patient-profile` returns HTTP 200
  with `{"profile": {}}` or an empty-fields profile object

#### Scenario: Existing DB backfills profile rows on restart
- **WHEN** `schema.sql` runs against an existing DB that has workspaces but no
  `workspace_patient_profile` rows
- **THEN** every workspace has a corresponding `workspace_patient_profile` row with
  `profile = '{}'`

#### Scenario: Workspace delete cascades to profile
- **WHEN** a workspace is deleted
- **THEN** `GET /api/workspaces/{workspace_id}/patient-profile` returns HTTP 404

#### Scenario: Schema is idempotent
- **WHEN** `schema.sql` is applied twice to the same DB
- **THEN** no errors are raised on the second run

### Requirement: Profile CRUD endpoints are available

`GET /api/workspaces/{workspace_id}/patient-profile` SHALL return HTTP 200 with
`{"workspace_id": "...", "profile": {...}, "updated_at": "..."}`.
`PUT /api/workspaces/{workspace_id}/patient-profile` with body `{"profile": {...}}`
SHALL upsert the profile and return HTTP 200.
Both endpoints SHALL require a valid session cookie (HTTP 401 if unauthenticated).
`GET` SHALL return HTTP 404 if the workspace does not exist.
**Reason**: Operators need to inspect and seed the profile for a workspace.
**Evidence**: `backend/routers/workspaces.py` -- no patient-profile routes present.

#### Scenario: Unauthenticated GET returns 401
- **WHEN** `GET /api/workspaces/{workspace_id}/patient-profile` is called without
  a session cookie
- **THEN** the response is HTTP 401

#### Scenario: PUT updates profile and GET reflects it
- **WHEN** `PUT /api/workspaces/{workspace_id}/patient-profile` is called with
  `{"profile": {"active_diagnoses": ["Type 2 diabetes"]}}`
- **THEN** the subsequent `GET` returns a profile containing
  `"active_diagnoses": ["Type 2 diabetes"]`

#### Scenario: GET returns 404 for unknown workspace
- **WHEN** `GET /api/workspaces/00000000-0000-0000-0000-000000000000/patient-profile`
  is called with a valid session
- **THEN** the response is HTTP 404

### Requirement: Global settings seeds for memory configuration

`backend/schema.sql` SHALL seed `memory_conflict_resolution_enabled` with value
`'false'` and `memory_injection_token_budget` with value `'1500'` via idempotent
`INSERT ... ON CONFLICT (key) DO NOTHING`.
**Reason**: Conflict resolution is expensive on bundled 4b models; opt-in default
is required. Token budget must be configurable.
**Evidence**: C.md blocking unknown #2 -- `memory_conflict_resolution_enabled` flag
is mandatory, not optional.

#### Scenario: Default settings present after first boot
- **WHEN** the DB is initialized for the first time
- **THEN** `SELECT value FROM global_settings WHERE key='memory_conflict_resolution_enabled'`
  returns `'false'`
- **AND** `SELECT value FROM global_settings WHERE key='memory_injection_token_budget'`
  returns `'1500'`
