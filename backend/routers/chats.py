"""Chat CRUD, message listing, and streaming sends (OpenAI-compatible local inference or Claude)."""

import hashlib
import pathlib
import uuid

import json
import logging
from typing import Any, AsyncIterator

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from deps import (
    assert_workspace_usable,
    get_principal,
)
from db import get_pool
from services.audit import AuditEventHandle, AuditRecord, audit_event, insert_audit_event
from services.deid import is_enabled as deid_enabled, redact_text
from services.provider_client import (
    Provider,
    build_headers,
    resolve_provider_for_workspace,
)
from services.pruning import summarize_and_compress
from services.rag import (
    retrieve_context,
    retrieve_memory_facts,
)
from services.crypto import encrypt_column, decrypt_column
from services.safeguards import current_version, prepend_safeguard
from services.searx import searx_search_sources

router = APIRouter()
logger = logging.getLogger(__name__)


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


async def _assembled_system_prompt(
    conn: asyncpg.Connection,
    chat: asyncpg.Record,
    *,
    user_query_for_rag: str | None = None,
    include_site_private: bool = True,
) -> tuple[str, dict[str, int] | None]:
    """Workspace prompt + workspace instructions + semantic memory facts -> context files -> custom instructions -> RAG -> mode_memory."""
    workspace_id = chat["workspace_id"]
    workspace_prompt = ""
    if workspace_id is not None:
        ws = await conn.fetchrow(
            "SELECT system_prompt, rag_mode FROM workspaces WHERE id = $1::uuid",
            workspace_id,
        )
        if ws:
            workspace_prompt = (ws["system_prompt"] or "").strip()

    parts: list[str] = []
    workspace_instr_count = 0
    mem_entries_count = 0
    rag_context_chars = 0

    if workspace_prompt:
        parts.append(workspace_prompt)

    if workspace_id:
        workspace_instructions = await conn.fetch(
            "SELECT content AS instruction FROM workspace_instructions WHERE workspace_id = $1::uuid ORDER BY created_at",
            workspace_id,
        )
        if workspace_instructions:
            workspace_instr_count = len(workspace_instructions)
            instr_text = "\n".join([f"- {r['instruction']}" for r in workspace_instructions])
            parts.append(f"### Workspace Instructions\n{instr_text}")

        workspace_mem_rows = await conn.fetch(
            "SELECT content FROM workspace_memory WHERE workspace_id = $1::uuid ORDER BY created_at ASC",
            workspace_id,
        )
        if workspace_mem_rows:
            mem_lines = "\n".join(f"- {r['content']}" for r in workspace_mem_rows)
            parts.append(f"[Workspace Memory]\n{mem_lines}")

    if workspace_id is not None and include_site_private and user_query_for_rag:
        memory_facts = await retrieve_memory_facts(str(user_query_for_rag), conn)
        if memory_facts:
            mem_entries_count = len(memory_facts)
            bullets = "\n".join([f"- {f}" for f in memory_facts])
            parts.append(f"### Relevant Context\n{bullets}")

    if workspace_id is not None:
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

    if include_site_private:
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
            source_ids = [str(r["source_id"]) for r in sel]
            if not source_ids:
                workspace_sources = await conn.fetch(
                    "SELECT id FROM sources WHERE workspace_id = $1::uuid AND embedding_status = 'complete'",
                    uuid.UUID(str(workspace_id)),
                )
                source_ids = [str(r["id"]) for r in workspace_sources]
            if source_ids:
                rag_block, rag_n = await retrieve_context(
                    str(user_query_for_rag).strip(),
                    source_ids,
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

    preview = (assembled[:2000] + "…") if len(assembled) > 2000 else assembled
    logger.info(
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
    # step. Chokepoint — no code path returns from this function without it.
    # Workspace prompt + RAG appear after, never before. See
    # services/safeguards.py for the prompt text + version key.
    assembled = prepend_safeguard(assembled)

    return assembled, sse_rag_meta


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _clean_auto_title(raw: str) -> str:
    t = (raw or "").strip()
    while len(t) >= 2 and t[0] in "\"'" and t[0] == t[-1]:
        t = t[1:-1].strip()
    return (t.strip(" \"'") or "")[:60]


async def _openai_short_chat_title(
    provider: Provider, model: str, text: str
) -> str | None:
    """Non-streaming title via OpenAI-compatible /v1/chat/completions; returns None on failure."""
    excerpt = (text or "")[:300]
    prompt = (
        "Generate a short chat title (4-6 words, no punctuation, no quotes) summarizing "
        f"this assistant response: {excerpt}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 48,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            if r.status_code >= 400:
                logger.warning("auto-title: LLM returned %d", r.status_code)
                return None
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                logger.warning("auto-title: no choices in response")
                return None
            msg = choices[0].get("message") or {}
            raw = (msg.get("content") or "").strip()
            cleaned = _clean_auto_title(raw)
            logger.info("auto-title: raw=%r cleaned=%r", raw[:80], cleaned)
            return cleaned or None
    except Exception as e:
        logger.warning("auto-title: failed: %s: %s", type(e).__name__, e)
        return None


async def _stream_inference(
    provider: Provider,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[bytes]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    logger.info("openai /v1/chat/completions provider=%s model=%s", provider.name, model)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
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
                            piece = delta.get("content") or ""
                            if piece:
                                yield _sse(json.dumps({"content": piece}))
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    yield _sse("[DONE]")


class ChatCreate(BaseModel):
    title: str | None = None
    model: str | None = Field(default=None)
    workspace_id: uuid.UUID | None = None
    web_search_enabled: bool | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    web_search_enabled: bool | None = None
    workspace_id: uuid.UUID | None = None


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    model: str | None = None
    attached_source_ids: list[str] | None = None


def _scrub_pg_text(value: str) -> str:
    """Strip null bytes from a string before INSERT into a Postgres TEXT
    column. asyncpg + Postgres reject 0x00 in TEXT with
    `CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8"`.

    The frontend gates image attachments out at the input layer, but this
    is defense-in-depth — a stray null byte from any other binary that
    slipped past the MIME check (zip dropped as octet-stream, etc.) would
    otherwise 500 the messages endpoint.
    """
    if not value:
        return value
    return value.replace("\x00", "")


class WebSearchToggleBody(BaseModel):
    enabled: bool


class SourceSelectionBody(BaseModel):
    source_ids: list[uuid.UUID] = Field(default_factory=list)


def _chat_row(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "workspace_id": str(r["workspace_id"]) if r["workspace_id"] else None,
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
    raw_content = r["content"] or ""
    return {
        "id": str(r["id"]),
        "chat_id": str(r["chat_id"]),
        "role": r["role"],
        "content": decrypt_column(raw_content, str(r["id"])) if raw_content else raw_content,
        "model": r["model"],
        "tokens_used": r["tokens_used"],
        "sources_used": r["sources_used"],
        "forked_from": str(r["forked_from"]) if r["forked_from"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.post("/")
async def create_chat(
    body: ChatCreate,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await assert_workspace_usable(conn, principal, body.workspace_id)
        # Model resolution post-providers: explicit body.model first, then
        # workspace.model, then the legacy global_settings.default_model entry.
        # No env-var fallback. If all three are NULL, the row stores NULL and
        # send-time resolves the model via the workspace.
        row = await conn.fetchrow(
            """
            INSERT INTO chats (title, workspace_id, model, web_search_enabled, rag_enabled, owner_id)
            VALUES ($1, $2,
                COALESCE(
                    $3,
                    (SELECT NULLIF(TRIM(model), '') FROM workspaces WHERE id = $2::uuid),
                    (SELECT value FROM global_settings WHERE key = 'default_model' LIMIT 1)
                ),
                COALESCE($4, FALSE),
                $6,
                $5)
            RETURNING id, title, workspace_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            body.title,
            body.workspace_id,
            body.model,
            body.web_search_enabled,
            principal["user_id"],
            body.workspace_id is not None,
        )
    async with audit.targeting("chat", row["id"]):
        pass
    return _chat_row(row)


@router.get("/")
async def list_chats(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    workspace_id: uuid.UUID | None = Query(None, description="When set, only chats for this workspace."),
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    cols = """
                id, title, workspace_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
    """
    async with pool.acquire() as conn:
        if workspace_id is not None:
            rows = await conn.fetch(
                f"""
                SELECT {cols}
                FROM chats
                WHERE workspace_id = $3::uuid
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
                workspace_id,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM chats WHERE workspace_id = $1::uuid",
                workspace_id,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT {cols}
                FROM chats
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM chats",
            )
    async with audit.targeting("chat", None):
        pass
    return {"items": [_chat_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/non-workspace")
async def delete_non_workspace_chats(
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Delete all chats not tied to a workspace (workspace_id IS NULL)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            """
            WITH deleted AS (
                DELETE FROM chats
                WHERE workspace_id IS NULL
                RETURNING 1
            )
            SELECT COUNT(*)::int FROM deleted
            """,
        )
    async with audit.targeting("chat", None):
        pass
    return {"deleted": int(deleted or 0)}


@router.get("/{chat_id}")
async def get_chat(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, workspace_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    async with audit.targeting("chat", chat_id):
        pass
    return _chat_row(row)


@router.patch("/{chat_id}/web-search")
async def patch_web_search(
    chat_id: uuid.UUID,
    body: WebSearchToggleBody,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None:
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
    async with audit.targeting("chat", chat_id):
        pass
    return {"web_search_enabled": bool(row["web_search_enabled"])}


@router.get("/{chat_id}/source-selection")
async def get_source_selection(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = await conn.fetch(
            "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
            chat_id,
        )
    async with audit.targeting("chat", chat_id):
        pass
    return {"chat_id": str(chat_id), "source_ids": [str(r["source_id"]) for r in rows]}


@router.put("/{chat_id}/source-selection")
async def put_source_selection(
    chat_id: uuid.UUID,
    body: SourceSelectionBody,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
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
    async with audit.targeting("chat", chat_id):
        pass
    return {"chat_id": str(chat_id), "source_ids": [str(s) for s in body.source_ids]}


@router.patch("/{chat_id}")
async def patch_chat(
    chat_id: uuid.UUID,
    body: ChatPatch,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, workspace_id, model, web_search_enabled, rag_enabled,
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
        new_workspace = row["workspace_id"] if "workspace_id" not in data else data["workspace_id"]

        if new_workspace is not None:
            await assert_workspace_usable(conn, principal, new_workspace)

        updated = await conn.fetchrow(
            """
            UPDATE chats
            SET title = $2, model = $3, web_search_enabled = $4,
                workspace_id = $5, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, title, workspace_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            chat_id,
            new_title,
            new_model,
            new_ws,
            new_workspace,
        )
    async with audit.targeting("chat", chat_id):
        pass
    return _chat_row(updated)


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        result = await conn.execute("DELETE FROM chats WHERE id = $1::uuid", chat_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Chat not found")
    async with audit.targeting("chat", chat_id):
        pass
    return {"ok": True}


@router.post("/{chat_id}/export")
async def export_chat(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict:
    """Save a chat's messages to /data/history/chats/<workspace-slug>/<file-slug>.md.

    Requires the chat to be in a workspace (workspace_id must not be NULL).
    Attempts an AI rename via _openai_short_chat_title; on failure the
    timestamp filename persists and ai_renamed=false is returned.
    """
    from services.history import workspace_dir, slugify
    from services.history_writer import render_chat_markdown, timestamp_slug

    pool = await get_pool()
    async with pool.acquire() as conn:
        chat_row = await conn.fetchrow(
            "SELECT id, title, workspace_id, model, created_at FROM chats WHERE id=$1::uuid",
            chat_id,
        )
        if chat_row is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        if chat_row["workspace_id"] is None:
            raise HTTPException(status_code=400, detail="chat must be in a workspace to export")

        workspace_row = await conn.fetchrow(
            "SELECT name FROM workspaces WHERE id=$1::uuid",
            chat_row["workspace_id"],
        )
        if workspace_row is None:
            raise HTTPException(status_code=400, detail="Workspace not found")

        msg_rows = await conn.fetch(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE chat_id=$1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

    workspace_name: str = workspace_row["name"]
    messages = [
        {
            "role": r["role"],
            "content": decrypt_column(r["content"] or "", str(r["id"])) if r["content"] else (r["content"] or ""),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in msg_rows
    ]
    chat_dict = {
        "title": chat_row["title"],
        "model": chat_row["model"],
        "created_at": chat_row["created_at"].isoformat() if chat_row["created_at"] else None,
    }

    content = render_chat_markdown(chat_dict, messages)

    ts = timestamp_slug()
    initial_filename = f"{ts}.md"

    target_dir = workspace_dir("chats", workspace_name)
    file_path = target_dir / initial_filename
    file_path.write_text(content, encoding="utf-8")

    # AI rename: derive a descriptive filename from the first user messages.
    # Requires the chat's workspace to have a provider configured; otherwise
    # the timestamp filename persists (ai_renamed=false).
    ai_renamed = False
    user_texts = [m["content"] for m in messages if m.get("role") == "user"]
    user_sample = "\n".join(user_texts)[:1000]
    provider_for_title: Provider | None = None
    model_for_title: str = ""
    if user_sample and chat_row["workspace_id"] is not None:
        try:
            provider_for_title, model_for_title = await resolve_provider_for_workspace(
                chat_row["workspace_id"]
            )
        except HTTPException as e:
            logger.info(
                "export_chat ai_rename skipped chat_id=%s: %s", str(chat_id), e.detail
            )
    if user_sample and provider_for_title is not None:
        try:
            ai_title = await _openai_short_chat_title(
                provider_for_title,
                model_for_title,
                user_sample,
            )
            if ai_title:
                slug = slugify(ai_title, max_len=60)
                candidate = f"{slug}-{ts}.md"
                # Collision check
                candidate_path = target_dir / candidate
                nonce = 1
                while candidate_path.exists():
                    if nonce > 50:
                        raise HTTPException(status_code=500, detail="export collision loop")
                    candidate = f"{slug}-{ts}-{nonce:03d}.md"
                    candidate_path = target_dir / candidate
                    nonce += 1
                file_path.rename(candidate_path)
                file_path = candidate_path
                ai_renamed = True
        except Exception as exc:
            logger.warning(
                "export_chat ai_rename failed chat_id=%s err=%s", str(chat_id), exc
            )

    logger.info(
        "export_chat chat_id=%s workspace=%s file=%s ai_renamed=%s",
        str(chat_id), workspace_name, file_path.name, ai_renamed,
    )
    async with audit.targeting("chat", chat_id):
        pass
    return {
        "filename": file_path.name,
        "workspace_slug": slugify(workspace_name),
        "path": str(file_path),
        "ai_renamed": ai_renamed,
    }


@router.get("/{chat_id}/messages")
async def list_messages(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
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
    async with audit.targeting("chat", chat_id):
        pass
    return {"items": [_message_row(r) for r in rows]}


@router.post("/{chat_id}/messages/{message_id}/fork")
async def fork_chat_at_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            src = await conn.fetchrow(
                """
                SELECT id, title, model, workspace_id,
                    web_search_enabled, rag_enabled
                FROM chats
                WHERE id = $1::uuid
                """,
                chat_id,
            )
            if src is None:
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
                SELECT id, role, content, model, tokens_used, sources_used, safeguard_version, ai_generated
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
                    title, workspace_id, model,
                    web_search_enabled, rag_enabled, message_count,
                    owner_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, title, workspace_id, model, web_search_enabled, rag_enabled,
                    pruning_summary, message_count, is_main_chat, created_at, updated_at
                """,
                fork_title,
                src["workspace_id"],
                src["model"],
                src["web_search_enabled"],
                src["rag_enabled"],
                len(copies),
                principal["user_id"],
            )
            assert new_chat is not None
            new_id = new_chat["id"]

            for r in copies:
                mid = uuid.uuid4()
                raw_content = r["content"] or ""
                plain_content = decrypt_column(raw_content, str(r["id"])) if raw_content else raw_content
                await conn.execute(
                    """
                    INSERT INTO messages (
                        id, chat_id, role, content, model, tokens_used, sources_used, forked_from, safeguard_version, ai_generated
                    )
                    VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid, $9, $10
                    )
                    """,
                    mid,
                    new_id,
                    r["role"],
                    encrypt_column(plain_content, str(mid)) if plain_content else plain_content,
                    r["model"],
                    r["tokens_used"],
                    r["sources_used"],
                    r["id"],
                    r["safeguard_version"],
                    r["ai_generated"],
                )

    async with audit.targeting("chat", chat_id):
        pass
    return _chat_row(new_chat)


@router.post("/{chat_id}/messages")
async def append_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            """
            SELECT id, title, model, pruning_summary, web_search_enabled, workspace_id,
                message_count, rag_enabled
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")

        audit._target_type = "chat"
        audit._target_id = str(chat_id)

        # Provider resolution: every chat send must go through the workspace's
        # configured provider. Workspaces without a provider raise the exact
        # spec message. Chats without a workspace can't have a provider either.
        if chat["workspace_id"] is None:
            raise HTTPException(
                status_code=400,
                detail="No provider configured for this workspace. Open Settings → Workspace to pick one.",
            )
        provider, ws_model = await resolve_provider_for_workspace(chat["workspace_id"])
        # The workspace pins (provider_id, model) together via CHECK constraint,
        # so ws_model is always non-empty here. body.model and chat.model are
        # ignored once we're past the resolver — workspace owns the truth.
        effective_model = ws_model

        # Fetch is_bundled so the gen() closure knows whether data leaves the
        # operator's network. Bundled providers (hlh_chat) stay on-box; external
        # providers require de-identification of user messages before send.
        provider_is_bundled_row = await conn.fetchval(
            "SELECT is_bundled FROM providers WHERE id = $1::uuid",
            provider.id,
        )
        provider_is_bundled: bool = bool(provider_is_bundled_row or False)

        # Keep chat.model in sync with the resolved model (purely informational;
        # send-time always re-resolves via the workspace).
        if (chat["model"] or "") != effective_model:
            await conn.execute(
                "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                chat_id,
                effective_model,
            )

        first_exchange_for_auto_title = int(chat["message_count"] or 0) == 0

        user_msg_id = uuid.uuid4()
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model, ai_generated)
                VALUES ($1::uuid, $2::uuid, 'user', $3, $4, $5)
                """,
                user_msg_id,
                chat_id,
                encrypt_column(_scrub_pg_text(body.content.strip()), str(user_msg_id)),
                effective_model,
                False,
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
            SELECT id, role, content
            FROM messages
            WHERE chat_id = $1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

        assembled, rag_sse_meta = await _assembled_system_prompt(
            conn,
            chat,
            user_query_for_rag=_scrub_pg_text(body.content.strip()),
            include_site_private=True,
        )

        user_profile_block = ""
        try:
            uid = principal.get("user_id")
            if uid:
                prof = await conn.fetchrow(
                    "SELECT display_name, username, bio FROM users WHERE id = $1::uuid",
                    uid,
                )
                if prof:
                    name = (prof["display_name"] or prof["username"] or "").strip()
                    bio = (prof["bio"] or "").strip()
                    if name or bio:
                        lines = ["## About the user you are talking to"]
                        if name:
                            lines.append(f"Name: {name}")
                        if bio:
                            lines.append(f"About: {bio}")
                        user_profile_block = "\n".join(lines)
        except Exception:
            user_profile_block = ""

    summary = chat["pruning_summary"]
    user_message_text = _scrub_pg_text(body.content.strip())

    from services.guard import scan_input, scan_output
    input_scan = scan_input(user_message_text)
    if not input_scan.passed:
        try:
            _pool = await get_pool()
            async with _pool.acquire() as _aconn:
                await insert_audit_event(_aconn, AuditRecord(
                    request_id=request.state.request_id,
                    actor=principal.get("username", "unknown"),
                    action="safeguard.refuse.input",
                    target_type="chat",
                    target_id=str(chat_id),
                    status_code=422,
                    payload_hash=hashlib.sha256(user_message_text.encode("utf-8")).digest(),
                ))
        except Exception:
            logger.warning("audit insert failed for input guard refusal", exc_info=True)
        return JSONResponse(
            status_code=422,
            content={
                "error": "input_blocked",
                "guard_flags": input_scan.to_json(),
                "message": "Your message was blocked by the input guard. Please rephrase.",
            },
        )

    async def gen() -> AsyncIterator[bytes]:
        sources_list: list[dict[str, str]] = []
        extra_search = ""
        if bool(chat["web_search_enabled"]):
            sources_list, extra_search = await searx_search_sources(
                user_message_text,
            )
        if sources_list:
            yield _sse(json.dumps({"type": "search_sources", "sources": sources_list}))
        if rag_sse_meta:
            yield _sse(
                json.dumps(
                    {
                        "type": "rag_context",
                        "chunks": rag_sse_meta["chars"],
                        "count": rag_sse_meta["count"],
                    }
                )
            )

        api_messages: list[dict[str, str]] = []
        system_blocks: list[str] = []
        if assembled:
            system_blocks.append(assembled)
        if user_profile_block:
            system_blocks.append(user_profile_block)
        if summary:
            system_blocks.append("Compressed prior conversation summary:\n" + summary)
        if extra_search:
            system_blocks.append(
                "## Web search results (use if relevant; the user enabled web search for this turn):\n" + extra_search
            )
        if body.attached_source_ids:
            attached_docs: list[str] = []
            for sid in body.attached_source_ids:
                try:
                    src_path = pathlib.Path(f"/data/uploads")
                    async with pool.acquire() as aconn:
                        srow = await aconn.fetchrow(
                            "SELECT name, mime_type, file_url FROM sources WHERE id = $1::uuid", uuid.UUID(sid)
                        )
                    if srow and srow["file_url"]:
                        fp = pathlib.Path(srow["file_url"])
                        if fp.exists():
                            file_raw = fp.read_bytes()
                            smime = (srow["mime_type"] or "text/plain").lower().split(";")[0].strip()
                            txt = None
                            if smime == "application/pdf":
                                from services.vision import extract_pdf_via_vision
                                txt = await extract_pdf_via_vision(file_raw)
                            elif smime.startswith("image/"):
                                from services.vision import extract_image_via_vision
                                txt = await extract_image_via_vision(file_raw, smime)
                            if not txt:
                                from services.chunking import parse_source_bytes as _parse
                                txt = _parse(file_raw, srow["mime_type"] or "text/plain")
                            if deid_enabled():
                                txt = redact_text(txt).text
                            attached_docs.append(f"[DOCUMENT: {srow['name']}]\n{txt}")
                except Exception as exc:
                    logger.warning("attached source %s read failed: %s", sid, exc)
            if attached_docs:
                system_blocks.append(
                    "### Attached documents (the user explicitly sent these to chat — read them fully):\n\n"
                    + "\n\n---\n\n".join(attached_docs)
                )
        if system_blocks:
            api_messages.append({"role": "system", "content": "\n\n".join(system_blocks)})
        for r in msg_rows:
            role = r["role"]
            if role not in ("user", "assistant", "system"):
                continue
            raw = r["content"] or ""
            api_messages.append({"role": role, "content": decrypt_column(raw, str(r["id"])) if raw else raw})

        # De-identify user messages before sending to external providers.
        # Bundled providers (is_bundled=True) run on-box — no redaction needed.
        # System and assistant messages are not redacted (safeguard preamble +
        # historical assistant responses; see C5 Task B rationale).
        if deid_enabled() and not provider_is_bundled:
            for msg in api_messages:
                if msg["role"] == "user":
                    r = redact_text(msg["content"])
                    if r.had_phi:
                        logger.info(
                            "deid: redacted %d findings in user message before external inference",
                            len(r.findings),
                        )
                    msg["content"] = r.text

        full: list[str] = []
        had_error = False
        logger.info(
            "chat inference chat_id=%s model=%s workspace_id=%s",
            str(chat_id),
            effective_model,
            str(chat["workspace_id"]) if chat["workspace_id"] else None,
        )
        stream = _stream_inference(
            provider,
            effective_model,
            api_messages,
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

        output_scan = scan_output(assistant_text)
        guard_flags_json = output_scan.to_json() if output_scan.flags else None

        assist_id = uuid.uuid4()
        p = await get_pool()
        async with p.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model, safeguard_version, ai_generated, guard_flags)
                VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4, $5, $6, $7)
                """,
                assist_id,
                chat_id,
                encrypt_column(assistant_text, str(assist_id)),
                effective_model,
                current_version(),
                True,
                json.dumps(guard_flags_json) if guard_flags_json else None,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )
            if output_scan.flags:
                try:
                    flags_bytes = json.dumps(guard_flags_json).encode("utf-8")
                    await insert_audit_event(conn, AuditRecord(
                        request_id=request.state.request_id,
                        actor="system",
                        action="safeguard.flag.output",
                        target_type="message",
                        target_id=str(assist_id),
                        status_code=200,
                        payload_hash=hashlib.sha256(flags_bytes).digest(),
                    ))
                except Exception:
                    logger.warning("audit insert failed for output guard flags", exc_info=True)

        title_emit: str | None = None
        has_custom_title = bool((chat["title"] or "").strip())
        if first_exchange_for_auto_title and assistant_text and not has_custom_title:
            new_title: str | None = None
            try:
                new_title = await _openai_short_chat_title(provider, effective_model, assistant_text)
            except Exception:
                new_title = None
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
        if auto_mem:
            async with p.acquire() as conn_mem:
                mem_row = await conn_mem.fetchrow(
                    """
                    INSERT INTO memory_entries (content, source)
                    VALUES ($1, 'auto')
                    RETURNING id
                    """,
                    auto_mem,
                )
                if mem_row:
                    try:
                        from services.embeddings import embed_text

                        emb = await embed_text(auto_mem)
                        if emb:
                            await conn_mem.execute(
                                """
                                UPDATE memory_entries
                                SET embedding = $1::vector, embedded_at = NOW()
                                WHERE id = $2::uuid
                                """,
                                str(emb),
                                mem_row["id"],
                            )
                    except Exception as e:
                        logger.warning("Failed to embed memory entry: %s", e)

        await summarize_and_compress(str(chat_id), p)

        if not output_scan.passed:
            yield _sse(json.dumps({
                "type": "guard_alert",
                "flags": output_scan.to_json(),
                "message": "The assistant's response was flagged by the output guard.",
            }))
        if output_scan.flags and output_scan.passed:
            yield _sse(json.dumps({
                "type": "guard_info",
                "flags": output_scan.to_json(),
            }))

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
