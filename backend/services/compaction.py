"""Auto-compaction for long conversations.

When prompt_tokens reaches 85% of ctx_max, older messages are summarized
via the LLM and marked compacted_at. The summary replaces them in future
inference calls while the originals remain visible (collapsed) in the UI.
"""

import json
import logging
import uuid
from datetime import timezone

import httpx

from db import get_pool
from services.crypto import decrypt_column
from services.provider_client import build_headers, resolve_bundled_chat_provider

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD = 0.85
TAIL_TURNS = 4  # keep newest N user+assistant turn pairs
SUMMARY_TIMEOUT = 60.0

SUMMARY_SYSTEM_PROMPT = (
    "Summarize the following conversation for context continuity. "
    "Preserve: key medical facts, test results mentioned, dates discussed, "
    "decisions made, and action items. Be concise but complete."
)


async def maybe_compact(chat_id: uuid.UUID, prompt_tokens: int | None, ctx_max: int | None) -> bool:
    """Check whether compaction is needed and run it if so.

    Returns True if compaction was performed, False otherwise.
    Best-effort: failures log and return False, never raise.
    """
    if not prompt_tokens or not ctx_max or ctx_max <= 0:
        return False
    if prompt_tokens / ctx_max < COMPACTION_THRESHOLD:
        return False
    try:
        return await _run_compaction(chat_id)
    except Exception as exc:
        logger.error("compaction failed for chat_id=%s: %s", chat_id, exc)
        return False


async def _run_compaction(chat_id: uuid.UUID) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, role, content FROM messages "
            "WHERE chat_id = $1::uuid AND compacted_at IS NULL "
            "ORDER BY created_at ASC, id ASC",
            chat_id,
        )
        min_messages = TAIL_TURNS * 2 + 2  # need at least tail + something to summarize
        if len(rows) < min_messages:
            return False

        tail_count = TAIL_TURNS * 2
        head = rows[:-tail_count]

        head_lines = []
        for r in head:
            plain = decrypt_column(r["content"], str(r["id"]))
            head_lines.append(f"[{r['role']}]: {plain}")
        head_text = "\n".join(head_lines)

        chat = await conn.fetchrow(
            "SELECT pruning_summary FROM chats WHERE id = $1::uuid", chat_id
        )
        existing_summary = chat["pruning_summary"] if chat else None

        summary = await _generate_summary(head_text, existing_summary)
        if not summary:
            return False

        head_ids = [r["id"] for r in head]
        await conn.execute(
            "UPDATE messages SET compacted_at = NOW() WHERE id = ANY($1::uuid[])",
            head_ids,
        )
        await conn.execute(
            "UPDATE chats SET pruning_summary = $2, updated_at = NOW() WHERE id = $1::uuid",
            chat_id, summary,
        )
        logger.info(
            "compaction: chat_id=%s, compacted %d messages, kept %d tail messages",
            chat_id, len(head), tail_count,
        )
        return True


async def _generate_summary(conversation_text: str, existing_summary: str | None) -> str | None:
    binding = await resolve_bundled_chat_provider()
    if binding is None:
        logger.info("compaction: no bundled chat provider available; skipping summary")
        return None
    provider, model = binding

    prompt_parts = []
    if existing_summary:
        prompt_parts.append(f"Previous conversation summary:\n{existing_summary}\n")
    prompt_parts.append(f"Conversation to summarize:\n{conversation_text}")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    try:
        async with httpx.AsyncClient(timeout=SUMMARY_TIMEOUT) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.error("compaction summary LLM call failed: %s", exc)
        return None
