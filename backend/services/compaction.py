"""Auto-compaction for long conversations.

When prompt_tokens reaches 85% of ctx_max, older messages are summarized
via the LLM and marked compacted_at. The summary replaces them in future
inference calls while the originals remain visible (collapsed) in the UI.
"""

import logging
import uuid

from db import get_pool
from services.crypto import decrypt_column
from services.provider_client import resolve_bundled_chat_provider
from services.summarization import (
    build_preserved_facts_block,
    extract_medical_facts,
    summarize_transcript,
)

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD = 0.85
TAIL_TURNS = 4  # keep newest N user+assistant turn pairs
SUMMARY_TIMEOUT = 60.0

# Summary-input token budget (char/4 estimate). Sized to fit a 4096-ctx
# summarizer (the smallest bundled chat model) with room for the rolling
# summary and the generated output. When the head exceeds this, the
# lowest-weight (cheapest, lowest-signal) messages are dropped from the summary
# input while survivors stay in chronological order. Medical facts are pinned
# separately via extract_medical_facts over the FULL head, so dropping short
# messages never loses lab values, dates, or dosages. Tunable; could move to
# global_settings if a tier needs a larger window.
HEAD_SUMMARY_TOKEN_BUDGET = 2500


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

        # Decrypt head messages (already chronological) and estimate token weight
        # via a char/4 heuristic (approximation only).
        head_entries = []
        for r in head:
            plain = decrypt_column(r["content"], str(r["id"]))
            weight = max(1, len(plain) // 4)
            head_entries.append((r, plain, weight))

        # Fact pinning runs over the FULL head so no lab value, date, or dose is
        # lost even when a message is dropped from the summary input below.
        full_head_text = "\n".join(f"[{e[0]['role']}]: {e[1]}" for e in head_entries)

        # Priority-aware budget (G.2): if the head exceeds the summary token
        # budget, drop the lowest-weight messages first, then summarize the
        # survivors in chronological order. Never drop the last remaining message.
        survivors = head_entries
        total_weight = sum(e[2] for e in head_entries)
        if total_weight > HEAD_SUMMARY_TOKEN_BUDGET and len(head_entries) > 1:
            dropped: set[int] = set()
            remaining = total_weight
            for i in sorted(range(len(head_entries)), key=lambda j: head_entries[j][2]):
                if remaining <= HEAD_SUMMARY_TOKEN_BUDGET or len(dropped) >= len(head_entries) - 1:
                    break
                dropped.add(i)
                remaining -= head_entries[i][2]
            survivors = [e for i, e in enumerate(head_entries) if i not in dropped]

        head_text = "\n".join(f"[{e[0]['role']}]: {e[1]}" for e in survivors)

        chat = await conn.fetchrow(
            "SELECT pruning_summary FROM chats WHERE id = $1::uuid", chat_id
        )
        existing_summary = chat["pruning_summary"] if chat else None

        summary = await _generate_summary(head_text, existing_summary)
        if not summary:
            return False

        facts = extract_medical_facts(full_head_text)
        if facts:
            summary = summary + build_preserved_facts_block(facts)

        head_ids = [e[0]["id"] for e in head_entries]
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

    result = await summarize_transcript(
        provider,
        model,
        conversation_text,
        existing_summary=existing_summary,
        temperature=0.1,
        max_tokens=1024,
        timeout_s=SUMMARY_TIMEOUT,
    )
    if not result:
        logger.error("compaction summary LLM call failed: empty response")
        return None
    return result
