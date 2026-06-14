# Tasks: lift-context-pruning

**Date:** 2026-06-13

Implement in order: G.3 first (prerequisite), then G.1, then G.2.
G.2 is independent of G.1 but touches the same function; do it after G.1 to
minimize merge conflicts.

---

## G.3-1 - Fix pruning.py COUNT query to exclude compacted rows

- [x] In `backend/services/pruning.py` line 96-100, change the `COUNT` query to
      add `AND compacted_at IS NULL`:
      ```python
      count_row = await conn.fetchrow(
          "SELECT COUNT(*)::int AS c FROM messages WHERE chat_id = $1::uuid AND compacted_at IS NULL",
          chat_id,
      )
      ```
- [x] Run `python3 -m py_compile backend/services/pruning.py` -- must produce no
      output.

**Acceptance criteria:** `py_compile` passes. The query string contains
`compacted_at IS NULL`.

---

## G.3-2 - Fix pruning.py message SELECT to exclude compacted rows

- [x] In `backend/services/pruning.py` lines 102-110, add `AND compacted_at IS NULL`
      to the `SELECT` query:
      ```python
      rows = await conn.fetch(
          """
          SELECT id, role, content, created_at
          FROM messages
          WHERE chat_id = $1::uuid AND compacted_at IS NULL
          ORDER BY created_at ASC, id ASC
          """,
          chat_id,
      )
      ```
- [x] Run `python3 -m py_compile backend/services/pruning.py` -- must pass.

**Acceptance criteria:** `py_compile` passes. The SELECT for `rows` contains
`compacted_at IS NULL`. The two query changes together prevent pruning.py from
including soft-deleted compacted messages in its transcript and threshold count.

---

## G.3-3 - Verify coordination fix with curl

- [ ] With the full stack running (`docker compose up -d`), send a chat message
      and confirm no ERROR lines containing `compaction` or `pruning` appear:
      ```bash
      docker logs --since 10s hlh_api 2>&1 | grep -i "compaction\|pruning"
      ```
- [ ] Confirm `docker logs hlh_api` shows no `inference_job: pruning failed`
      or `inference_job: compaction failed` errors after a send.

**Acceptance criteria:** No ERROR-level compaction/pruning lines in logs after
a normal chat turn.

**NOTE: REMAINING LIVE VERIFICATION -- requires running stack.**

---

## G.1-1 - Add _extract_medical_facts helper to compaction.py

- [x] In `backend/services/compaction.py`, add the `import re` statement at the
      top of the file (after existing imports).
- [x] Add the following function before `maybe_compact`:

      ```python
      _FACT_PATTERNS = [
          # Lab values with units: "HbA1c 7.2%", "TSH 2.4 mIU/L", "eGFR 58", "BP 120/80"
          re.compile(
              r'\b(?:HbA1c|A1C|TSH|eGFR|BUN|LDL|HDL|BMI|BP|glucose|creatinine|hemoglobin|hematocrit)'
              r'\s*[=:]\s*[\d.]+(?:\s*/\s*[\d.]+)?(?:\s*\w{1,10})?',
              re.IGNORECASE,
          ),
          # Generic numeric result with unit: "94 mg/dL", "7.2 %", "120/80 mmHg"
          re.compile(r'\b\d{1,4}(?:\.\d{1,3})?\s*(?:mg/dL|mIU/L|mmol/L|g/dL|%|mmHg|mL/min)\b'),
          # ISO dates: 2026-04-15
          re.compile(r'\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b'),
          # US dates: 04/15/2026 or 4/15/2026
          re.compile(r'\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/\d{4}\b'),
          # Written dates: April 15, 2026
          re.compile(
              r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
              r'\s+\d{1,2},?\s+\d{4}\b',
              re.IGNORECASE,
          ),
          # Diagnoses: "diagnosed with Type 2 Diabetes", "Diagnosis: Hypertension"
          re.compile(
              r'(?:diagnosed with|diagnosis\s*:|impression\s*:)\s+[A-Z][^\n.]{3,60}',
              re.IGNORECASE,
          ),
          # Medication dosages: "metformin 500mg", "lisinopril 10 mg"
          re.compile(r'\b[A-Za-z]{4,30}\s+\d{1,4}\s*(?:mg|mcg|g|mg/day|mg/mL)\b', re.IGNORECASE),
      ]
      _MAX_FACTS = 20


      def _extract_medical_facts(text: str) -> list[str]:
          """Extract verbatim medical fact spans from text for preservation after summarization.

          Returns up to _MAX_FACTS matched spans in order of appearance, deduplicated
          by exact string value.
          """
          if not text:
              return []
          seen: set[str] = set()
          facts: list[str] = []
          for pattern in _FACT_PATTERNS:
              for m in pattern.finditer(text):
                  span = m.group(0).strip()
                  if span and span not in seen:
                      seen.add(span)
                      facts.append(span)
                      if len(facts) >= _MAX_FACTS:
                          return facts
          return facts
      ```
- [x] Run `python3 -m py_compile backend/services/compaction.py` -- must pass.

**Acceptance criteria:** `py_compile` passes. Function `_extract_medical_facts`
is importable from `services.compaction`.

---

## G.1-2 - Apply fact-pinning in compaction.py _generate_summary call site

- [x] In `backend/services/compaction.py` `_run_compaction`, after `summary` is
      returned from `_generate_summary`, add the preserved-facts append block:

      ```python
      summary = await _generate_summary(head_text, existing_summary)
      if not summary:
          return False

      facts = _extract_medical_facts(head_text)
      if facts:
          facts_block = "\n\n## PRESERVED FACTS\n(extracted verbatim from summarized messages)\n" + \
                        "\n".join(f"- {f}" for f in facts)
          summary = summary + facts_block
      ```
- [x] Update `SUMMARY_SYSTEM_PROMPT` to add a trailing sentence informing the
      model about the PRESERVED FACTS block:
      ```python
      SUMMARY_SYSTEM_PROMPT = (
          "Summarize the following conversation for context continuity. "
          "Preserve: key medical facts, test results mentioned, dates discussed, "
          "decisions made, and action items. Be concise but complete. "
          "A PRESERVED FACTS block will follow your summary -- "
          "treat those verbatim facts as authoritative ground truth."
      )
      ```
- [x] Run `python3 -m py_compile backend/services/compaction.py` -- must pass.

**Acceptance criteria:** `py_compile` passes. The `PRESERVED FACTS` block is
appended to the summary string before the `UPDATE chats` write.

---

## G.1-3 - Apply fact-pinning in pruning.py

- [x] In `backend/services/pruning.py`, add the import at the top of the file
      (after existing imports):
      ```python
      from services.compaction import _extract_medical_facts
      ```
- [x] In `summarize_and_compress`, after the `summary = await _openai_summarize(...)`
      call and the `if not summary: return` guard, add the preserved-facts block.
      NOTE (V2 fix): `_extract_medical_facts` is called on a freshly decrypted
      transcript (using `decrypt_column` per row) so the regex works when
      `HLH_MASTER_KEY` is set.
- [x] Update the inline summary prompt in `_openai_summarize` to add the
      same trailing sentence.
- [x] Run `python3 -m py_compile backend/services/pruning.py` -- must pass.

**Acceptance criteria:** `py_compile` passes. The `PRESERVED FACTS` block is
appended to `summary` before `UPDATE chats SET pruning_summary` in pruning.py.

---

## G.1-4 - Verify fact-pinning end-to-end with curl

- [ ] With the stack running, send a chat message in a workspace that has a chat
      with enough history to trigger either compaction or pruning. Alternatively
      seed a test chat manually:
      ```bash
      # Confirm pruning_summary is updated after a send
      docker exec hlh_db psql -U hlh -d hlh -c \
        "SELECT id, length(pruning_summary), pruning_summary FROM chats WHERE pruning_summary IS NOT NULL LIMIT 3;"
      ```
- [ ] If the summary is non-null, confirm the presence of the `PRESERVED FACTS`
      section heading in the output above.
- [ ] Confirm no Python `ImportError` for `_extract_medical_facts` in
      `docker logs hlh_api`.

**Acceptance criteria:** At least one chat row has `pruning_summary` containing
the string `PRESERVED FACTS` (if any summarization has triggered). No import
errors in logs.

**NOTE: REMAINING LIVE VERIFICATION -- requires running stack.**

---

## G.2-1 - Priority-aware head selection in compaction.py

- [x] In `backend/services/compaction.py` `_run_compaction`, replace the existing
      head-decryption and `head_lines` assembly block with the priority-sorted
      version using `head_entries` tuples (row, plain, weight).
- [x] Run `python3 -m py_compile backend/services/compaction.py` -- must pass.

**Acceptance criteria:** `py_compile` passes. `head_ids` is derived from
`head_entries`. The `head_entries.sort(...)` line is present.

---

## G.2-2 - Verify no regression in compaction

- [x] Run `python3 -m py_compile $(find /home/samkintop/opt/homelabhealth/backend -name '*.py')` -- no
      output (all modules compile clean).
- [ ] With the stack running, confirm `docker logs hlh_api` shows no new
      `compaction failed` or `pruning failed` error lines after sending a
      message.

**Acceptance criteria:** Full `py_compile` sweep passes with zero errors.
No new ERROR lines in API logs after a send.

**NOTE: Live stack check is REMAINING LIVE VERIFICATION.**

---

## Cross-cutting verification

- [x] `python3 -m py_compile $(find /home/samkintop/opt/homelabhealth/backend -name '*.py')` -- passes.
- [ ] `docker compose up --build -d` starts cleanly; `docker logs hlh_api` shows
      no import errors or schema errors on startup. Use
      `docker compose -f /home/samkintop/opt/homelabhealth/docker-compose.yml up --build -d`
      if not running from repo root.
- [x] Update `CHANGELOG.md` under `[Unreleased]` with entries for G.3, G.1, G.2.

**NOTE: `docker compose up --build` is REMAINING LIVE VERIFICATION.**
