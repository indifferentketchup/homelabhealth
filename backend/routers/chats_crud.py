"""Pure chat-CRUD endpoints extracted from routers/chats.py (2026-06-14).

Covers: create chat, list chats, get chat, patch chat, delete chat,
web-search toggle, source-selection CRUD, export, list messages, fork.

Mounted in main.py under the same /api/chats prefix and tags=["chats"] as the
main chats router so route paths are byte-identical to before.

Streaming/inference endpoints remain in routers/chats.py.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import (
    assert_workspace_usable,
    get_principal,
)
from db import get_pool
from services.audit import AuditEventHandle, audit_event
from services.crypto import decrypt_column, encrypt_column
from services.provider_client import (
    Provider,
    resolve_provider_for_workspace,
)
from services.prompt_assembly import _openai_short_chat_title

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models shared across CRUD endpoints
# ---------------------------------------------------------------------------

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


class WebSearchToggleBody(BaseModel):
    enabled: bool


class SourceSelectionBody(BaseModel):
    source_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Row serializers shared across CRUD endpoints
# (kept in sync with chats.py -- changes must be mirrored there too)
# ---------------------------------------------------------------------------

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
        "ctx_max": r["ctx_max"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _message_row(r: asyncpg.Record) -> dict[str, Any]:
    raw_content = r["content"] or ""
    out = {
        "id": str(r["id"]),
        "chat_id": str(r["chat_id"]),
        "role": r["role"],
        "content": decrypt_column(raw_content, str(r["id"])) if raw_content else "",
        "model": r["model"],
        "tokens_used": r["tokens_used"],
        "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"],
        "compacted_at": r["compacted_at"].isoformat() if r.get("compacted_at") else None,
        "sources_used": r["sources_used"],
        "forked_from": str(r["forked_from"]) if r["forked_from"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "guard_flags": r["guard_flags"] if r["guard_flags"] else None,
        "status": r.get("status", "complete"),
        "started_at": r["started_at"].isoformat() if r.get("started_at") else None,
        "finished_at": r["finished_at"].isoformat() if r.get("finished_at") else None,
    }
    err = r.get("error_message")
    if err:
        out["error_message"] = err
    return out


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def write_export_file(content: str, target_dir: pathlib.Path, initial_filename: str) -> pathlib.Path:
    """Write chat export content to disk and return the file path."""
    file_path = target_dir / initial_filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


async def ai_rename_file(
    file_path: pathlib.Path,
    target_dir: pathlib.Path,
    ts: str,
    user_sample: str,
    provider: Provider,
    model: str,
) -> tuple[pathlib.Path, bool]:
    """Derive a descriptive filename via LLM, handle slug collision, rename.

    Returns (final_path, ai_renamed).
    """
    import logging
    from services.history import slugify
    _logger = logging.getLogger(__name__)

    ai_title = await _openai_short_chat_title(provider, model, user_sample)
    if not ai_title:
        return file_path, False

    slug = slugify(ai_title, max_len=60)
    candidate = f"{slug}-{ts}.md"
    candidate_path = target_dir / candidate
    nonce = 1
    while candidate_path.exists():
        if nonce > 50:
            raise HTTPException(status_code=500, detail="export collision loop")
        candidate = f"{slug}-{ts}-{nonce:03d}.md"
        candidate_path = target_dir / candidate
        nonce += 1
    file_path.rename(candidate_path)
    return candidate_path, True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/")
async def create_chat(
    body: ChatCreate,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await assert_workspace_usable(conn, principal, body.workspace_id)
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
                pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
                pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
                pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
            for idx, sid in enumerate(body.source_ids):
                await conn.execute(
                    """
                    INSERT INTO chat_source_selections (chat_id, source_id, position)
                    VALUES ($1::uuid, $2::uuid, $3)
                    """,
                    chat_id,
                    sid,
                    idx,
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
                pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
                pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
    import logging
    from services.history import workspace_dir, slugify
    from services.history_writer import render_chat_markdown, timestamp_slug
    _logger = logging.getLogger(__name__)

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
    file_path = write_export_file(content, target_dir, initial_filename)

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
            _logger.info(
                "export_chat ai_rename skipped chat_id=%s: %s", str(chat_id), e.detail
            )
    if user_sample and provider_for_title is not None:
        try:
            file_path, ai_renamed = await ai_rename_file(
                file_path, target_dir, ts, user_sample, provider_for_title, model_for_title,
            )
        except Exception as exc:
            _logger.warning(
                "export_chat ai_rename failed chat_id=%s err=%s", str(chat_id), exc
            )

    _logger.info(
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
            SELECT id, chat_id, role, content, model, tokens_used, prompt_tokens, completion_tokens, compacted_at, sources_used, forked_from, created_at, guard_flags, status, started_at, finished_at, error_message
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
                    pruning_summary, message_count, is_main_chat, ctx_max, created_at, updated_at
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
