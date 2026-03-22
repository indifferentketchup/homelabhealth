"""Chat CRUD, message listing, and streaming sends (Ollama or Claude)."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, AsyncIterator

import asyncpg
import httpx
from anthropic import AsyncAnthropic
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import get_pool
from services.pruning import summarize_and_compress

router = APIRouter()


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


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


async def _stream_ollama(model: str, messages: list[dict[str, str]]) -> AsyncIterator[bytes]:
    base = _ollama_base()
    payload = {"model": model, "messages": messages, "stream": True}
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


async def _stream_claude(model: str, messages: list[dict[str, str]]) -> AsyncIterator[bytes]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield _sse(json.dumps({"error": "ANTHROPIC_API_KEY is not configured"}))
        return
    resolved = _resolve_claude_model(model)
    system, api_messages = _split_system_for_claude(messages)
    client = AsyncAnthropic(api_key=api_key)
    try:
        kwargs: dict[str, Any] = {
            "model": resolved,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system
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


class ChatPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    web_search_enabled: bool | None = None


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    model: str | None = None


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
async def create_chat(body: ChatCreate):
    pool = await get_pool()
    mode = body.mode if body.mode in ("booops", "808notes") else "booops"
    default_model = os.environ.get("DEFAULT_MODEL", "qwen3.5:9b")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chats (title, daw_id, mode, model, web_search_enabled)
            VALUES ($1, $2, $3,
                COALESCE($4, (SELECT value FROM global_settings WHERE key = 'default_model' LIMIT 1), $6),
                COALESCE($5, FALSE))
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            body.title,
            body.daw_id,
            mode,
            body.model,
            body.web_search_enabled,
            default_model,
        )
    return _chat_row(row)


@router.get("/")
async def list_chats(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = Query("booops"),
):
    pool = await get_pool()
    m = mode if mode in ("booops", "808notes") else "booops"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE mode = $3
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
            m,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM chats WHERE mode = $1",
            m,
        )
    return {"items": [_chat_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{chat_id}")
async def get_chat(chat_id: uuid.UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _chat_row(row)


@router.patch("/{chat_id}")
async def patch_chat(chat_id: uuid.UUID, body: ChatPatch):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        if not data:
            return _chat_row(row)
        new_title = data.get("title", row["title"])
        new_model = data.get("model", row["model"])
        new_ws = data.get("web_search_enabled", row["web_search_enabled"])
        updated = await conn.fetchrow(
            """
            UPDATE chats
            SET title = $2, model = $3, web_search_enabled = $4, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            chat_id,
            new_title,
            new_model,
            new_ws,
        )
    return _chat_row(updated)


@router.delete("/{chat_id}")
async def delete_chat(chat_id: uuid.UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM chats WHERE id = $1::uuid", chat_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"ok": True}


@router.get("/{chat_id}/messages")
async def list_messages(chat_id: uuid.UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM chats WHERE id = $1::uuid", chat_id)
        if exists is None:
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


@router.post("/{chat_id}/messages")
async def append_message(chat_id: uuid.UUID, body: MessageCreate):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            """
            SELECT id, model, pruning_summary, mode
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")

        model = (body.model or chat["model"] or "").strip()
        if not model:
            raise HTTPException(status_code=400, detail="No model set for chat")

        if body.model is not None:
            await conn.execute(
                "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                chat_id,
                model,
            )

        user_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO messages (id, chat_id, role, content, model)
            VALUES ($1::uuid, $2::uuid, 'user', $3, $4)
            """,
            user_id,
            chat_id,
            body.content.strip(),
            model,
        )
        await conn.execute(
            """
            UPDATE chats
            SET message_count = message_count + 1,
                updated_at = NOW(),
                title = COALESCE(NULLIF(title, ''), LEFT($2, 80))
            WHERE id = $1::uuid
            """,
            chat_id,
            body.content.strip(),
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

    api_messages: list[dict[str, str]] = []
    summary = chat["pruning_summary"]
    if summary:
        api_messages.append(
            {
                "role": "system",
                "content": "Compressed prior conversation summary:\n" + summary,
            }
        )
    for r in msg_rows:
        role = r["role"]
        if role not in ("user", "assistant", "system"):
            continue
        api_messages.append({"role": role, "content": r["content"] or ""})

    async def gen() -> AsyncIterator[bytes]:
        full: list[str] = []
        had_error = False
        stream = _stream_claude(model, api_messages) if _is_claude_model(model) else _stream_ollama(model, api_messages)
        try:
            async for chunk in stream:
                yield chunk
                try:
                    line = chunk.decode("utf-8")
                except Exception:
                    continue
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
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
                model,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )

        await summarize_and_compress(str(chat_id), p)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
