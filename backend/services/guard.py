"""I/O guard scanner for chat content.

Input scanning: detects prompt injection attempts and banned substrings
before the prompt reaches the inference sidecar.

Output scanning: detects PII regurgitation, medical-advice patterns,
crisis content, and hallucinated identifiers in assistant responses
before they are stored.

Architecture note: the roadmap specified a separate `hlh_guard` Docker
sidecar running llm-guard. This in-process regex scanner is the
v0.14.0 pragmatic alternative — same functional coverage for a
single-user LAN deployment without the container overhead. A future
release can migrate to a sidecar if the threat model changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ScanFlag:
    category: str      # e.g. "pii_leak", "prompt_injection", "medical_advice"
    pattern_name: str   # which pattern matched
    matched_text: str   # the actual matched substring (REDACTED for PII)
    detail: str         # human-readable explanation


@dataclass
class ScanResult:
    passed: bool
    flags: list[ScanFlag] = field(default_factory=list)

    def to_json(self) -> list[dict]:
        return [
            {"category": f.category, "pattern": f.pattern_name, "detail": f.detail}
            for f in self.flags
        ]


# ---------------------------------------------------------------------------
# Input scanner patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are\s+(a|an)?\s*(?!patient|person|user)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a|an)\s+(?!patient|person|user)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s*mode", re.IGNORECASE),
    re.compile(r"developer\s*mode\s*(enabled|on|activate)", re.IGNORECASE),
]

_BAN_SUBSTRINGS = [
    "repeat the above",
    "show me your instructions",
    "what are your rules",
    "print your system prompt",
    "reveal your prompt",
    "output your instructions",
]


# ---------------------------------------------------------------------------
# Output scanner patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    ("ssn",      re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("us_phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("email",    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("mrn",      re.compile(r"\bMRN[:\s#]*\d{4,12}\b", re.IGNORECASE)),
]

_MEDICAL_ADVICE_PATTERNS = [
    re.compile(r"\byou\s+should\s+take\s+\d+\s*(mg|ml|mcg|units?)\b", re.IGNORECASE),
    re.compile(r"\btake\s+\d+\s*(mg|ml|mcg|units?)\s+of\b", re.IGNORECASE),
    re.compile(r"\byour\s+diagnosis\s+is\b", re.IGNORECASE),
    re.compile(r"\bi\s+diagnose\s+you\s+with\b", re.IGNORECASE),
    re.compile(r"\bi\s+prescribe\b", re.IGNORECASE),
    re.compile(r"\bstop\s+taking\s+your\s+(medication|medicine)\b", re.IGNORECASE),
    re.compile(r"\bincrease\s+your\s+dose\s+to\b", re.IGNORECASE),
]

_CRISIS_PATTERNS = [
    re.compile(r"\b(suicide|suicidal|kill\s+myself|end\s+my\s+life|self[- ]harm|overdose)\b", re.IGNORECASE),
]

_HALLUCINATED_ID_PATTERNS = [
    ("npi", re.compile(r"\bNPI[:\s#]*\d{10}\b", re.IGNORECASE)),
    ("dea", re.compile(r"\bDEA[:\s#]*[A-Za-z]{2}\d{7}\b", re.IGNORECASE)),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_input(text: str) -> ScanResult:
    """Scan a user prompt for injection attempts and banned substrings.

    Returns ScanResult with passed=False and populated flags if any pattern
    matches. The caller decides whether to block the request or log.
    """
    flags: list[ScanFlag] = []

    for i, pattern in enumerate(_INJECTION_PATTERNS):
        m = pattern.search(text)
        if m:
            flags.append(ScanFlag(
                category="prompt_injection",
                pattern_name=f"injection_{i}",
                matched_text=m.group(0),
                detail=f"Prompt injection pattern matched: {m.group(0)!r}",
            ))

    text_lower = text.lower()
    for substring in _BAN_SUBSTRINGS:
        if substring in text_lower:
            flags.append(ScanFlag(
                category="prompt_injection",
                pattern_name="ban_substring",
                matched_text=substring,
                detail=f"Banned substring detected: {substring!r}",
            ))

    return ScanResult(passed=len(flags) == 0, flags=flags)


def scan_output(text: str) -> ScanResult:
    """Scan an assistant response for PII, medical advice, crisis content,
    and hallucinated identifiers.

    Crisis flags set passed=True (flag but don't block — the response may
    contain helpful crisis resources). All other flag categories set
    passed=False.
    """
    flags: list[ScanFlag] = []
    blocking = False

    for name, pattern in _PII_PATTERNS:
        m = pattern.search(text)
        if m:
            flags.append(ScanFlag(
                category="pii_leak",
                pattern_name=name,
                matched_text="[REDACTED]",
                detail=f"PII pattern '{name}' matched in output (value redacted)",
            ))
            blocking = True

    for i, pattern in enumerate(_MEDICAL_ADVICE_PATTERNS):
        m = pattern.search(text)
        if m:
            flags.append(ScanFlag(
                category="medical_advice",
                pattern_name=f"medical_{i}",
                matched_text=m.group(0),
                detail=f"Medical advice pattern matched: {m.group(0)!r}",
            ))
            blocking = True

    for i, pattern in enumerate(_CRISIS_PATTERNS):
        m = pattern.search(text)
        if m:
            flags.append(ScanFlag(
                category="crisis_content",
                pattern_name=f"crisis_{i}",
                matched_text=m.group(0),
                detail=f"Crisis keyword detected: {m.group(0)!r}",
            ))
            # Crisis does NOT set blocking=True

    for name, pattern in _HALLUCINATED_ID_PATTERNS:
        m = pattern.search(text)
        if m:
            flags.append(ScanFlag(
                category="hallucinated_id",
                pattern_name=name,
                matched_text=m.group(0),
                detail=f"Hallucinated identifier pattern '{name}' matched: {m.group(0)!r}",
            ))
            blocking = True

    return ScanResult(passed=not blocking, flags=flags)


def scanner_summary() -> dict[str, int]:
    """Return counts of configured scanners for the doctor check."""
    return {
        "input_injection": len(_INJECTION_PATTERNS),
        "input_ban": len(_BAN_SUBSTRINGS),
        "output_pii": len(_PII_PATTERNS),
        "output_medical": len(_MEDICAL_ADVICE_PATTERNS),
        "output_crisis": len(_CRISIS_PATTERNS),
        "output_hallucinated_id": len(_HALLUCINATED_ID_PATTERNS),
    }
