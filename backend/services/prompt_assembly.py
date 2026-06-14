"""Prompt assembly and inference streaming helpers.

Extracted from routers/chats.py to invert the dependency direction:
services must not import from routers. Callers (routers/chats.py,
routers/history.py, services/inference_job.py, scripts/verify_safeguards_assembler.py)
all import from here instead.

Functions exported:
  _assembled_system_prompt  -- builds the full system prompt (RAG + instructions + profile)
  _stream_inference         -- SSE streaming wrapper for /v1/chat/completions
  _openai_short_chat_title  -- non-streaming auto-title via LLM
  _first_auto_memory_sentence -- extracts a memory snippet from assistant text
  _normalize_messages_for_inference -- merges consecutive same-role turns
  _clean_auto_title         -- strips quotes/padding from a raw title string
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

import asyncpg
import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigger phrases for auto-memory extraction
# ---------------------------------------------------------------------------

_AUTO_MEMORY_TRIGGERS = (
    "remember that",
    "note that",
    "don't forget",
    "dont forget",
    "keep in mind",
)


def _first_auto_memory_sentence(text: str) -> str | None:
    """Return the sentence containing the first auto-memory trigger, or None."""
    if not text or not text.strip():
        return None
    lower = text.lower()
    best: int | None = None
    for trig in _AUTO_MEMORY_TRIGGERS:
        i = lower.find(trig)
        if i != -1 and (best is None or i < best):
            best = i
    if best is None:
        return None
    idx = best
    s = text
    start = 0
    for i in range(min(idx, max(len(s) - 1, 0)), -1, -1):
        if i < 0:
            break
        c = s[i]
        if c in ".!?\n":
            start = i + 1
            while start < len(s) and s[start] in " \t":
                start += 1
            break
    end = len(s)
    for j in range(idx, len(s)):
        c = s[j]
        if c in ".!?":
            end = j + 1
            break
        if c == "\n":
            end = j
            break
    snippet = s[start:end].strip()
    return snippet or None


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------

def _clean_auto_title(raw: str) -> str:
    t = (raw or "").strip()
    while len(t) >= 2 and t[0] in "\"'" and t[0] == t[-1]:
        t = t[1:-1].strip()
    return (t.strip(" \"'") or "")[:60]


async def _openai_short_chat_title(
    provider: object, model: str, text: str | None = None, *, user_message_text: str | None = None
) -> str | None:
    """Non-streaming title via OpenAI-compatible /v1/chat/completions; returns None on failure.

    Accepts `text` positionally (callers in chats.py/inference_job.py) or
    `user_message_text` as a keyword argument (callers in history.py).
    """
    from services.provider_client import async_llm_call, Provider
    from services.reasoning_strip import strip_thinking_text

    content = text if text is not None else user_message_text
    excerpt = (content or "")[:300]
    prompt = (
        "Generate a short chat title (4-6 words, no punctuation, no quotes) summarizing "
        f"this assistant response: {excerpt}"
    )
    raw = await async_llm_call(
        provider,  # type: ignore[arg-type]
        model,
        [{"role": "user", "content": prompt}],
        max_tokens=48,
        timeout_s=30.0,
    )
    if not raw:
        return None
    stripped = strip_thinking_text(raw)
    cleaned = _clean_auto_title(stripped)
    logger.info("auto-title: raw=%r cleaned=%r", raw[:80], cleaned)
    return cleaned or None


# ---------------------------------------------------------------------------
# Message normalization
# ---------------------------------------------------------------------------

def _normalize_messages_for_inference(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge consecutive same-role turns for strict user/assistant templates (MedGemma jinja).

    Retries after a failed inference can leave multiple user rows in a row; llama.cpp's
    peg-native template rejects that with a 400.
    """
    merged: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role == "system":
            if merged and merged[-1]["role"] == "system":
                merged[-1]["content"] = f"{merged[-1]['content']}\n\n{content}".strip()
            else:
                merged.append({"role": "system", "content": content})
            continue
        if role not in ("user", "assistant"):
            continue
        if not content:
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] = f"{merged[-1]['content']}\n\n{content}".strip()
        else:
            merged.append({"role": role, "content": content})

    first_body = next((i for i, m in enumerate(merged) if m["role"] != "system"), None)
    if first_body is not None and merged[first_body]["role"] == "assistant":
        merged.insert(first_body, {"role": "user", "content": "Continue from the prior context."})

    return merged


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Streaming inference
# ---------------------------------------------------------------------------

async def _stream_inference(
    provider: object,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[bytes]:
    from services.provider_client import build_headers, Provider
    from services.reasoning_strip import ThinkingStreamFilter

    messages = _normalize_messages_for_inference(messages)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    _provider: Any = provider
    logger.info("openai /v1/chat/completions provider=%s model=%s", _provider.name, model)
    filt = ThinkingStreamFilter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{_provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(_provider),
            ) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(json.dumps({"error": f"Inference error {resp.status_code}: {err}"}))
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        err = chunk.get("error")
                        if err is not None:
                            yield _sse(json.dumps({"error": str(err)}))
                            return
                        choices = chunk.get("choices")
                        if isinstance(choices, list) and len(choices) > 0:
                            delta = (choices[0] or {}).get("delta") or {}
                            # reasoning_content intentionally ignored (internal planning).
                            piece = delta.get("content") or ""
                            if piece:
                                for out in filt.feed(piece):
                                    yield _sse(json.dumps({"content": out}))
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    for out in filt.flush():
        yield _sse(json.dumps({"content": out}))
    yield _sse("[DONE]")


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

async def _assembled_system_prompt(
    conn: asyncpg.Connection,
    chat: asyncpg.Record,
    *,
    user_query_for_rag: str | None = None,
    include_site_private: bool = True,
) -> tuple[str, dict[str, int] | None, str]:
    """Workspace prompt + workspace instructions + semantic memory facts -> context files -> custom instructions -> RAG -> mode_memory.

    Returns (assembled_system_prompt, sse_rag_meta, rag_block).
    rag_block is the raw RAG context text (empty string when no RAG context was retrieved).

    Accepts either an asyncpg.Record or a plain dict for `chat`; accesses
    fields via [] which works for both (duck-typing intentional -- do not
    tighten this type annotation).
    """
    from services.rag import retrieve_context, retrieve_memory_facts
    from services.crypto import decrypt_column
    from services.safeguards import prepend_safeguard

    # Deferred to avoid a circular import: patient_profile imports asyncpg
    # types that transitively pull in db.py, which is also imported by the
    # routers; keeping this import deferred keeps the module graph acyclic.
    # Once patient_profile.py is confirmed to have no path back to this
    # module, this can be promoted to a top-level import.
    from services.patient_profile import get_profile, format_profile_for_injection

    workspace_id = chat["workspace_id"]
    workspace_prompt = ""
    parts: list[str] = []
    if workspace_id is not None:
        try:
            ws = await conn.fetchrow(
                "SELECT system_prompt, rag_mode FROM workspaces WHERE id = $1::uuid",
                workspace_id,
            )
            if ws:
                workspace_prompt = (ws["system_prompt"] or "").strip()
        except Exception as exc:
            logger.warning("_assembled_system_prompt: workspace prompt fetch failed: %s", exc)
            parts.append("# [workspace_prompt unavailable]")

    workspace_instr_count = 0
    mem_entries_count = 0
    rag_context_chars = 0

    if workspace_prompt:
        parts.append(workspace_prompt)

    if workspace_id:
        try:
            workspace_instructions = await conn.fetch(
                "SELECT content AS instruction FROM workspace_instructions WHERE workspace_id = $1::uuid ORDER BY created_at",
                workspace_id,
            )
            if workspace_instructions:
                workspace_instr_count = len(workspace_instructions)
                instr_text = "\n".join([f"- {r['instruction']}" for r in workspace_instructions])
                parts.append(f"### Workspace Instructions\n{instr_text}")
        except Exception as exc:
            logger.warning("_assembled_system_prompt: workspace instructions fetch failed: %s", exc)
            parts.append("# [workspace_instructions unavailable]")

        try:
            workspace_mem_rows = await conn.fetch(
                "SELECT content FROM workspace_memory WHERE workspace_id = $1::uuid ORDER BY created_at ASC",
                workspace_id,
            )
            if workspace_mem_rows:
                mem_lines = "\n".join(f"- {r['content']}" for r in workspace_mem_rows)
                parts.append(f"[Workspace Memory]\n{mem_lines}")
        except Exception as exc:
            logger.warning("_assembled_system_prompt: workspace memory fetch failed: %s", exc)
            parts.append("# [workspace_memory unavailable]")

        # Patient profile injection (C1c).
        # Injected here: after workspace_memory, unconditionally (no similarity gate).
        # This placement is before the retrieve_memory_facts RAG block so the structured
        # profile always lands before similarity-gated content.
        try:
            _budget_str = await conn.fetchval(
                "SELECT value FROM global_settings WHERE key = 'memory_injection_token_budget'"
            )
            _budget = int(_budget_str or "1500")
            _profile = await get_profile(conn, workspace_id)
            _profile_text = format_profile_for_injection(_profile, _budget)
            if _profile_text:
                parts.append(f"### Patient Profile\n{_profile_text}")
        except Exception as exc:
            logger.warning("_assembled_system_prompt: patient profile fetch failed: %s", exc)

    if workspace_id is not None and include_site_private and user_query_for_rag:
        try:
            memory_facts = await retrieve_memory_facts(str(user_query_for_rag), conn)
            if memory_facts:
                mem_entries_count = len(memory_facts)
                bullets = "\n".join([f"- {f}" for f in memory_facts])
                parts.append(f"### Relevant Context\n{bullets}")
        except Exception as exc:
            logger.warning("_assembled_system_prompt: memory facts retrieval failed: %s", exc)
            parts.append("# [memory_facts unavailable]")

    if workspace_id is not None:
        try:
            cf_rows = await conn.fetch(
                """
                SELECT filename, content FROM workspace_context_files
                WHERE workspace_id = $1::uuid
                ORDER BY sort_order ASC NULLS LAST, created_at ASC
                """,
                workspace_id,
            )
            for cf in cf_rows:
                parts.append(f"[Context file: {cf['filename']}]\n{cf['content']}")
        except Exception as exc:
            logger.warning("_assembled_system_prompt: context files fetch failed: %s", exc)
            parts.append("# [context_files unavailable]")

    if include_site_private:
        try:
            ci_rows = await conn.fetch(
                """
                SELECT id, content FROM custom_instructions
                WHERE content IS NOT NULL
                """,
            )
            _ci_parts: list[str] = []
            for _ci in ci_rows:
                _ci_plain = decrypt_column(_ci["content"] or "", str(_ci["id"])).strip()
                if _ci_plain:
                    _ci_parts.append(_ci_plain)
            custom_instr = "\n\n".join(_ci_parts)
            if custom_instr:
                parts.append(custom_instr)
        except Exception as exc:
            logger.warning("_assembled_system_prompt: custom instructions fetch failed: %s", exc)
            parts.append("# [custom_instructions unavailable]")

    # V5 fix: initialize rag_block before the rag_ok guard so it is always bound
    # (the actual assignment inside `if source_ids:` is conditional).
    rag_block = ""
    rag_ok = (
        bool(user_query_for_rag and str(user_query_for_rag).strip())
        and workspace_id is not None
        and chat.get("rag_enabled") is not False
    )
    sse_rag_meta: dict[str, int] | None = None
    if rag_ok:
        cid = chat.get("id")
        if cid is not None:
            sel = await conn.fetch(
                "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
                cid,
            )
            # Attached sources ("send to chat") are prioritized, but RAG always
            # searches every embedded source in the workspace so the model can
            # read anything the user references -- not just what's attached.
            priority_ids = [str(r["source_id"]) for r in sel]
            workspace_sources = await conn.fetch(
                "SELECT id FROM sources WHERE workspace_id = $1::uuid AND embedding_status = 'complete'",
                uuid.UUID(str(workspace_id)),
            )
            source_ids = [str(r["id"]) for r in workspace_sources]
            # Defensive union: keep attached sources searchable even if they fall
            # outside the workspace 'complete' set for any reason.
            for pid in priority_ids:
                if pid not in source_ids:
                    source_ids.append(pid)
            if source_ids:
                rag_block, rag_n = await retrieve_context(
                    str(user_query_for_rag).strip(),
                    source_ids,
                    priority_source_ids=priority_ids,
                )
                if rag_block:
                    parts.append(rag_block)
                    rag_context_chars = len(rag_block)
                    sse_rag_meta = {"count": rag_n, "chars": rag_context_chars}

    assembled = "\n\n".join(parts)

    mem_text = ""
    if workspace_id is not None and include_site_private:
        mem = await conn.fetchrow("SELECT content FROM mode_memory LIMIT 1")
        mem_text = (mem["content"] or "").strip() if mem else ""
        if mem_text:
            if len(mem_text) > 2000:
                mem_text = mem_text[:2000] + "\n[truncated]"
            block = "## What I know about you:\n" + mem_text
            assembled = f"{assembled}\n\n{block}" if assembled else block

    preview = (assembled[:2000] + "...") if len(assembled) > 2000 else assembled
    logger.debug(
        "assembled prompt workspace_id=%s is_workspace_chat=%s len=%d workspace_instruction_rows=%d "
        "memory_entry_rows=%d mode_memory_len=%d rag_context_chars=%d preview=%s",
        str(workspace_id) if workspace_id else None,
        workspace_id is not None,
        len(assembled),
        workspace_instr_count,
        mem_entries_count,
        len(mem_text),
        rag_context_chars,
        preview,
    )
    logger.debug("assembled prompt full text=%s", assembled)

    # B0 safeguards: prepend the locked tiered-refusal prompt as the final
    # step. Chokepoint -- no code path returns from this function without it.
    # Workspace prompt + RAG appear after, never before. See
    # services/safeguards.py for the prompt text + version key.
    assembled = prepend_safeguard(assembled)

    return assembled, sse_rag_meta, rag_block
