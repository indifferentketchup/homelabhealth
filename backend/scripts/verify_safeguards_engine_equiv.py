"""Equivalence check for the safeguards engine.

Pins the observable output of services.safeguards_engine against a baseline
captured 2026-06-15 (before the engine was trimmed from 1129 lines). For each
probe query it asserts:
  - the set of matched rule conditions,
  - whether _build_engine_safeguard returns the full prompt or contextual directives
    (the SET of directive lines; order is not asserted because the pre-change engine
    emitted them in nondeterministic set-iteration order),
  - whether should_request_approval fires.

Pure in-process, no DB. Run from backend/:
    python3 scripts/verify_safeguards_engine_equiv.py

Exit 0 = output identical to baseline. Non-zero = drift (the regression signal).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.safeguards import (  # noqa: E402
    SAFEGUARD_SYSTEM_PROMPT,
    _build_engine_safeguard,
)
from services.approval_gate import should_request_approval  # noqa: E402
from services.safeguards_engine import get_engine  # noqa: E402

# (matched_conditions sorted, is_full_prompt, directives_text, needs_approval)
BASELINE: dict[str, dict] = {
    "what does my diagnosis mean for the chest x-ray finding": {
        "matched": ["user asks for diagnosis"],
        "full": False,
        "directives": "## Safeguards (contextual)\n[HIGH] • explain findings, state limits, recommend clinician",
        "approval": True,
    },
    "can you explain what this medication does": {
        "matched": ["user asks about medication", "user asks medication combinations"],
        "full": False,
        "directives": "## Safeguards (contextual)\n[HIGH] • general info only, point to pharmacist\n• explain general interactions, direct to pharmacist",
        "approval": True,
    },
    "is it safe to take ibuprofen with my warfarin medication combinations": {
        "matched": ["user asks about medication", "user asks medication combinations"],
        "full": False,
        "directives": "## Safeguards (contextual)\n[HIGH] • general info only, point to pharmacist\n• explain general interactions, direct to pharmacist",
        "approval": True,
    },
    "I have severe chest pain and trouble breathing emergency": {
        "matched": [],
        "full": True,
        "directives": "",
        "approval": False,
    },
    "I want to end my life, self-harm": {
        "matched": ["user expresses self-harm"],
        "full": True,
        "directives": "",
        "approval": True,
    },
    "what is the capital of france": {
        "matched": [],
        "full": True,
        "directives": "",
        "approval": False,
    },
    "explain my cholesterol numbers please": {
        "matched": [],
        "full": True,
        "directives": "",
        "approval": False,
    },
    "diagnosis and medication question together": {
        "matched": ["user asks for diagnosis"],
        "full": False,
        "directives": "## Safeguards (contextual)\n[HIGH] • explain findings, state limits, recommend clinician",
        "approval": True,
    },
}


def run() -> int:
    eng = get_engine()
    failures: list[str] = []

    for query, expected in BASELINE.items():
        eng.clear_cache()
        matches = eng.evaluate(query)

        matched = sorted(m.guideline.content.condition for m in matches)
        safeguard = _build_engine_safeguard(matches)
        is_full = safeguard == SAFEGUARD_SYSTEM_PROMPT
        directives = "" if is_full else safeguard.split(SAFEGUARD_SYSTEM_PROMPT)[0].strip()
        # Compare directive lines as an order-independent set (see module docstring).
        directive_lines = sorted(ln for ln in directives.splitlines() if ln.strip())
        expected_lines = sorted(ln for ln in expected["directives"].splitlines() if ln.strip())
        needs_approval = should_request_approval(matches)[0] if matches else False

        if matched != expected["matched"]:
            failures.append(f"[{query}] matched: expected {expected['matched']}, got {matched}")
        if is_full != expected["full"]:
            failures.append(f"[{query}] is_full_prompt: expected {expected['full']}, got {is_full}")
        if directive_lines != expected_lines:
            failures.append(
                f"[{query}] directives mismatch:\n  expected: {expected_lines!r}\n  got:      {directive_lines!r}"
            )
        if needs_approval != expected["approval"]:
            failures.append(f"[{query}] needs_approval: expected {expected['approval']}, got {needs_approval}")

        if not any(query in f for f in failures):
            print(f"✓ {query[:60]}")

    if failures:
        print("\nFAILURES:")
        print("\n".join(failures))
        return 1
    print(f"\nAll {len(BASELINE)} safeguards-engine equivalence checks PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
