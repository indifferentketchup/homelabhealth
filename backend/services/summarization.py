"""Shared summarization machinery for compaction and pruning.

Owns the summary system prompt, the medical-fact regex patterns, and the
`summarize_transcript` / `extract_medical_facts` / `build_preserved_facts_block`
helpers.  Neither compaction nor pruning should define these locally.

Callers are responsible for provider resolution and disposal (soft delete vs.
hard delete) -- this module only handles the LLM call and fact extraction.
"""

from __future__ import annotations

import re

from services.provider_client import async_llm_call

# ---------------------------------------------------------------------------
# Summary system prompt
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM_PROMPT = (
    "Summarize the following conversation for context continuity. "
    "Preserve in order of priority: (1) unresolved questions and open issues, "
    "(2) lab values, vital signs, and test results with dates, "
    "(3) medications and dosages currently active or recently changed, "
    "(4) decisions made and the reasoning behind them, "
    "(5) action items and follow-up plans. "
    "Be concise but complete. Use plain prose, not bullets. "
    "A PRESERVED FACTS block will follow your summary -- "
    "treat those verbatim facts as authoritative ground truth."
)

# ---------------------------------------------------------------------------
# Medical-fact extraction
# ---------------------------------------------------------------------------

# Each pattern is bounded to prevent catastrophic backtracking on large inputs.
_FACT_PATTERNS = [
    # Lab values with units: "HbA1c 7.2%", "A1C = 7.2", "TSH 2.4 mIU/L", "BP 120/80"
    # Separator is [=:\s] to cover both "HbA1c 7.2%" (space) and "A1C = 7.2" (=/:).
    re.compile(
        r'\b(?:HbA1c|A1C|TSH|eGFR|BUN|LDL|HDL|BMI|BP|glucose|creatinine|hemoglobin|hematocrit)'
        r'\s*[=:\s]\s*[\d.]+(?:\s*/\s*[\d.]+)?(?:\s*[\w%/]{1,12})?',
        re.IGNORECASE,
    ),
    # Generic numeric result with unit: "94 mg/dL", "7.2%", "120/80 mmHg"
    # Trailing \b omitted -- % and other unit-final chars are non-word and would
    # block matching "7.2%" at end-of-span or before whitespace.
    re.compile(r'\b\d{1,4}(?:\.\d{1,3})?\s*(?:mg/dL|mIU/L|mmol/L|g/dL|%|mmHg|mL/min)'),
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


def extract_medical_facts(text: str) -> list[str]:
    """Extract verbatim medical fact spans from text for preservation after summarization.

    Returns up to _MAX_FACTS matched spans in order of appearance, deduplicated
    by exact string value.  Returns [] for empty input.
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


def build_preserved_facts_block(facts: list[str]) -> str:
    """Return the '## PRESERVED FACTS' appendix string for a non-empty facts list.

    Prepends a blank line so callers can do `summary += build_preserved_facts_block(facts)`
    without having to manage the separator themselves.
    """
    return (
        "\n\n## PRESERVED FACTS\n"
        "(extracted verbatim from summarized messages)\n"
        + "\n".join(f"- {f}" for f in facts)
    )


# ---------------------------------------------------------------------------
# LLM summarization
# ---------------------------------------------------------------------------

async def summarize_transcript(
    provider: object,
    model: str,
    transcript: str,
    existing_summary: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout_s: float = 60.0,
) -> str:
    """Call the LLM to produce a rolling summary of `transcript`.

    `provider` and `model` must already be resolved by the caller.
    `existing_summary` is prepended to the user message when present so the
    model can update the rolling summary rather than start fresh.

    Returns the raw LLM text (non-empty) or raises on failure.  Returns ""
    when the LLM response is empty.
    """
    prompt_parts: list[str] = []
    if existing_summary:
        prompt_parts.append(f"Previous conversation summary:\n{existing_summary}\n")
    prompt_parts.append(f"Conversation to summarize:\n{transcript}")

    return await async_llm_call(
        provider,
        model,
        [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    ) or ""
