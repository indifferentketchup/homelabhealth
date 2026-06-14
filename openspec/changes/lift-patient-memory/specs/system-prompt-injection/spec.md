## MODIFIED Requirements

### Requirement: _assembled_system_prompt injects patient profile unconditionally

`_assembled_system_prompt` in `backend/routers/chats.py` (line 112) SHALL fetch the
`workspace_patient_profile` for the workspace and inject it as a `### Patient Profile`
section after the `workspace_memory` block and before context files.
Injection SHALL be unconditional -- no similarity gate.
The injection block SHALL be wrapped in try/except; any failure SHALL be caught,
logged as a warning, and not abort prompt assembly.
When the profile is empty (`{}` or all null/empty fields), no section SHALL be
appended (no empty header).
Token budget for injection is read from `global_settings.memory_injection_token_budget`
(default 1500 tokens), consumed via `format_profile_for_injection`.
**Reason**: C.md item 2 -- durable health facts must be available to the model on
every turn without requiring a similarity search.
**Evidence**: `backend/routers/chats.py:156-166` -- workspace_memory is injected as
flat bullets with no ordering or budget. No patient profile injection exists.

#### Scenario: Profile with diagnoses appears in assembled prompt
- **WHEN** a workspace has a patient profile with
  `{"active_diagnoses": ["Type 2 diabetes"]}`
- **AND** a chat message is sent in that workspace
- **THEN** `docker logs hlh_api` shows the assembled prompt preview contains
  `"Type 2 diabetes"` or `"active_diagnoses"` text

#### Scenario: Empty profile produces no section in prompt
- **WHEN** a workspace has a patient profile of `{}`
- **THEN** the assembled system prompt does NOT contain `### Patient Profile`

#### Scenario: Profile fetch failure does not abort prompt assembly
- **WHEN** the patient profile fetch raises an exception
- **THEN** a warning is logged and the rest of the system prompt sections
  (context files, custom instructions, RAG) are assembled normally

#### Scenario: Token budget limits injection size
- **WHEN** a profile contains 200 facts each 100 chars and token_budget is 1500
- **THEN** `format_profile_for_injection(profile, 1500)` returns a string of at
  most 6000 characters (1500 * 4 chars/token)

### Requirement: format_profile_for_injection renders ranked facts within budget

`backend/services/patient_profile.py` SHALL export `format_profile_for_injection(profile, token_budget)`.
Structured fields (name, DOB, blood_type, active_diagnoses, current_medications,
allergies, lab_baselines) SHALL be rendered first regardless of confidence.
`facts` SHALL be sorted by `confidence` descending, then `created_at` descending.
Token counting SHALL use `len(text) // 4` (char/4 estimate). No tiktoken.
The function SHALL return `""` for an empty or all-null profile.
**Reason**: C.md item 4 -- HLH currently has no ranked injection formatter.
**Evidence**: `services/rag.py` -- `engine.search()` returns raw SearchResult list
with no ranked formatting or token budget applied. No injection formatter exists.

#### Scenario: Facts sorted by confidence descending
- **WHEN** a profile has facts with confidence 0.3, 0.9, and 0.6
- **THEN** `format_profile_for_injection` renders the 0.9-confidence fact first

#### Scenario: Empty profile returns empty string
- **WHEN** `format_profile_for_injection({})` is called
- **THEN** the return value is `""`
