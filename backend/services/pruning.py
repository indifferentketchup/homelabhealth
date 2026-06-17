"""Summarize-and-compress chat history when message count exceeds threshold.

Inference is routed via the chat's workspace provider (resolved per call).
No env-var URL / API_KEY / DEFAULT_MODEL fallbacks  -  if the workspace has no
provider configured, summarization silently no-ops (same as any other
upstream failure).
"""

from __future__ import annotations

import logging
import asyncpg
from fastapi import HTTPException

from db import get_pool
from services.crypto import decrypt_column
from services.provider_client import resolve_provider_for_workspace
from services.reasoning_strip import strip_thinking_text
from services.summarization import (
    build_preserved_facts_block,
    extract_medical_facts,
    summarize_transcript,
)

logger = logging.getLogger(__name__)


async def _get_setting(conn: asyncpg.Connection, key: str, default: str) -> str:
    row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = $1",
        key,
    )
    return row["value"] if row else default




async def summarize_and_compress(
    chat_id: str,
    pool: asyncpg.Pool | None = None,
) -> None:
    """If message_count >= threshold, summarize and delete old turns."""
    own_pool = pool is None
    if own_pool:
        pool = await get_pool()

    async with pool.acquire() as conn:
        threshold_s = await _get_setting(conn, "pruning_threshold", "40")
        try:
            threshold = int(threshold_s)
        except ValueError:
            threshold = 40

        chat = await conn.fetchrow(
            """
            SELECT id, workspace_id, pruning_summary, message_count
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None:
            return

        count_row = await conn.fetchrow(
            "SELECT COUNT(*)::int AS c FROM messages WHERE chat_id = $1::uuid AND compacted_at IS NULL",
            chat_id,
        )
        actual = count_row["c"] if count_row else 0

        rows = await conn.fetch(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE chat_id = $1::uuid AND compacted_at IS NULL
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

        if actual < threshold:
            if chat["message_count"] != actual:
                await conn.execute(
                    "UPDATE chats SET message_count = $2, updated_at = NOW() WHERE id = $1::uuid",
                    chat_id,
                    actual,
                )
            return

        if len(rows) <= 10:
            return

        to_prune = rows[:-10]
        keep_ids = [r["id"] for r in rows[-10:]]

        # Decrypt message content before building the summarization input so
        # the LLM sees real text when HLH_MASTER_KEY column encryption is active.
        transcript = "\n\n".join(
            f"{r['role'].upper()}: {decrypt_column(r['content'], str(r['id']))}"
            for r in to_prune
        )
        prev = chat["pruning_summary"] or ""

        # Resolve provider via the chat's workspace. If unconfigured, skip
        # silently -- pruning is best-effort and shouldn't fail the user's send.
        workspace_id = chat["workspace_id"]
        if workspace_id is None:
            return
        try:
            provider, model = await resolve_provider_for_workspace(workspace_id)
        except HTTPException as e:
            logger.info("pruning skipped chat_id=%s: %s", chat_id, e.detail)
            return

        raw_summary = await summarize_transcript(
            provider,
            model,
            transcript,
            existing_summary=prev or None,
            temperature=0.3,
            max_tokens=1024,
            timeout_s=120.0,
        )
        summary = strip_thinking_text(raw_summary) if raw_summary else ""

        if not summary:
            return

        # Reuse the already-decrypted transcript for fact extraction.
        facts = extract_medical_facts(transcript)
        if facts:
            summary = summary + build_preserved_facts_block(facts)

        prune_ids = [r["id"] for r in to_prune]
        await conn.execute(
            "DELETE FROM messages WHERE chat_id = $1::uuid AND id = ANY($2::uuid[])",
            chat_id,
            prune_ids,
        )
        new_count = len(keep_ids)
        await conn.execute(
            """
            UPDATE chats
            SET pruning_summary = $2,
                message_count = $3,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            chat_id,
            summary,
            new_count,
        )
