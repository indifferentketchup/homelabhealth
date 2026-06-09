"""Analytics endpoints: token usage, tool costs, provider comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from db import get_pool
from deps import get_principal

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _serialize_row(r) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain JSON-safe dict."""
    out = dict(r)
    for k, v in out.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
    return out


@router.get("/tokens")
async def get_token_analytics(
    principal: dict[str, Any] = Depends(get_principal),
):
    """Aggregate token usage across sessions, per-model, and per-provider."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ── Summary ──────────────────────────────────────────────────────
        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT chat_id)::int AS chat_count,
                COUNT(*)::int               AS message_count,
                COALESCE(SUM(tokens_used), 0)::int          AS total_tokens,
                COALESCE(SUM(prompt_tokens), 0)::int         AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0)::int     AS total_completion_tokens
            FROM messages
            """,
        )

        # ── Session usage (per-chat aggregate) ───────────────────────────
        sessions = await conn.fetch(
            """
            SELECT
                c.id,
                c.title,
                c.model                       AS chat_model,
                c.created_at                  AS chat_created_at,
                COUNT(m.id)::int              AS message_count,
                COALESCE(SUM(m.tokens_used), 0)::int          AS total_tokens,
                COALESCE(SUM(m.prompt_tokens), 0)::int         AS total_prompt_tokens,
                COALESCE(SUM(m.completion_tokens), 0)::int     AS total_completion_tokens,
                MAX(m.created_at)             AS last_message_at
            FROM chats c
            LEFT JOIN messages m ON m.chat_id = c.id
            GROUP BY c.id, c.title, c.model, c.created_at
            ORDER BY MAX(m.created_at) DESC NULLS LAST
            LIMIT 100
            """,
        )

        # ── Tool / model costs ──────────────────────────────────────────
        models = await conn.fetch(
            """
            SELECT
                COALESCE(m.model, 'unknown') AS model,
                COUNT(*)::int                AS message_count,
                COALESCE(SUM(m.tokens_used), 0)::int          AS total_tokens,
                COALESCE(SUM(m.prompt_tokens), 0)::int         AS total_prompt_tokens,
                COALESCE(SUM(m.completion_tokens), 0)::int     AS total_completion_tokens
            FROM messages m
            WHERE m.model IS NOT NULL
            GROUP BY m.model
            ORDER BY total_tokens DESC
            """,
        )

        # ── Provider comparison ─────────────────────────────────────────
        providers = await conn.fetch(
            """
            SELECT
                COALESCE(p.name, 'bundled (default)') AS provider_name,
                p.is_bundled,
                COUNT(m.id)::int                      AS message_count,
                COALESCE(SUM(m.tokens_used), 0)::int  AS total_tokens,
                COALESCE(SUM(m.prompt_tokens), 0)::int AS total_prompt_tokens,
                COALESCE(SUM(m.completion_tokens), 0)::int AS total_completion_tokens
            FROM messages m
            JOIN chats c ON c.id = m.chat_id
            LEFT JOIN workspaces w ON w.id = c.workspace_id
            LEFT JOIN providers p ON p.id = w.provider_id
            WHERE m.model IS NOT NULL
            GROUP BY p.name, p.is_bundled
            ORDER BY total_tokens DESC
            """,
        )

    return {
        "summary": _serialize_row(summary) if summary else {},
        "sessions": [_serialize_row(r) for r in sessions],
        "models": [_serialize_row(r) for r in models],
        "providers": [_serialize_row(r) for r in providers],
    }
