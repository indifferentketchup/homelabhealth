## ADDED Requirements

### Requirement: resolve_conflicts uses a prescribed system prompt with exact JSON schema

`backend/services/patient_profile.py:resolve_conflicts` SHALL use
`_CONFLICT_RESOLUTION_PROMPT` as the system message text. The prompt MUST instruct
the model to prefer newer information, supersede contradictions, and return only
the prescribed JSON schema -- nothing else.
The user message SHALL be formatted as:
`"EXISTING FACTS:\n{json.dumps(existing_facts, indent=2)}\n\nNEW FACTS:\n{json.dumps(new_facts, indent=2)}"`.
The LLM call SHALL use `stream: false`, `max_tokens: 512`, `temperature: 0.0`.
On any parse failure or LLM error, the function SHALL fall back to `(new_facts, [])`.
**Reason**: The prompt is load-bearing for patient safety -- a poorly-worded prompt
could cause medication facts to be incorrectly deleted or retained. The exact text
and schema must be specified, not left to implementor discretion.
**Evidence**: C.md item 1 -- patient-safety impact: "Patient takes metformin 500mg"
and "Patient takes metformin 1000mg" both survive as active facts with no
reconciliation. LLM-driven resolution requires a precise prompt to be safe.

#### Scenario: Prescribed prompt text is used
- **WHEN** `resolve_conflicts` is called
- **THEN** the LLM is sent the system message beginning with
  "You are a patient health record conflict resolver."

#### Scenario: Output schema is enforced by prompt
- **WHEN** the LLM returns valid JSON for the conflict resolution call
- **THEN** the response is parsed as `{"factsToRemove": [...], "newFacts": [...]}`

### Requirement: _CONFLICT_RESOLUTION_PROMPT is defined in patient_profile.py

The constant `_CONFLICT_RESOLUTION_PROMPT` SHALL be defined at module level in
`backend/services/patient_profile.py` with the following exact text:

```
You are a patient health record conflict resolver.

You will be given two inputs:
- EXISTING FACTS: the facts currently stored in the patient profile
- NEW FACTS: facts just extracted from a new conversation exchange

Your task: identify which existing facts are contradicted or superseded by new facts,
and return the resolution as structured JSON.

Rules:
- Prefer newer information over older when facts conflict about the same topic.
- A fact supersedes another if they describe the same attribute (e.g., same medication name,
  same diagnosis) with different values.
- Do not remove facts that are additive (different topics, complementary information).
- Keep existing facts that are not contradicted.
- Return only the IDs to remove and the new facts to add.

Return exactly this JSON schema and nothing else:
{
  "factsToRemove": ["<fact-id>", ...],
  "newFacts": [
    {"id": "<uuid4>", "content": "...", "category": "...", "confidence": 0.0,
     "source": "extraction", "created_at": "<ISO8601>", "updated_at": "<ISO8601>"}
  ]
}
```

**Reason**: Exact prompt text prevents implementor variation in safety-critical logic.
**Evidence**: Design.md C2 -- "Prompt: `_MEMORY_UPDATE_PROMPT` (transplanted verbatim)."
The source-fork version is adapted here for HLH's schema (uses `factsToRemove` ID list
rather than `RemoveDoc` objects, since HLH facts have UUIDs).

#### Scenario: Prompt is not a checklist (safeguard rule compliance)
- **WHEN** `_CONFLICT_RESOLUTION_PROMPT` is read
- **THEN** it does NOT contain numbered rules or enumerated steps prefixed with
  digits (e.g., "1.", "2.") that a reasoning model could narrate step by step
  (per CLAUDE.md: "Safeguard prompt must not be a checklist")

#### Scenario: Hallucinated IDs in factsToRemove are discarded
- **WHEN** the LLM returns a `factsToRemove` list containing an ID not present
  in the existing profile facts
- **THEN** that ID is silently discarded and no fact is removed for it

#### Scenario: LLM timeout falls back to append-only
- **WHEN** the httpx call to the LLM times out (30 second timeout)
- **THEN** `resolve_conflicts` logs a warning and returns `(new_facts, [])`
- **AND** no exception propagates to `run_background_extraction`
