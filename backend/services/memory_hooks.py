"""Memory hook registration and background extraction.

Provides PostToolUse callbacks for memory operations and the background
extraction entry point called from inference_job.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.hooks import HookContext, register
from services.memory.engine import get_engine
from services.memory_extraction import extract_from_exchange

logger = logging.getLogger(__name__)

_EXTRACTION_MIN_TEXT_LENGTH = 40
"""Minimum combined text length to trigger background extraction."""

# Module-level debounce dict: at most one pending extraction task per workspace.
_pending_extraction: dict[str, asyncio.Task] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Signal detection (pure-Python regex, no external deps)
# ──────────────────────────────────────────────────────────────────────────────


def _detect_correction(text: str) -> bool:
    """Return True if text contains a correction signal."""
    patterns = [
        r"\b(no,?\s+that'?s?\s+(wrong|incorrect|not right))\b",
        r"\b(actually,?\s+it'?s?)\b",
        r"\b(i\s+said|i\s+meant)\b",
        r"\bplease\s+(fix|correct|update)\b",
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _detect_reinforcement(text: str) -> bool:
    """Return True if text reinforces a prior fact."""
    patterns = [
        r"\b(yes,?\s+that'?s?\s+(right|correct))\b",
        r"\b(exactly|precisely|confirmed)\b",
        r"\b(still|continue\s+to|remain)\b",
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


# ──────────────────────────────────────────────────────────────────────────────
# Hook callbacks
# ──────────────────────────────────────────────────────────────────────────────


async def _post_tool_memory_hook(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any,
    ctx: HookContext,
    duration_ms: float,
) -> None:
    """PostToolUse callback that logs memory operations and triggers
    lightweight metadata enrichment on ``manage_memory`` calls."""
    if tool_name not in ("manage_memory", "search_memory"):
        return

    action = tool_input.get("action", "create")
    content = (tool_input.get("content") or "")[:120]

    logger.debug(
        "memory_hook: %s %s (%.2fms) chat=%s user=%s",
        tool_name,
        action,
        duration_ms,
        ctx.chat_id or "?",
        ctx.user_id or "?",
    )

    # For manage_memory "create" with substantial content, add a short
    # audit trail via the daily tier.
    if tool_name == "manage_memory" and action == "create" and len(content) > 20:
        try:
            engine = get_engine()
            engine.daily.append(
                entry_text=(
                    f"**Agent memory created** ({content[:80]}…)"
                ),
                reason="agent_tool",
                user_id=ctx.user_id,
            )
        except Exception as exc:
            logger.warning("memory_hook: daily append skipped: %s", exc)

    # For search_memory, log the query for future analytics
    if tool_name == "search_memory":
        query = (tool_input.get("query") or "")[:120]
        logger.info(
            "memory_hook: search query=%r limit=%s (%.2fms)",
            query,
            tool_input.get("limit", 10),
            duration_ms,
        )


def register_memory_hooks() -> None:
    """Register PostToolUse and Stop hooks for memory operations.

    Call this once at application startup (e.g. in ``main.py`` lifespan).
    Safe to call multiple times -- callbacks are append-only but
    registering duplicates is harmless for these lightweight hooks.
    """
    register("post_tool_execution", _post_tool_memory_hook)
    logger.info("memory_tools: registered PostToolUse memory hook")


# ──────────────────────────────────────────────────────────────────────────────
# Background extraction + debounce
# ──────────────────────────────────────────────────────────────────────────────


async def run_background_extraction(
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
    *,
    workspace_id: str | None = None,
    pool: Any | None = None,
    signal_type: str | None = None,
    provider_is_bundled: bool = True,
) -> list[dict[str, Any]]:
    """Convenience entry point called from inference_job.py post-completion.

    Skips extraction when text is too short (avoids wasting inference
    tokens on trivial exchanges).

    When workspace_id and pool are provided, acquired facts are written to
    workspace_patient_profile in Postgres (dual-write: the SQLite CoreTier
    write in extract_from_exchange continues unchanged -- do NOT remove
    eng.manage() from memory_extraction.py; the CoreTier path must stay).

    Returns the list of extracted facts (empty if nothing extracted).
    """
    combined = (user_message_text or "") + (assistant_text or "")
    if len(combined.strip()) < _EXTRACTION_MIN_TEXT_LENGTH:
        return []

    try:
        facts = await extract_from_exchange(
            user_text=user_message_text,
            assistant_text=assistant_text,
            provider=provider,
            model=model,
            provider_is_bundled=provider_is_bundled,
        )
    except Exception as exc:
        logger.warning(
            "run_background_extraction: extract_from_exchange failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []

    if workspace_id and pool and facts:
        from services.patient_profile import (
            get_profile,
            apply_fact_updates,
            resolve_conflicts,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        new_facts = [
            {
                "id": str(uuid4()),
                "content": f["content"],
                "category": f.get("category", "context"),
                "confidence": f.get("confidence", 0.5),
                "source": "extraction",
                "signal_type": signal_type,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            for f in facts
        ]
        try:
            # Phase 1: read settings and current profile; release connection before
            # the LLM call so we do not hold a pool connection across a 30s network op.
            conflict_enabled = None
            current_profile = None
            async with pool.acquire() as conn:
                conflict_enabled = await conn.fetchval(
                    "SELECT value FROM global_settings "
                    "WHERE key = 'memory_conflict_resolution_enabled'"
                )
                if conflict_enabled == "true":
                    current_profile = await get_profile(conn, workspace_id)
            # Phase 2: LLM conflict-resolution call (no DB connection held).
            # Skip when the provider is external: resolve_conflicts sends raw
            # patient facts (names, diagnoses, meds, doses) to the LLM.
            # On a bundled/local provider it stays on-box and is safe to run.
            if conflict_enabled == "true" and current_profile is not None and provider_is_bundled:
                to_add, to_remove = await resolve_conflicts(
                    current_profile, new_facts, provider, model
                )
            elif conflict_enabled == "true" and not provider_is_bundled:
                logger.info(
                    "run_background_extraction: skipping conflict-resolution "
                    "for external provider (raw patient facts would leave the box)"
                )
                to_add, to_remove = new_facts, []
            else:
                to_add, to_remove = new_facts, []
            # Phase 3: write results; re-acquire connection.
            async with pool.acquire() as conn:
                await apply_fact_updates(conn, workspace_id, to_add, to_remove)
        except Exception as exc:
            logger.warning(
                "run_background_extraction: Postgres profile write failed: %s: %s",
                type(exc).__name__,
                exc,
            )

    return facts


async def schedule_extraction(
    workspace_id: str,
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
    pool: Any,
    *,
    debounce_seconds: float = 10.0,
    signal_type: str | None = None,
    provider_is_bundled: bool = True,
) -> None:
    """Cancel any pending extraction for this workspace and reschedule.

    V2 fix: signal_type is an explicit keyword-only param here so the call
    site in inference_job.py can pass signal_type=_signal without a TypeError.
    It is threaded through _delayed() into run_background_extraction.

    The identity check in _on_done prevents the following race: if task A is
    cancelled and task B is already stored under the same workspace_id, task
    A's done_callback fires after B is stored -- without the identity check it
    would pop B's reference, leaving B unreferenced and eligible for GC before
    the sleep completes.
    """
    if not workspace_id:
        return  # workspace-less chat; skip silently

    existing = _pending_extraction.get(workspace_id)
    if existing and not existing.done():
        existing.cancel()

    async def _delayed() -> None:
        await asyncio.sleep(debounce_seconds)
        await run_background_extraction(
            user_message_text=user_message_text,
            assistant_text=assistant_text,
            provider=provider,
            model=model,
            workspace_id=workspace_id,
            pool=pool,
            signal_type=signal_type,
            provider_is_bundled=provider_is_bundled,
        )

    task = asyncio.create_task(_delayed(), name=f"mem_extract_{workspace_id}")
    _pending_extraction[workspace_id] = task

    def _on_done(t: asyncio.Task) -> None:
        # Identity check: only pop if the stored task is still this exact task.
        # Prevents the cancelled-old-task callback from popping the replacement.
        if _pending_extraction.get(workspace_id) is t:
            _pending_extraction.pop(workspace_id, None)

    task.add_done_callback(_on_done)
