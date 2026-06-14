"""Structured patient profile: get, upsert, fact merge, conflict resolution, injection formatting.

Single-responsibility module for all workspace_patient_profile CRUD and prompt formatting.
No coupling to MemoryEngine or CoreTier.

asyncpg JSONB convention: always pass profile dict as json.dumps(profile) with ::jsonb cast.
workspace_id is accepted as str throughout the hooks layer; asyncpg ::uuid cast handles
the coercion from string UUID to PG uuid type. This is intentional -- no runtime crash.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Canonical empty profile shape
# ──────────────────────────────────────────────────────────────────────────────

EMPTY_PROFILE: dict[str, Any] = {
    "version": "1.0",
    "name": None,
    "date_of_birth": None,
    "blood_type": None,
    "active_diagnoses": [],
    "current_medications": [],
    "allergies": [],
    "primary_care_provider": None,
    "insurance": None,
    "lab_baselines": {},
    "user_context": {"summary": "", "updatedAt": ""},
    "history": {
        "recentMonths": {"summary": "", "updatedAt": ""},
        "longTermBackground": {"summary": "", "updatedAt": ""},
    },
    "facts": [],
}


# ──────────────────────────────────────────────────────────────────────────────
# Conflict-resolution prompt (not a numbered checklist per CLAUDE.md)
# ──────────────────────────────────────────────────────────────────────────────

_CONFLICT_RESOLUTION_PROMPT = """\
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
}"""


# ──────────────────────────────────────────────────────────────────────────────
# CRUD functions
# ──────────────────────────────────────────────────────────────────────────────


async def get_profile(conn, workspace_id) -> dict[str, Any]:
    """Fetch profile or return EMPTY_PROFILE copy if row absent.

    workspace_id may be str or UUID; asyncpg ::uuid cast handles the coercion.
    """
    row = await conn.fetchrow(
        "SELECT profile FROM workspace_patient_profile WHERE workspace_id = $1::uuid",
        str(workspace_id),
    )
    if row is None:
        return dict(EMPTY_PROFILE)
    raw = row["profile"]
    # asyncpg may return JSONB as str or dict depending on codec registration.
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


async def upsert_profile(conn, workspace_id, profile: dict) -> None:
    """Full-document upsert.

    Passes profile as json.dumps(profile) with ::jsonb cast per asyncpg convention.
    workspace_id may be str or UUID; asyncpg ::uuid cast handles the coercion.
    """
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO workspace_patient_profile (workspace_id, profile, updated_at)
        VALUES ($1::uuid, $2::jsonb, $3)
        ON CONFLICT (workspace_id) DO UPDATE
            SET profile = EXCLUDED.profile,
                updated_at = EXCLUDED.updated_at
        """,
        str(workspace_id),
        json.dumps(profile),
        now,
    )


async def apply_fact_updates(
    conn,
    workspace_id,
    new_facts: list[dict],
    facts_to_remove: list[str],
) -> None:
    """Merge new_facts into profile['facts'], remove by ID, upsert.

    facts_to_remove is a list of fact ID strings.
    """
    profile = await get_profile(conn, workspace_id)
    existing = profile.get("facts") or []

    # Remove by ID
    if facts_to_remove:
        remove_set = set(facts_to_remove)
        existing = [f for f in existing if f.get("id") not in remove_set]

    # Append new facts
    existing.extend(new_facts)
    profile["facts"] = existing
    await upsert_profile(conn, workspace_id, profile)


async def resolve_conflicts(
    profile: dict,
    new_facts: list[dict],
    provider: Any,
    model: str,
) -> tuple[list[dict], list[str]]:
    """LLM conflict-resolution pass. Returns (facts_to_add, ids_to_remove).

    Skips LLM call and returns append-only result if new_facts is empty.
    Falls back to (new_facts, []) on any LLM/parse failure.
    Validates returned IDs against existing profile facts to prevent
    hallucinated phantom deletes.
    """
    if not new_facts:
        return new_facts, []

    existing_facts = profile.get("facts") or []
    existing_ids = {f.get("id") for f in existing_facts if f.get("id")}

    user_message = (
        f"EXISTING FACTS:\n{json.dumps(existing_facts, indent=2)}"
        f"\n\nNEW FACTS:\n{json.dumps(new_facts, indent=2)}"
    )

    try:
        from services.provider_client import async_llm_call

        raw = await async_llm_call(
            provider,
            model,
            [
                {"role": "system", "content": _CONFLICT_RESOLUTION_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
            max_tokens=512,
            timeout_s=30.0,
        )
        if not raw:
            return new_facts, []

        # Strip markdown fences (same logic as _parse_extraction_response)
        text = raw.strip()
        if text.startswith("```"):
            start = text.find("{")
            if start != -1:
                end = text.rfind("```")
                text = text[start:end].strip() if end > start else text[start:].strip()

        result = json.loads(text)
        raw_ids_to_remove: list[str] = result.get("factsToRemove") or []
        raw_new_facts: list[dict] = result.get("newFacts") or []

        # Validate: discard hallucinated IDs not present in existing profile
        ids_to_remove = [fid for fid in raw_ids_to_remove if fid in existing_ids]
        hallucinated = len(raw_ids_to_remove) - len(ids_to_remove)
        if hallucinated:
            logger.warning(
                "resolve_conflicts: discarded %d hallucinated fact IDs", hallucinated
            )

        return raw_new_facts if raw_new_facts else new_facts, ids_to_remove

    except Exception as exc:
        logger.warning(
            "resolve_conflicts: failed (%s: %s) -- falling back to append-only",
            type(exc).__name__,
            exc,
        )
        return new_facts, []


# ──────────────────────────────────────────────────────────────────────────────
# Injection formatter (C4)
# ──────────────────────────────────────────────────────────────────────────────


def format_profile_for_injection(profile: dict, token_budget: int = 1500) -> str:
    """Render profile as prompt text. Sorted by confidence, truncated at budget.

    Token estimator: len(text) // 4 (char/4, no tiktoken dependency).
    Returns "" for empty or all-null profile.

    Injection order:
    1. Structured fields (always rendered first if non-empty).
    2. Facts sorted by confidence DESC then created_at DESC.
    3. History/user_context summaries if budget allows.
    """
    if not profile or profile == {}:
        return ""

    lines: list[str] = []
    tokens_used = 0

    def _add(line: str) -> bool:
        nonlocal tokens_used
        cost = len(line) // 4
        if tokens_used + cost > token_budget:
            return False
        lines.append(line)
        tokens_used += cost
        return True

    # 1. Structured fields
    name = profile.get("name")
    if name:
        _add(f"Name: {name}")

    dob = profile.get("date_of_birth")
    if dob:
        _add(f"Date of birth: {dob}")

    blood_type = profile.get("blood_type")
    if blood_type:
        _add(f"Blood type: {blood_type}")

    diagnoses = profile.get("active_diagnoses") or []
    if diagnoses:
        _add(f"Active diagnoses: {', '.join(str(d) for d in diagnoses)}")

    meds = profile.get("current_medications") or []
    if meds:
        _add(f"Current medications: {', '.join(str(m) for m in meds)}")

    allergies = profile.get("allergies") or []
    if allergies:
        _add(f"Allergies: {', '.join(str(a) for a in allergies)}")

    pcp = profile.get("primary_care_provider")
    if pcp:
        _add(f"Primary care provider: {pcp}")

    insurance = profile.get("insurance")
    if insurance:
        _add(f"Insurance: {insurance}")

    lab_baselines = profile.get("lab_baselines") or {}
    if lab_baselines:
        lab_str = ", ".join(f"{k}: {v}" for k, v in lab_baselines.items())
        _add(f"Lab baselines: {lab_str}")

    # 2. Facts sorted by confidence DESC, created_at DESC
    facts = profile.get("facts") or []
    if facts:
        # Sort confidence DESC, created_at DESC (newest first as tiebreaker).
        # Python sort is stable; apply secondary key first, then primary.
        sorted_facts = sorted(
            facts,
            key=lambda f: f.get("created_at") or "",
            reverse=True,
        )
        sorted_facts = sorted(
            sorted_facts,
            key=lambda f: -float(f.get("confidence") or 0.0),
        )
        for fact in sorted_facts:
            content = (fact.get("content") or "").strip()
            if not content:
                continue
            category = fact.get("category") or "other"
            line = f"- [{category}] {content}"
            if not _add(line):
                break

    # 3. History/user_context if budget allows
    user_ctx = profile.get("user_context") or {}
    uc_summary = (user_ctx.get("summary") or "").strip()
    if uc_summary:
        _add(f"Context: {uc_summary}")

    history = profile.get("history") or {}
    recent = (history.get("recentMonths") or {}).get("summary") or ""
    if recent.strip():
        _add(f"Recent history: {recent.strip()}")

    ltbg = (history.get("longTermBackground") or {}).get("summary") or ""
    if ltbg.strip():
        _add(f"Long-term background: {ltbg.strip()}")

    if not lines:
        return ""

    return "\n".join(lines)
