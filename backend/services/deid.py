"""De-identification pipeline for source documents and chat content.

Regex-based PHI redaction with three policy levels. No model dependencies.
Replaces identified PHI with typed placeholders ([SSN], [PHONE], etc.)
so downstream embeddings don't encode raw PHI.

Architecture note: the roadmap specified a Presidio sidecar with NER
models. This regex-based module is the v0.16.0 pragmatic alternative.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class DeidFinding:
    category: str       # "ssn", "phone", "email", "mrn", "date", "zip", "name_pattern"
    original_len: int   # length of matched text (NOT the text itself  -  never log raw PHI)
    replacement: str    # what it was replaced with, e.g. "[SSN]"
    start: int          # position in original text
    end: int            # position in original text


@dataclass
class DeidResult:
    text: str                              # redacted text
    findings: list[DeidFinding] = field(default_factory=list)
    policy: str = "strict"

    @property
    def had_phi(self) -> bool:
        return len(self.findings) > 0


# Pattern sets by policy level.
# Each higher tier includes the lower tiers' patterns.

_PERMISSIVE = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
]

_STANDARD = _PERMISSIVE + [
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    ("mrn", re.compile(r"\bMRN[:\s#]*\d{4,12}\b", re.IGNORECASE), "[MRN]"),
]

_STRICT = _STANDARD + [
    ("dob", re.compile(r"(?i)(?:DOB|date\s*of\s*birth|birth\s*date|born)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b"), "[DOB]"),
    ("zip", re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[ZIP]"),
    # Catches "Dr. Smith", "Mr. Johnson", "Ms. Alice Brown"  -  title + capitalized words.
    # Known limitation: names without titles are not matched (regex cannot do NER).
    ("name_title", re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b"), "[NAME]"),
]

# Note on zip: ZIP code patterns will have false positives with other 5-digit numbers.
# In strict mode this is acceptable (defense-in-depth, over-redact rather than under-redact).
# standard mode skips it.

_POLICY_PATTERNS = {
    "permissive": _PERMISSIVE,
    "standard": _STANDARD,
    "strict": _STRICT,
}


def get_policy() -> str:
    """Read HLH_REDACTION_POLICY from env. Default 'strict'."""
    raw = os.environ.get("HLH_REDACTION_POLICY", "strict").strip().lower()
    if raw not in _POLICY_PATTERNS:
        return "strict"
    return raw


def is_enabled() -> bool:
    """Read HLH_DEID_ENABLED from env. Default 'true'."""
    return os.environ.get("HLH_DEID_ENABLED", "true").strip().lower() in ("true", "1", "yes")


def redact_text(text: str, policy: str | None = None) -> DeidResult:
    """Apply de-identification to text.

    Returns DeidResult with redacted text and list of findings.
    If deid is disabled (HLH_DEID_ENABLED=false), returns text unchanged.
    """
    if not is_enabled():
        return DeidResult(text=text, findings=[], policy="disabled")

    effective_policy = policy or get_policy()
    patterns = _POLICY_PATTERNS.get(effective_policy, _STRICT)
    findings: list[DeidFinding] = []
    result = text

    # Collect all matches from all patterns.
    # Apply patterns in reverse-specificity order (most specific first)
    # to avoid overlapping replacements.
    all_matches: list[tuple[int, int, str, str]] = []  # (start, end, category, replacement)
    for category, pattern, replacement in patterns:
        for m in pattern.finditer(result):
            all_matches.append((m.start(), m.end(), category, replacement))

    # Sort by start position ascending; earlier-starting match wins overlaps.
    # Ties broken by longer span (end descending) so "MRN#12345" beats "12345".
    all_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Deduplicate overlapping matches: greedily accept each match whose span
    # does not overlap any already-accepted match.
    accepted: list[tuple[int, int, str, str]] = []
    covered_end = -1
    for start, end, cat, repl in all_matches:
        if start >= covered_end:
            accepted.append((start, end, cat, repl))
            covered_end = end

    # Reverse so we apply replacements from end to start without
    # invalidating earlier positions.
    deduped = list(reversed(accepted))

    # Apply replacements (from end to start).
    for start, end, category, replacement in deduped:
        findings.append(DeidFinding(
            category=category,
            original_len=end - start,
            replacement=replacement,
            start=start,
            end=end,
        ))
        result = result[:start] + replacement + result[end:]

    # Reverse findings to be in document order.
    findings.reverse()

    return DeidResult(text=result, findings=findings, policy=effective_policy)


def redact_chunks(chunks: list[str], policy: str | None = None) -> tuple[list[str], list[list[DeidFinding]]]:
    """Redact a list of text chunks. Returns (redacted_chunks, per_chunk_findings)."""
    redacted = []
    all_findings = []
    for chunk in chunks:
        r = redact_text(chunk, policy)
        redacted.append(r.text)
        all_findings.append(r.findings)
    return redacted, all_findings


def pipeline_summary() -> dict[str, str | int | bool]:
    """Return pipeline status for the doctor check."""
    policy = get_policy()
    enabled = is_enabled()
    patterns = _POLICY_PATTERNS.get(policy, _STRICT)
    return {
        "enabled": enabled,
        "policy": policy,
        "pattern_count": len(patterns),
    }
