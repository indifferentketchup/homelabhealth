# Tasks: lift-deep-research

**Date:** 2026-06-13

Tasks are ordered by dependency. T1-T3 are independent of each other except
where noted. T4 depends on T1. T5 is standalone.

---

## T1 - Seed deep_research_max_loops in schema.sql

- [x] In `backend/schema.sql`, locate the block of `INSERT INTO global_settings`
      seed statements near the end of the file (search for existing
      `INSERT INTO global_settings` to find the correct location).
- [x] Add the following idempotent insert immediately after the existing
      `global_settings` seed rows:
      ```sql
      INSERT INTO global_settings (key, value)
      VALUES ('deep_research_max_loops', '3')
      ON CONFLICT (key) DO NOTHING;
      ```
- [x] Confirm no `ALTER TABLE` or column addition is used. The `global_settings`
      table is key/value (key TEXT PK, value TEXT NOT NULL) per CLAUDE.md.
- [x] Run `python -m py_compile backend/schema.sql` -- this will fail (SQL is not
      Python); instead verify by grepping: `grep -c 'deep_research_max_loops'
      backend/schema.sql` must return 1.

**Acceptance:** `grep 'deep_research_max_loops' backend/schema.sql` returns the
INSERT line. With stack running: `docker exec hlh_db psql -U hlh -d hlh -tAc
"SELECT value FROM global_settings WHERE key='deep_research_max_loops'"` returns
`3` (after `docker compose up --build -d`).

---

## T2 - Create services/deep_research.py

- [x] Create `backend/services/deep_research.py` with the following structure
      (all sections required):

  **Imports:**
  ```python
  from __future__ import annotations
  import json
  import logging
  from collections.abc import AsyncIterator
  import httpx
  from db import get_pool
  from services.searx import searx_search_sources
  from services.provider_client import build_headers, resolve_provider_for_workspace
  ```

  **`_load_max_loops(default: int) -> int`** (async): reads
  `global_settings.deep_research_max_loops` via asyncpg, returns int; falls back
  to `default` on any failure. Uses `SELECT value FROM global_settings WHERE
  key = 'deep_research_max_loops'`.

  **`_summarize(query, current_query, snippets, provider, model) -> str`** (async):
  single LLM call. System prompt: "You are a medical research assistant. Summarize
  the following web search results as they relate to the research question. Extract
  key facts, values, and relevant details." User content: question + snippets.
  `temperature=0.1`, `max_tokens=512`. Returns empty string on failure (log at
  WARNING level).

  **`_compress_findings(findings, provider, model) -> str`** (async): single LLM
  call. System prompt: "Compress the following research findings into a concise
  summary. Preserve all key facts, values, dates, and source references."
  `temperature=0.1`, `max_tokens=512`. Returns original `findings` string on
  failure (safe fallback, log at WARNING level).

  **`_reflect(original_query, findings, provider, model) -> tuple[bool, str | None]`**
  (async): reflection LLM call with `response_format: {type: "json_object"}`.
  Prompt per design.md. Parse result for `{"continue": bool, "follow_up_query": str}`.
  On ANY exception (network, parse failure, unexpected JSON structure): log at
  WARNING level and return `(True, original_query)`. Never raise. Never return
  empty `follow_up_query` as `""` -- coerce to `None` if blank.

  **`_synthesize(original_query, findings, sources, provider, model) -> str`**
  (async): final synthesis LLM call. System prompt: "You are a medical research
  assistant. Synthesize the following research findings into a comprehensive answer
  to the original question. Use inline citations like [Source Title] where relevant.
  Be accurate and cite only facts present in the findings." Include sources list
  (title + URL) in user content. `temperature=0.2`, `max_tokens=1024`. Returns
  empty string on failure (log ERROR level).

  **`run_deep_research(query, workspace_id, chat_id, *, max_loops=3) -> AsyncIterator[dict]`**
  (async generator): implements the loop per design.md. Must yield:
  - `{"type": "dr_phase", "phase": "searching"|"summarizing"|"reflecting"|"compressing"|"done", "loop": N}`
  - `{"type": "dr_sources", "sources": [...], "loop": N}` after each search
  - `{"type": "dr_result", "content": "...", "sources": [...]}` at the end
  - `{"type": "dr_error", "error": "..."}` on fatal errors (provider not configured)
  Compression is triggered only when `len(findings) > 3000` and loop is not the
  last one. Reflection is skipped on the final loop. On empty `markdown_block`
  from searx, break early and synthesize from whatever findings exist.

- [x] Run `python -m py_compile backend/services/deep_research.py` -- must exit 0.
- [x] Run `python -m py_compile $(find backend -name '*.py')` -- must exit 0.

**Acceptance:** `python -m py_compile backend/services/deep_research.py` exits 0.
All functions present: `grep -n "^async def\|^def" backend/services/deep_research.py`
shows `_load_max_loops`, `_summarize`, `_compress_findings`, `_reflect`,
`_synthesize`, `run_deep_research`.

**Implementation notes:**
- F2 fix applied: `import uuid` added; `workspace_id: str` is converted via
  `uuid.UUID(workspace_id)` before calling `resolve_provider_for_workspace`.
- `_append_findings` is a plain `def` (not async), also present.

---

## T3 - Upgrade SUMMARY_SYSTEM_PROMPT in compaction.py (B2)

- [x] In `backend/services/compaction.py`, replace the `SUMMARY_SYSTEM_PROMPT`
      constant. Cross-phase note: the prior lift-context-pruning change had already
      modified the prompt to add the PRESERVED FACTS reference. B2 was NOT already
      satisfied -- the priority ordering and "medications" framing were still absent.
      The new prompt merges the B2 priority list with the existing PRESERVED FACTS
      reference (both preserved).
- [x] Confirm `COMPACTION_THRESHOLD`, `TAIL_TURNS`, `SUMMARY_TIMEOUT`, and all
      function signatures below are unchanged.
- [x] Run `python -m py_compile backend/services/compaction.py` -- must exit 0.
- [x] Do NOT add a version-bump variable. Only `services/safeguards.py` tracks
      `SAFEGUARD_VERSION` per CLAUDE.md convention.

**Acceptance:** `python -m py_compile backend/services/compaction.py` exits 0.
`grep -A8 'SUMMARY_SYSTEM_PROMPT' backend/services/compaction.py` shows the new
prompt text including "unresolved questions", "medications and dosages", and the
PRESERVED FACTS reference from G.1.

---

## T4 - Add deep_research endpoint to routers/chats.py

Depends on T2 (deep_research.py must exist before importing it).

- [x] In `backend/routers/chats.py`, add `DeepResearchBody` Pydantic model near
      `ApprovalResponseBody`.
- [x] Add the new endpoint at end of file with lazy import of `run_deep_research`.
- [x] F1 fix applied: used `Depends(get_principal)` (not `require_owner` which is
      not imported in chats.py). Matches every other endpoint in the file.
- [x] F3 fix applied: `chat_id: uuid.UUID` (not str). FastAPI auto-validates UUID.
- [x] F4 fix applied: `StreamingResponse` includes SSE headers:
      `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
- [x] Confirm `uuid`, `StreamingResponse`, `json`, `_sse` already in scope (confirmed).
- [x] Run `python -m py_compile backend/routers/chats.py` -- must exit 0.
- [x] Run `python -m py_compile $(find backend -name '*.py')` -- must exit 0.

**Acceptance:** `python -m py_compile backend/routers/chats.py` exits 0.
`grep -n "deep_research" backend/routers/chats.py` shows the new endpoint and
import. With stack running: `curl -s -X POST http://localhost:9600/api/chats/
<valid-chat-id>/deep_research -H "Content-Type: application/json" -d
'{"query":""}' -b "hlh_session=<token>"` returns HTTP 400 with
`{"detail":"query is required"}`.

---

## T5 - Create verify_deep_research.sh

- [x] Create `backend/scripts/verify_deep_research.sh` (executable,
      `set -euo pipefail`).
- [x] Confirm the script uses `PASS=$((PASS+1))` not `((PASS++))` per CLAUDE.md.
- [x] Confirm `chmod +x backend/scripts/verify_deep_research.sh`.
- [x] Run `bash -n backend/scripts/verify_deep_research.sh` -- must exit 0.

**Acceptance:** `bash -n backend/scripts/verify_deep_research.sh` exits 0.
`ls -la backend/scripts/verify_deep_research.sh` shows executable bit.

---

## T6 - Cross-cutting verification

- [x] `python -m py_compile $(find backend -name '*.py')` -- no errors (verified).
- [ ] `cd frontend && npm run build` -- no errors (no frontend changes in this
      batch; this confirms nothing was accidentally broken). REMAINING LIVE.
- [ ] With stack running after `docker compose up --build -d`:
      - `docker logs hlh_api | grep -i error | tail -20` -- REMAINING LIVE.
      - `docker exec hlh_db psql -U hlh -d hlh -tAc "SELECT value FROM
        global_settings WHERE key='deep_research_max_loops'"` -- REMAINING LIVE.
      - Run `backend/scripts/verify_deep_research.sh` with a valid session cookie.
        REMAINING LIVE.
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for B1 and B2.

**Acceptance:** `git diff --stat` shows changes in `backend/services/deep_research.py`,
`backend/routers/chats.py`, `backend/services/compaction.py`, `backend/schema.sql`,
`backend/scripts/verify_deep_research.sh`, and `CHANGELOG.md` only. No unrelated
files modified.
