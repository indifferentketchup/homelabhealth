"""Chat CRUD, message listing, and streaming sends (Ollama or Claude)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, AsyncIterator

import asyncpg
import httpx
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth_deps import (
    assert_daw_usable,
    assert_persona_usable,
    get_principal,
    principal_can_access_chat,
)
from db import get_pool
from services.pruning import summarize_and_compress
from services.searx import searx_search_sources

router = APIRouter()
logger = logging.getLogger(__name__)


async def _default_persona_id_for_mode(conn: asyncpg.Connection, mode: str) -> uuid.UUID | None:
    """Default persona for new chat: global personas table + per-app default flags."""
    m = mode if mode in ("booops", "808notes") else "booops"
    if m == "808notes":
        return await conn.fetchval(
            "SELECT id FROM personas WHERE is_default_808notes IS TRUE LIMIT 1",
        )
    return await conn.fetchval(
        "SELECT id FROM personas WHERE is_default_booops IS TRUE LIMIT 1",
    )


async def _global_context_window(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = 'context_window_global'",
    )
    if row and row["value"]:
        try:
            v = int(row["value"])
            return max(1024, min(32768, v))
        except ValueError:
            pass
    return 16384


async def _global_ollama_inference_defaults(conn: asyncpg.Connection) -> dict[str, float | int]:
    keys = ("temperature_global", "top_p_global", "top_k_global", "max_tokens_global")
    rows = await conn.fetch(
        "SELECT key, value FROM global_settings WHERE key = ANY($1::text[])",
        list(keys),
    )
    m = {r["key"]: r["value"] for r in rows}

    def _temp(v: str | None) -> float:
        if not v:
            return 0.7
        try:
            return float(max(0.0, min(2.0, float(v))))
        except ValueError:
            return 0.7

    def _top_p(v: str | None) -> float:
        if not v:
            return 1.0
        try:
            return float(max(0.0, min(1.0, float(v))))
        except ValueError:
            return 1.0

    def _top_k(v: str | None) -> int:
        if not v:
            return 20
        try:
            return int(max(1, min(100, int(v))))
        except ValueError:
            return 20

    def _max_t(v: str | None) -> int:
        if not v:
            return 2048
        try:
            return int(max(256, min(8192, int(v))))
        except ValueError:
            return 2048

    return {
        "temperature": _temp(m.get("temperature_global")),
        "top_p": _top_p(m.get("top_p_global")),
        "top_k": _top_k(m.get("top_k_global")),
        "max_tokens": _max_t(m.get("max_tokens_global")),
    }


_AUTO_MEMORY_TRIGGERS = (
    "remember that",
    "note that",
    "don't forget",
    "dont forget",
    "keep in mind",
)


def _first_auto_memory_sentence(text: str) -> str | None:
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


async def _site_default_model(conn: asyncpg.Connection, mode: str) -> str:
    key = "default_model_808notes" if mode == "808notes" else "default_model"
    row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", key)
    if row and row["value"]:
        v = str(row["value"]).strip()
        if v:
            return v
    return (os.environ.get("DEFAULT_MODEL", "qwen3.5:9b") or "qwen3.5:9b").strip()


async def _bump_message_cap_or_429(conn: asyncpg.Connection, principal: dict[str, Any]) -> None:
    if principal["kind"] == "owner":
        return
    if principal["kind"] == "guest":
        ip = principal["ip"]
        row = await conn.fetchrow(
            """
            INSERT INTO guest_message_counts (ip, count, last_seen)
            VALUES ($1, 1, NOW())
            ON CONFLICT (ip) DO UPDATE SET
                count = guest_message_counts.count + 1,
                last_seen = EXCLUDED.last_seen
            WHERE guest_message_counts.count < 20
            RETURNING count
            """,
            ip,
        )
        if row is None:
            raise HTTPException(status_code=429, detail="guest_limit_reached")
        return
    uid = principal["user_id"]
    row = await conn.fetchrow(
        """
        INSERT INTO member_message_counts (user_id, date, count)
        VALUES ($1::uuid, CURRENT_DATE, 1)
        ON CONFLICT (user_id, date) DO UPDATE SET
            count = member_message_counts.count + 1
        WHERE member_message_counts.count < 200
        RETURNING count
        """,
        uid,
    )
    if row is None:
        raise HTTPException(status_code=429, detail="member_daily_limit_reached")


async def _assembled_system_prompt(
    conn: asyncpg.Connection,
    chat: asyncpg.Record,
    *,
    user_query_for_rag: str | None = None,
    effective_context_window: int | None = None,
    include_site_private: bool = True,
) -> str:
    """Persona → DAW prompt + daw_instructions + memory_entries → context files → custom instructions → RAG → mode_memory."""
    mode = chat["mode"] if chat["mode"] in ("booops", "808notes") else "booops"
    pid = chat["persona_id"]
    daw_id = chat["daw_id"]
    daw_prompt = ""
    daw_persona_id = None
    if daw_id is not None:
        ws = await conn.fetchrow(
            "SELECT system_prompt, persona_id FROM daws WHERE id = $1::uuid",
            daw_id,
        )
        if ws:
            daw_prompt = (ws["system_prompt"] or "").strip()
            daw_persona_id = ws["persona_id"]

    resolve_pid = pid if pid is not None else daw_persona_id

    persona_prompt = ""
    if resolve_pid is not None:
        pr = await conn.fetchrow(
            "SELECT system_prompt FROM personas WHERE id = $1::uuid",
            resolve_pid,
        )
        if pr:
            persona_prompt = (pr["system_prompt"] or "").strip()

    if not persona_prompt:
        if mode == "808notes":
            d = await conn.fetchrow(
                "SELECT system_prompt FROM personas WHERE is_default_808notes IS TRUE LIMIT 1",
            )
        else:
            d = await conn.fetchrow(
                "SELECT system_prompt FROM personas WHERE is_default_booops IS TRUE LIMIT 1",
            )
        if d:
            persona_prompt = (d["system_prompt"] or "").strip()

    parts: list[str] = []
    daw_instr_count = 0
    mem_entries_count = 0
    rag_context_chars = 0

    if persona_prompt:
        parts.append(persona_prompt)
    if daw_prompt:
        parts.append(daw_prompt)

    if daw_id:
        daw_instructions = await conn.fetch(
            "SELECT content AS instruction FROM daw_instructions WHERE daw_id = $1::uuid ORDER BY created_at",
            daw_id,
        )
        if daw_instructions:
            daw_instr_count = len(daw_instructions)
            instr_text = "\n".join([f"- {r['instruction']}" for r in daw_instructions])
            parts.append(f"### DAW Instructions\n{instr_text}")

    memory_entries: list[Any] = []
    if include_site_private:
        memory_entries = await conn.fetch(
            "SELECT content AS fact FROM memory_entries WHERE mode = $1 AND is_deleted = false ORDER BY created_at",
            mode,
        )
    if memory_entries:
        mem_entries_count = len(memory_entries)
        bullets = "\n".join([f"- {e['fact']}" for e in memory_entries])
        parts.append(f"### Remembered Facts\n{bullets}")

    if daw_id is not None:
        cf_rows = await conn.fetch(
            """
            SELECT filename, content FROM daw_context_files
            WHERE daw_id = $1::uuid
            ORDER BY sort_order ASC NULLS LAST, created_at ASC
            """,
            daw_id,
        )
        for cf in cf_rows:
            parts.append(f"[Context file: {cf['filename']}]\n{cf['content']}")

    if include_site_private:
        ci_rows = await conn.fetch(
            """
            SELECT scope, content FROM custom_instructions
            WHERE scope IN ('global', $1::text) AND btrim(content) <> ''
            ORDER BY CASE WHEN scope = 'global' THEN 0 ELSE 1 END, scope ASC
            """,
            mode,
        )
        custom_instr = "\n\n".join(
            (r["content"] or "").strip() for r in ci_rows if (r["content"] or "").strip()
        )
        if custom_instr:
            parts.append(custom_instr)

    rag_ok = (
        mode == "808notes"
        and bool(user_query_for_rag and str(user_query_for_rag).strip())
        and daw_id is not None
        and chat.get("rag_enabled") is not False
    )
    if rag_ok:
        cid = chat.get("id")
        if cid is not None:
            sel = await conn.fetch(
                "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
                cid,
            )
            source_ids = [str(r["source_id"]) for r in sel]
            if source_ids:
                from services.rag import retrieve_context

                rag_block = await retrieve_context(
                    str(user_query_for_rag).strip(),
                    str(daw_id),
                    source_ids,
                )
                if rag_block:
                    parts.append(rag_block)
                    rag_context_chars = len(rag_block)

    assembled = "\n\n".join(parts)

    if include_site_private:
        mem = await conn.fetchrow("SELECT content FROM mode_memory WHERE mode = $1", mode)
        mem_text = (mem["content"] or "").strip() if mem else ""
        if mem_text:
            block = "## What I know about you:\n" + mem_text
            assembled = f"{assembled}\n\n{block}" if assembled else block
    else:
        mem_text = ""

    preview = (assembled[:2000] + "…") if len(assembled) > 2000 else assembled
    logger.info(
        "assembled prompt mode=%s daw_id=%s len=%d daw_instruction_rows=%d "
        "memory_entry_rows=%d mode_memory_len=%d rag_context_chars=%d "
        "context_window=%s preview=%s",
        mode,
        str(daw_id) if daw_id else None,
        len(assembled),
        daw_instr_count,
        mem_entries_count,
        len(mem_text),
        rag_context_chars,
        effective_context_window,
        preview,
    )
    logger.debug("assembled prompt full text=%s", assembled)

    return assembled


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _clean_auto_title(raw: str) -> str:
    t = (raw or "").strip()
    while len(t) >= 2 and t[0] in "\"'" and t[0] == t[-1]:
        t = t[1:-1].strip()
    return (t.strip(" \"'") or "")[:60]


async def _ollama_short_chat_title(model: str, user_message_text: str) -> str | None:
    """Non-streaming title via Ollama; returns None on failure."""
    base = _ollama_base()
    excerpt = (user_message_text or "")[:300]
    prompt = (
        "Generate a short chat title (4-6 words, no punctuation, no quotes) for a conversation "
        f"that starts with this message: {excerpt}"
    )
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.post(f"{base}/api/chat", json=payload)
            if r.status_code >= 400:
                return None
            data = r.json()
            msg = data.get("message") or {}
            raw = (msg.get("content") or "").strip()
            cleaned = _clean_auto_title(raw)
            return cleaned or None
    except Exception:
        return None


async def _anthropic_short_chat_title(user_message_text: str) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    excerpt = (user_message_text or "")[:300]
    title_model = (os.environ.get("ANTHROPIC_TITLE_MODEL") or "").strip() or _resolve_claude_model(
        "claude-haiku"
    )
    prompt = (
        "Generate a short chat title (4-6 words, no punctuation, no quotes) for a conversation "
        f"that starts with this message: {excerpt}"
    )
    try:
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=title_model,
            max_tokens=48,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    raw = "".join(parts).strip()
    cleaned = _clean_auto_title(raw)
    return cleaned or None


async def _ai_short_chat_title(model: str, user_message_text: str) -> str | None:
    if _is_claude_model(model):
        return await _anthropic_short_chat_title(user_message_text)
    return await _ollama_short_chat_title(model, user_message_text)


CLAUDE_ALIASES: dict[str, str] = {
    "claude-sonnet": "claude-sonnet-4-20250514",
    "claude-haiku": "claude-3-5-haiku-20241022",
    "claude-opus": "claude-3-opus-20240229",
}


def _is_claude_model(model: str) -> bool:
    m = (model or "").strip().lower()
    if m in CLAUDE_ALIASES:
        return True
    if m.startswith("claude-"):
        return True
    return False


def _resolve_claude_model(model: str) -> str:
    key = (model or "").strip().lower()
    if key in CLAUDE_ALIASES:
        env_key = {
            "claude-sonnet": "ANTHROPIC_MODEL_SONNET",
            "claude-haiku": "ANTHROPIC_MODEL_HAIKU",
            "claude-opus": "ANTHROPIC_MODEL_OPUS",
        }[key]
        return os.environ.get(env_key) or CLAUDE_ALIASES[key]
    return model.strip()


def _split_system_for_claude(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    rest: list[dict[str, str]] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            rest.append(m)
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest


async def _stream_ollama(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    top_p: float = 1.0,
    top_k: int = 20,
    num_ctx: int = 8192,
) -> AsyncIterator[bytes]:
    base = _ollama_base()
    opts: dict[str, Any] = {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "num_ctx": int(num_ctx),
        "num_predict": int(max_tokens),
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": opts,
    }
    logger.info(
        "ollama /api/chat model=%s temperature=%s max_tokens=%s top_p=%s top_k=%s num_ctx=%s",
        model,
        temperature,
        max_tokens,
        top_p,
        top_k,
        num_ctx,
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(json.dumps({"error": f"Ollama error {resp.status_code}: {err}"}))
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        yield _sse(json.dumps({"error": str(chunk["error"])}))
                        return
                    msg = chunk.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        yield _sse(json.dumps({"content": piece}))
                    if chunk.get("done"):
                        break
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Ollama request failed: {e}"}))
        return
    yield _sse("[DONE]")


async def _stream_claude(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 1.0,
    max_tokens: int = 4096,
    top_p: float = 1.0,
) -> AsyncIterator[bytes]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield _sse(json.dumps({"error": "ANTHROPIC_API_KEY is not configured"}))
        return
    resolved = _resolve_claude_model(model)
    system, api_messages = _split_system_for_claude(messages)
    client = AsyncAnthropic(api_key=api_key)
    try:
        mt = max(1, min(8192, int(max_tokens)))
        kwargs: dict[str, Any] = {
            "model": resolved,
            "max_tokens": mt,
            "messages": api_messages,
            "temperature": temperature,
            "top_p": max(0.0, min(1.0, float(top_p))),
        }
        if system:
            kwargs["system"] = system
        logger.info(
            "claude messages.stream model=%s temperature=%s max_tokens=%s top_p=%s",
            resolved,
            temperature,
            mt,
            top_p,
        )
        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield _sse(json.dumps({"content": text}))
    except Exception as e:
        yield _sse(json.dumps({"error": str(e)}))
        return
    yield _sse("[DONE]")


class ChatCreate(BaseModel):
    title: str | None = None
    model: str | None = Field(default=None)
    daw_id: uuid.UUID | None = None
    mode: str = "booops"
    web_search_enabled: bool | None = None
    persona_id: uuid.UUID | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    web_search_enabled: bool | None = None
    persona_id: uuid.UUID | None = None
    daw_id: uuid.UUID | None = None


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    model: str | None = None


class WebSearchToggleBody(BaseModel):
    enabled: bool


class SourceSelectionBody(BaseModel):
    source_ids: list[uuid.UUID] = Field(default_factory=list)


def _chat_row(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "daw_id": str(r["daw_id"]) if r["daw_id"] else None,
        "mode": r["mode"],
        "persona_id": str(r["persona_id"]) if r["persona_id"] else None,
        "model": r["model"],
        "web_search_enabled": r["web_search_enabled"],
        "rag_enabled": r["rag_enabled"],
        "pruning_summary": r["pruning_summary"],
        "message_count": r["message_count"],
        "is_main_chat": r["is_main_chat"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _message_row(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "chat_id": str(r["chat_id"]),
        "role": r["role"],
        "content": r["content"],
        "model": r["model"],
        "tokens_used": r["tokens_used"],
        "sources_used": r["sources_used"],
        "forked_from": str(r["forked_from"]) if r["forked_from"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.post("/")
async def create_chat(body: ChatCreate, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    mode = body.mode if body.mode in ("booops", "808notes") else "booops"
    default_model = os.environ.get("DEFAULT_MODEL", "qwen3.5:9b")
    if principal["kind"] == "owner":
        owner_id, guest_ip = None, None
    elif principal["kind"] == "member":
        owner_id, guest_ip = principal["user_id"], None
    else:
        owner_id, guest_ip = None, principal["ip"]
    async with pool.acquire() as conn:
        await assert_persona_usable(conn, principal, body.persona_id)
        await assert_daw_usable(conn, principal, body.daw_id)
        persona_id_for_insert = body.persona_id
        if persona_id_for_insert is None:
            persona_id_for_insert = await _default_persona_id_for_mode(conn, mode)
        model_arg = body.model
        if principal["kind"] != "owner":
            model_arg = await _site_default_model(conn, mode)
        row = await conn.fetchrow(
            """
            INSERT INTO chats (title, daw_id, mode, model, web_search_enabled, persona_id, owner_id, guest_ip)
            VALUES ($1, $2, $3,
                COALESCE($4, (
                    SELECT value FROM global_settings WHERE key = (
                        CASE WHEN $3::text = '808notes' THEN 'default_model_808notes' ELSE 'default_model' END
                    ) LIMIT 1
                ), $6),
                COALESCE($5, FALSE),
                $7,
                $8,
                $9)
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            body.title,
            body.daw_id,
            mode,
            model_arg,
            body.web_search_enabled,
            default_model,
            persona_id_for_insert,
            owner_id,
            guest_ip,
        )
    return _chat_row(row)


@router.get("/")
async def list_chats(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = Query("booops"),
    daw_id: uuid.UUID | None = Query(None, description="When set, only chats for this DAW workspace."),
    principal: dict[str, Any] = Depends(get_principal),
):
    if principal["kind"] == "guest":
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    pool = await get_pool()
    m = mode if mode in ("booops", "808notes") else "booops"
    cols = """
                id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
    """
    async with pool.acquire() as conn:
        if principal["kind"] == "owner":
            scope = "owner_id IS NULL AND guest_ip IS NULL"
            if daw_id is not None:
                rows = await conn.fetch(
                    f"""
                    SELECT {cols}
                    FROM chats
                    WHERE mode = $3 AND daw_id = $4::uuid AND {scope}
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                    m,
                    daw_id,
                )
                total = await conn.fetchval(
                    f"SELECT COUNT(*)::int FROM chats WHERE mode = $1 AND daw_id = $2::uuid AND {scope}",
                    m,
                    daw_id,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT {cols}
                    FROM chats
                    WHERE mode = $3 AND {scope}
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                    m,
                )
                total = await conn.fetchval(
                    f"SELECT COUNT(*)::int FROM chats WHERE mode = $1 AND {scope}",
                    m,
                )
        else:
            uid = principal["user_id"]
            if daw_id is not None:
                rows = await conn.fetch(
                    f"""
                    SELECT {cols}
                    FROM chats
                    WHERE mode = $3 AND daw_id = $4::uuid AND owner_id = $5::uuid
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                    m,
                    daw_id,
                    uid,
                )
                total = await conn.fetchval(
                    "SELECT COUNT(*)::int FROM chats WHERE mode = $1 AND daw_id = $2::uuid AND owner_id = $3::uuid",
                    m,
                    daw_id,
                    uid,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT {cols}
                    FROM chats
                    WHERE mode = $3 AND owner_id = $4::uuid
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                    m,
                    uid,
                )
                total = await conn.fetchval(
                    "SELECT COUNT(*)::int FROM chats WHERE mode = $1 AND owner_id = $2::uuid",
                    m,
                    uid,
                )
    return {"items": [_chat_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/non-daw")
async def delete_non_daw_chats(
    mode: str = Query("booops"),
    principal: dict[str, Any] = Depends(get_principal),
):
    """Delete all chats in the given mode that are not tied to a DAW (daw_id IS NULL)."""
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    m = mode if mode in ("booops", "808notes") else "booops"
    async with pool.acquire() as conn:
        if principal["kind"] == "owner":
            deleted = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM chats
                    WHERE mode = $1 AND daw_id IS NULL AND owner_id IS NULL AND guest_ip IS NULL
                    RETURNING 1
                )
                SELECT COUNT(*)::int FROM deleted
                """,
                m,
            )
        else:
            deleted = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM chats
                    WHERE mode = $1 AND daw_id IS NULL AND owner_id = $2::uuid
                    RETURNING 1
                )
                SELECT COUNT(*)::int FROM deleted
                """,
                m,
                principal["user_id"],
            )
    return {"deleted": int(deleted or 0), "mode": m}


@router.get("/{chat_id}")
async def get_chat(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at,
                owner_id, guest_ip
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
    if row is None or not principal_can_access_chat(principal, row):
        raise HTTPException(status_code=404, detail="Chat not found")
    return _chat_row(row)


@router.patch("/{chat_id}/web-search")
async def patch_web_search(
    chat_id: uuid.UUID,
    body: WebSearchToggleBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id, owner_id, guest_ip FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None or not principal_can_access_chat(principal, cur):
            raise HTTPException(status_code=404, detail="Chat not found")
        row = await conn.fetchrow(
            """
            UPDATE chats
            SET web_search_enabled = $2, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING web_search_enabled
            """,
            chat_id,
            body.enabled,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"web_search_enabled": bool(row["web_search_enabled"])}


@router.get("/{chat_id}/source-selection")
async def get_source_selection(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id, owner_id, guest_ip FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None or not principal_can_access_chat(principal, c):
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = await conn.fetch(
            "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
            chat_id,
        )
    return {"chat_id": str(chat_id), "source_ids": [str(r["source_id"]) for r in rows]}


@router.put("/{chat_id}/source-selection")
async def put_source_selection(
    chat_id: uuid.UUID,
    body: SourceSelectionBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id, owner_id, guest_ip FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None or not principal_can_access_chat(principal, c):
            raise HTTPException(status_code=404, detail="Chat not found")
        for sid in body.source_ids:
            ok = await conn.fetchval("SELECT 1 FROM sources WHERE id = $1::uuid", sid)
            if ok is None:
                raise HTTPException(status_code=400, detail=f"Unknown source_id {sid}")
        async with conn.transaction():
            await conn.execute("DELETE FROM chat_source_selections WHERE chat_id = $1::uuid", chat_id)
            for sid in body.source_ids:
                await conn.execute(
                    """
                    INSERT INTO chat_source_selections (chat_id, source_id)
                    VALUES ($1::uuid, $2::uuid)
                    """,
                    chat_id,
                    sid,
                )
    return {"chat_id": str(chat_id), "source_ids": [str(s) for s in body.source_ids]}


@router.patch("/{chat_id}")
async def patch_chat(
    chat_id: uuid.UUID,
    body: ChatPatch,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    if principal["kind"] != "owner" and "model" in data:
        del data["model"]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at,
                owner_id, guest_ip
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if row is None or not principal_can_access_chat(principal, row):
            raise HTTPException(status_code=404, detail="Chat not found")
        if not data:
            return _chat_row(row)
        new_title = data.get("title", row["title"])
        new_model = data.get("model", row["model"])
        new_ws = data.get("web_search_enabled", row["web_search_enabled"])
        new_persona = row["persona_id"] if "persona_id" not in data else data["persona_id"]
        new_daw = row["daw_id"] if "daw_id" not in data else data["daw_id"]

        if new_persona is not None:
            await assert_persona_usable(conn, principal, new_persona)
        if new_daw is not None:
            await assert_daw_usable(conn, principal, new_daw)

        updated = await conn.fetchrow(
            """
            UPDATE chats
            SET title = $2, model = $3, web_search_enabled = $4,
                persona_id = $5, daw_id = $6, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            chat_id,
            new_title,
            new_model,
            new_ws,
            new_persona,
            new_daw,
        )
    return _chat_row(updated)


@router.delete("/{chat_id}")
async def delete_chat(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id, owner_id, guest_ip FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None or not principal_can_access_chat(principal, cur):
            raise HTTPException(status_code=404, detail="Chat not found")
        result = await conn.execute("DELETE FROM chats WHERE id = $1::uuid", chat_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"ok": True}


@router.get("/{chat_id}/messages")
async def list_messages(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id, owner_id, guest_ip FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None or not principal_can_access_chat(principal, c):
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = await conn.fetch(
            """
            SELECT id, chat_id, role, content, model, tokens_used, sources_used, forked_from, created_at
            FROM messages
            WHERE chat_id = $1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )
    return {"items": [_message_row(r) for r in rows]}


@router.post("/{chat_id}/messages/{message_id}/fork")
async def fork_chat_at_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            src = await conn.fetchrow(
                """
                SELECT id, title, mode, model, persona_id, daw_id,
                    web_search_enabled, rag_enabled, owner_id, guest_ip
                FROM chats
                WHERE id = $1::uuid
                """,
                chat_id,
            )
            if src is None or not principal_can_access_chat(principal, src):
                raise HTTPException(status_code=404, detail="Chat not found")

            target = await conn.fetchrow(
                """
                SELECT id FROM messages
                WHERE id = $1::uuid AND chat_id = $2::uuid
                """,
                message_id,
                chat_id,
            )
            if target is None:
                raise HTTPException(status_code=400, detail="Message does not belong to this chat")

            msg_rows = await conn.fetch(
                """
                SELECT id, role, content, model, tokens_used, sources_used
                FROM messages
                WHERE chat_id = $1::uuid
                ORDER BY created_at ASC, id ASC
                """,
                chat_id,
            )
            copies: list[Any] = []
            for r in msg_rows:
                copies.append(r)
                if r["id"] == message_id:
                    break
            else:
                raise HTTPException(status_code=400, detail="Message not found in chat history")

            base_title = ((src["title"] or "") or "chat").strip() or "chat"
            fork_title = ("Fork of " + base_title)[:80]

            new_chat = await conn.fetchrow(
                """
                INSERT INTO chats (
                    title, daw_id, mode, model, persona_id,
                    web_search_enabled, rag_enabled, message_count,
                    owner_id, guest_ip
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                    pruning_summary, message_count, is_main_chat, created_at, updated_at
                """,
                fork_title,
                src["daw_id"],
                src["mode"],
                src["model"],
                src["persona_id"],
                src["web_search_enabled"],
                src["rag_enabled"],
                len(copies),
                src["owner_id"],
                src["guest_ip"],
            )
            assert new_chat is not None
            new_id = new_chat["id"]

            for r in copies:
                mid = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO messages (
                        id, chat_id, role, content, model, tokens_used, sources_used, forked_from
                    )
                    VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid
                    )
                    """,
                    mid,
                    new_id,
                    r["role"],
                    r["content"],
                    r["model"],
                    r["tokens_used"],
                    r["sources_used"],
                    r["id"],
                )

    return _chat_row(new_chat)


@router.post("/{chat_id}/messages")
async def append_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            """
            SELECT id, title, model, pruning_summary, mode, persona_id, web_search_enabled, daw_id,
                message_count, rag_enabled, owner_id, guest_ip
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None or not principal_can_access_chat(principal, chat):
            raise HTTPException(status_code=404, detail="Chat not found")

        global_ctx = await _global_context_window(conn)
        ollama_global_inf = await _global_ollama_inference_defaults(conn)
        daw_row = None
        if chat["daw_id"] is not None:
            daw_row = await conn.fetchrow(
                """
                SELECT model, max_tokens, top_p, top_k, context_window, temperature
                FROM daws WHERE id = $1::uuid
                """,
                chat["daw_id"],
            )
        cm = chat["mode"] if chat["mode"] in ("booops", "808notes") else "booops"
        if principal["kind"] == "owner":
            daw_pins_model = bool(
                daw_row is not None and daw_row["model"] and str(daw_row["model"]).strip()
            )
            chat_model = (body.model or chat["model"] or "").strip()
            effective_model = str(daw_row["model"]).strip() if daw_pins_model else chat_model
        else:
            daw_pins_model = False
            effective_model = (await _site_default_model(conn, cm)).strip()
        if not effective_model:
            raise HTTPException(status_code=400, detail="No model set for chat")

        if principal["kind"] == "owner":
            if daw_pins_model:
                await conn.execute(
                    "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                    chat_id,
                    effective_model,
                )
            elif body.model is not None:
                await conn.execute(
                    "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                    chat_id,
                    effective_model,
                )

        if daw_pins_model and daw_row is not None:
            effective_ctx = int(daw_row["context_window"] or 8192)
        else:
            effective_ctx = global_ctx

        if _is_claude_model(effective_model):
            if daw_pins_model and daw_row is not None:
                effective_max_tokens = int(daw_row["max_tokens"] or 2048)
                effective_top_p = float(daw_row["top_p"] if daw_row["top_p"] is not None else 1.0)
                effective_top_k = int(daw_row["top_k"] if daw_row["top_k"] is not None else 20)
            else:
                effective_max_tokens = 2048
                effective_top_p = 1.0
                effective_top_k = 20
            inference_temperature = 0.7
            if daw_row is not None and daw_row["temperature"] is not None:
                inference_temperature = float(daw_row["temperature"])
        else:
            effective_max_tokens = int(ollama_global_inf["max_tokens"])
            effective_top_p = float(ollama_global_inf["top_p"])
            effective_top_k = int(ollama_global_inf["top_k"])
            inference_temperature = float(ollama_global_inf["temperature"])
            if daw_row is not None:
                if daw_row["max_tokens"] is not None:
                    effective_max_tokens = int(daw_row["max_tokens"])
                if daw_row["top_p"] is not None:
                    effective_top_p = float(daw_row["top_p"])
                if daw_row["top_k"] is not None:
                    effective_top_k = int(daw_row["top_k"])
                if daw_row["temperature"] is not None:
                    inference_temperature = float(daw_row["temperature"])

        include_private = principal["kind"] == "owner"
        first_exchange_for_auto_title = int(chat["message_count"] or 0) == 0

        user_msg_id = uuid.uuid4()
        async with conn.transaction():
            await _bump_message_cap_or_429(conn, principal)
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model)
                VALUES ($1::uuid, $2::uuid, 'user', $3, $4)
                """,
                user_msg_id,
                chat_id,
                body.content.strip(),
                effective_model,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )

        msg_rows = await conn.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id = $1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

        assembled = await _assembled_system_prompt(
            conn,
            chat,
            user_query_for_rag=body.content.strip(),
            effective_context_window=effective_ctx,
            include_site_private=include_private,
        )

    summary = chat["pruning_summary"]
    user_message_text = body.content.strip()

    async def gen() -> AsyncIterator[bytes]:
        sources_list: list[dict[str, str]] = []
        extra_search = ""
        if bool(chat["web_search_enabled"]):
            sources_list, extra_search = await searx_search_sources(
                user_message_text,
                mode=str(chat["mode"] or "booops"),
            )
        if sources_list:
            yield _sse(json.dumps({"type": "search_sources", "sources": sources_list}))

        api_messages: list[dict[str, str]] = []
        system_blocks: list[str] = []
        if assembled:
            system_blocks.append(assembled)
        if summary:
            system_blocks.append("Compressed prior conversation summary:\n" + summary)
        if extra_search:
            system_blocks.append(
                "## Web search results (use if relevant; the user enabled web search for this turn):\n" + extra_search
            )
        if system_blocks:
            api_messages.append({"role": "system", "content": "\n\n".join(system_blocks)})
        for r in msg_rows:
            role = r["role"]
            if role not in ("user", "assistant", "system"):
                continue
            api_messages.append({"role": role, "content": r["content"] or ""})

        full: list[str] = []
        had_error = False
        if _is_claude_model(effective_model):
            claude_t = max(0.0, min(1.0, inference_temperature))
            logger.info(
                "chat inference chat_id=%s model=%s daw_id=%s context_window=%s max_tokens=%s top_p=%s "
                "temperature_daw=%s temperature_claude=%s",
                str(chat_id),
                effective_model,
                str(chat["daw_id"]) if chat["daw_id"] else None,
                effective_ctx,
                effective_max_tokens,
                effective_top_p,
                inference_temperature,
                claude_t,
            )
            stream = _stream_claude(
                effective_model,
                api_messages,
                temperature=claude_t,
                max_tokens=effective_max_tokens,
                top_p=effective_top_p,
            )
        else:
            logger.info(
                "chat inference chat_id=%s model=%s daw_id=%s context_window=%s max_tokens=%s top_p=%s top_k=%s temperature=%s",
                str(chat_id),
                effective_model,
                str(chat["daw_id"]) if chat["daw_id"] else None,
                effective_ctx,
                effective_max_tokens,
                effective_top_p,
                effective_top_k,
                inference_temperature,
            )
            stream = _stream_ollama(
                effective_model,
                api_messages,
                temperature=inference_temperature,
                max_tokens=effective_max_tokens,
                top_p=effective_top_p,
                top_k=effective_top_k,
                num_ctx=effective_ctx,
            )
        try:
            async for chunk in stream:
                try:
                    line = chunk.decode("utf-8")
                except Exception:
                    yield chunk
                    continue
                payload_end = ""
                if line.startswith("data: "):
                    payload_end = line[6:].strip()
                defer_done = payload_end == "[DONE]"
                if not defer_done:
                    yield chunk
                if not line.startswith("data: "):
                    continue
                if defer_done:
                    continue
                try:
                    obj = json.loads(payload_end)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    had_error = True
                if obj.get("content"):
                    full.append(obj["content"])
        except Exception as e:
            yield _sse(json.dumps({"error": str(e)}))
            had_error = True

        if had_error:
            return

        assistant_text = "".join(full).strip()
        if not assistant_text:
            return

        assist_id = uuid.uuid4()
        p = await get_pool()
        async with p.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model)
                VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4)
                """,
                assist_id,
                chat_id,
                assistant_text,
                effective_model,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )

        title_emit: str | None = None
        has_custom_title = bool((chat["title"] or "").strip())
        if first_exchange_for_auto_title and assistant_text and not has_custom_title:
            new_title: str | None = None
            try:
                new_title = await _ai_short_chat_title(effective_model, user_message_text)
            except Exception:
                new_title = None
            if not new_title:
                first_line = (user_message_text or "").strip().split("\n")[0].strip()
                new_title = _clean_auto_title(first_line)[:60] if first_line else None
            if not new_title:
                new_title = "New chat"
            try:
                async with p.acquire() as conn_title:
                    await conn_title.execute(
                        "UPDATE chats SET title = $2, updated_at = NOW() WHERE id = $1::uuid",
                        chat_id,
                        new_title,
                    )
                title_emit = new_title
            except Exception:
                pass
        if title_emit:
            yield _sse(json.dumps({"type": "title_update", "title": title_emit}))

        auto_mem = _first_auto_memory_sentence(assistant_text)
        if auto_mem and principal["kind"] == "owner":
            chat_mode = chat["mode"] if chat["mode"] in ("booops", "808notes") else "booops"
            async with p.acquire() as conn_mem:
                await conn_mem.execute(
                    """
                    INSERT INTO memory_entries (content, source, mode)
                    VALUES ($1, 'auto', $2)
                    """,
                    auto_mem,
                    chat_mode,
                )

        await summarize_and_compress(str(chat_id), p, max_context_tokens=effective_ctx)

        yield _sse("[DONE]")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
