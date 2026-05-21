"""Summarize-and-compress chat history when message count exceeds threshold.

Inference is routed via the chat's workspace provider (resolved per call).
No env-var URL / API_KEY / DEFAULT_MODEL fallbacks — if the workspace has no
provider configured, summarization silently no-ops (same as any other
upstream failure).
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
import httpx
from fastapi import HTTPException

from db import get_pool
from services.provider_client import build_headers, resolve_provider_for_workspace

logger = logging.getLogger(__name__)


async def _get_setting(conn: asyncpg.Connection, key: str, default: str) -> str:
    row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = $1",
        key,
    )
    return row["value"] if row else default


async def _openai_summarize(
    base_url: str,
    headers: dict[str, str],
    model: str,
    text: str,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Summarize the following conversation turns into a concise bullet summary "
                    "that preserves facts, decisions, and open questions. "
                    "Do not address the user; output summary only.\n\n"
                    f"{text}"
                ),
            }
        ],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


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
            "SELECT COUNT(*)::int AS c FROM messages WHERE chat_id = $1::uuid",
            chat_id,
        )
        actual = count_row["c"] if count_row else 0

        rows = await conn.fetch(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE chat_id = $1::uuid
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

        transcript = "\n\n".join(
            f"{r['role'].upper()}: {r['content']}" for r in to_prune
        )
        prev = chat["pruning_summary"] or ""
        bundle = f"Previous summary:\n{prev}\n\nMessages to compress:\n{transcript}" if prev else transcript

        # Resolve provider via the chat's workspace. If unconfigured, skip
        # silently — pruning is best-effort and shouldn't fail the user's send.
        workspace_id = chat["workspace_id"]
        if workspace_id is None:
            return
        try:
            provider, model = await resolve_provider_for_workspace(workspace_id)
        except HTTPException as e:
            logger.info("pruning skipped chat_id=%s: %s", chat_id, e.detail)
            return
        try:
            summary = await _openai_summarize(
                provider.base_url, build_headers(provider), model, bundle
            )
        except Exception as e:
            logger.warning("pruning summarize failed chat_id=%s: %s", chat_id, e)
            return

        if not summary:
            return

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
