## MODIFIED Requirements

### Requirement: _assembled_system_prompt has per-section error handling
Each major section of `_assembled_system_prompt()` (lines 112-262) SHALL be wrapped in try/except with a placeholder on failure.
**Reason**: Audit finding S3 -- 7 sequential DB fetches with no error isolation. A transient failure silently truncates the prompt.
**Migration**: None -- assembly continues with placeholder on section failure.

#### Scenario: Workspace instructions fetch failure does not truncate prompt
- **WHEN** the workspace instructions DB fetch throws an exception
- **THEN** a placeholder comment is appended for that section, and remaining sections (memory, context files, RAG, etc.) are assembled normally

#### Scenario: Safeguard prepend always executes
- **WHEN** any section of `_assembled_system_prompt` fails
- **THEN** `prepend_safeguard(assembled)` is still called on whatever was assembled

### Requirement: model warm-up failure yields SSE warning
The model warm-up block (lines 1529-1537) SHALL yield an SSE warning event on failure instead of silently passing.
**Reason**: Audit finding B7/B14 -- if warm-up fails, the pipeline continues to inference which fails with a generic "Inference failed" error. User sees the wrong error message.
**Migration**: None -- new SSE event, inference still proceeds.

#### Scenario: Warm-up failure yields warning before inference
- **WHEN** the model warm-up HTTP call fails
- **THEN** an SSE event `{"type": "warning", "message": "Model warm-up failed..."}` is yielded, and inference is still attempted

### Requirement: silently swallowed errors produce log output
Locations at lines 1190, 1467, 1743, 1755, 1786 SHALL log at warning level instead of silently passing.
**Reason**: Audit finding S4 -- user profile fetch, attached source read, auto-title, and memory embedding failures are silently swallowed.
**Migration**: None -- log output only, no behavior change.

#### Scenario: User profile fetch failure is logged
- **WHEN** the user profile DB fetch throws an exception in `_assembled_system_prompt`
- **THEN** a warning is logged with the exception details, and `user_profile_block` remains empty

#### Scenario: Auto-title generation failure is logged
- **WHEN** `_openai_short_chat_title` throws an exception
- **THEN** a warning is logged, and `new_title` falls back to "New chat"

### Requirement: export_chat extracts helpers
The `export_chat` endpoint SHALL use extracted `write_export_file()` and `ai_rename_file()` helpers.
**Reason**: Audit finding S6 -- file write, AI title generation, collision loop, and audit logging in one 108-line function.
**Migration**: None -- behavior-preserving refactor.

#### Scenario: Export with AI rename uses helper
- **WHEN** `export_chat` is called and the AI title generation succeeds
- **THEN** `ai_rename_file()` handles slug creation, collision loop, and rename, returning the final path and `ai_renamed=true`

#### Scenario: Export without provider falls back to timestamp
- **WHEN** `export_chat` is called and no provider is configured for the workspace
- **THEN** the timestamp filename persists and `ai_renamed=false` is returned

### Requirement: export_chat response shape unchanged
The `export_chat` endpoint SHALL return the same JSON shape: `{"filename", "workspace_slug", "path", "ai_renamed"}`.
**Reason**: Frontend consumers depend on this response shape.
**Migration**: None -- response shape preserved.

#### Scenario: Export response contains all required fields
- **WHEN** `POST /api/chats/{id}/export` succeeds
- **THEN** the response contains `filename`, `workspace_slug`, `path`, and `ai_renamed` fields

### Requirement: wire-contract error strings remain byte-identical
All wire-contract error strings near the modified code paths MUST remain byte-identical after changes.
**Reason**: Frontend `ChatView.jsx` and Playwright assertions match these strings verbatim (CLAUDE.md hard rules).

#### Scenario: Wire-contract strings preserved
- **WHEN** any modification is made to `chats.py`
- **THEN** the following strings remain byte-identical: `"input_blocked"`, `"Inference was rejected by user."`, `"Another response is still streaming..."`, `"Document retrieval failed. Try again or start a fresh chat."`, `"Inference failed. Check server logs for details."`, `"Analysis failed. Check server logs for details."`
