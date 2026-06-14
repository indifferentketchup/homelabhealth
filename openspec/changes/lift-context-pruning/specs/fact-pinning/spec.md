# Delta spec: fact-pinning (G.1)

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: _extract_medical_facts SHALL extract verbatim medical fact spans

`backend/services/compaction.py` SHALL expose a module-level function
`_extract_medical_facts(text: str) -> list[str]` that applies regex patterns
to `text` and returns up to 20 matched spans in order of appearance.

Patterns SHALL cover:
- Named lab values with optional units (HbA1c, TSH, eGFR, BUN, LDL, HDL,
  BMI, BP, glucose, creatinine, hemoglobin, hematocrit)
- Generic numeric results followed by a recognized unit (mg/dL, mIU/L,
  mmol/L, g/dL, %, mmHg, mL/min)
- ISO dates (YYYY-MM-DD)
- US dates (M/D/YYYY or MM/DD/YYYY)
- Written dates (Month D, YYYY)
- Diagnosis phrases ("diagnosed with ...", "diagnosis: ...", "impression: ...")
- Medication dosages (drug name followed by amount and unit)

The function SHALL return `[]` for empty input and SHALL NOT raise.

#### Scenario: Lab value is extracted from message text

- **WHEN** `_extract_medical_facts` is called with text containing "HbA1c 7.2%"
- **THEN** the returned list SHALL contain the span "HbA1c 7.2%"

#### Scenario: ISO date is extracted

- **WHEN** `_extract_medical_facts` is called with text containing "2026-04-15"
- **THEN** the returned list SHALL contain the span "2026-04-15"

#### Scenario: Empty input returns empty list without error

- **WHEN** `_extract_medical_facts` is called with an empty string
- **THEN** the returned list SHALL be `[]`
- **AND** no exception SHALL be raised

#### Scenario: Result is capped at 20 facts

- **WHEN** the input text contains more than 20 distinct matching spans
- **THEN** the returned list SHALL contain at most 20 entries

### Requirement: compaction.py SHALL append a PRESERVED FACTS block after the LLM summary

`_run_compaction` SHALL call `_extract_medical_facts(head_text)` after
`_generate_summary` returns a non-empty summary and, if the result is non-empty,
append a `## PRESERVED FACTS` block to the summary before writing it to
`chats.pruning_summary`.

The block format SHALL be:
```
\n\n## PRESERVED FACTS\n(extracted verbatim from summarized messages)\n- <fact1>\n- <fact2>...
```

`SUMMARY_SYSTEM_PROMPT` SHALL include a sentence informing the model that a
PRESERVED FACTS block will follow its output and that those facts are
authoritative.

#### Scenario: PRESERVED FACTS block is appended when facts exist

- **WHEN** the head messages contain "HbA1c 7.2%" and compaction runs
- **THEN** the written `pruning_summary` SHALL contain the substring "## PRESERVED FACTS"
- **AND** the substring "HbA1c 7.2%" SHALL appear after the `## PRESERVED FACTS` heading

#### Scenario: No PRESERVED FACTS block when no facts are found

- **WHEN** the head messages contain no patterns matching any regex
- **THEN** the written `pruning_summary` SHALL NOT contain "## PRESERVED FACTS"
- **AND** the summary is the unmodified LLM output

### Requirement: pruning.py SHALL also append PRESERVED FACTS after its summary

`summarize_and_compress` in `backend/services/pruning.py` SHALL import
`_extract_medical_facts` from `services.compaction` and apply the same
PRESERVED FACTS append after `_openai_summarize` returns a non-empty summary.

The inline prompt in `_openai_summarize` SHALL include the same trailing
sentence about the PRESERVED FACTS block.

This ensures external-tier users (where compaction no-ops) also receive
fact-pinned summaries.

#### Scenario: External-tier user receives fact-pinned pruning summary

- **WHEN** no bundled chat provider is configured (external tier)
- **AND** message count reaches `pruning_threshold`
- **AND** the messages contain medical facts matching the regex patterns
- **THEN** `pruning_summary` SHALL contain a `## PRESERVED FACTS` block
- **AND** compaction SHALL have been skipped (no bundled provider)

#### Scenario: Pruning PRESERVED FACTS uses the pruned transcript

- **WHEN** `summarize_and_compress` builds `transcript` from `to_prune` rows
- **AND** those rows contain a medication dosage "metformin 500mg"
- **THEN** the written `pruning_summary` SHALL contain "metformin 500mg" in
  the PRESERVED FACTS block
