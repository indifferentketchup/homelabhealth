"""Memory hook registration and background extraction.

Provides PostToolUse callbacks for memory operations and the background
extraction entry point called from inference_job.py.
"""

from __future__ import annotations

import logging
from typing import Any

from services.hooks import HookContext, register
from services.memory.engine import get_engine
from services.memory_extraction import extract_from_exchange

logger = logging.getLogger(__name__)

_EXTRACTION_MIN_TEXT_LENGTH = 40
"""Minimum combined text length to trigger background extraction."""


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
                    f"**Agent memory created** ({content[:80]}\u2026)"
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
    Safe to call multiple times — callbacks are append-only but
    registering duplicates is harmless for these lightweight hooks.
    """
    register("post_tool_execution", _post_tool_memory_hook)
    logger.info("memory_tools: registered PostToolUse memory hook")


async def run_background_extraction(
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
) -> list[dict[str, Any]]:
    """Convenience entry point called from inference_job.py post-completion.

    Skips extraction when text is too short (avoids wasting inference
    tokens on trivial exchanges).

    Returns the list of extracted facts (empty if nothing extracted).
    """
    combined = (user_message_text or "") + (assistant_text or "")
    if len(combined.strip()) < _EXTRACTION_MIN_TEXT_LENGTH:
        return []

    try:
        return await extract_from_exchange(
            user_text=user_message_text,
            assistant_text=assistant_text,
            provider=provider,
            model=model,
        )
    except Exception as exc:
        logger.warning(
            "run_background_extraction: failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []
