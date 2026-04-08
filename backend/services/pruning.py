"""Summarize-and-compress chat history when message count exceeds threshold."""

from __future__ import annotations

import json
import os
from typing import Any

import asyncpg
import httpx

from db import get_pool


async def _get_setting(conn: asyncpg.Connection, key: str, default: str) -> str:
    row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = $1",
        key,
    )
    return row["value"] if row else default


def _inference_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _openai_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("BIFROST_API_KEY") or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


async def _openai_summarize(
    model: str,
    text: str,
) -> str:
    base = _inference_base()
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "max_tokens": 1024,
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
            f"{base}/v1/chat/completions",
            json=payload,
            headers=_openai_headers(),
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


def _estimate_tokens_from_messages(rows: list[Any]) -> int:
    total_chars = 0
    for r in rows:
        total_chars += len(r["content"] or "")
    return max(total_chars // 4, 0)


async def summarize_and_compress(
    chat_id: str,
    pool: asyncpg.Pool | None = None,
    *,
    max_context_tokens: int | None = None,
) -> None:
    """If message_count >= threshold or estimated tokens exceed context, summarize and delete old turns."""
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
            SELECT id, pruning_summary, message_count
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

        est_tokens = _estimate_tokens_from_messages(rows)
        token_budget = int(max_context_tokens) if max_context_tokens and max_context_tokens > 0 else 0
        over_tokens = bool(token_budget and est_tokens > int(token_budget * 0.72))
        over_msgs = actual >= threshold

        if actual < threshold and not over_tokens:
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

        default_model = await _get_setting(conn, "default_model", "llama-gpu/qwen3.5-9b-exl3")
        try:
            summary = await _openai_summarize(default_model, bundle)
        except Exception:
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
