"""808notes per-DAW notes (Phase 6 vertical slice)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_deps import get_principal
from db import get_pool

router = APIRouter(prefix="/notes", tags=["notes"])

_ALLOWED_SOURCE_TYPES = frozenset({"manual", "ai_response", "ai_summary"})


def _default_title_from_content(content: str) -> str:
    text = (content or "").strip()
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = (content or "").replace("\n", " ").strip()[:60]
    if not text:
        return "Untitled"
    return text[:60] if len(text) > 60 else text


def _note_row_dict(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "daw_id": str(r["daw_id"]),
        "group_id": str(r["group_id"]) if r.get("group_id") else None,
        "title": r["title"],
        "content": r["content"],
        "source_type": r["source_type"],
        "message_id": str(r["message_id"]) if r.get("message_id") else None,
        "converted_to_source_id": str(r["converted_to_source_id"]) if r.get("converted_to_source_id") else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


class NoteCreate(BaseModel):
    title: str | None = None
    content: str = Field(..., min_length=0)
    source_type: str | None = "manual"
    message_id: uuid.UUID | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


@router.get("/{daw_id}")
async def list_notes(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if not daw_exists:
            raise HTTPException(404, "DAW not found")
        rows = await conn.fetch(
            """
            SELECT id, title, content, source_type, created_at, updated_at
            FROM notes
            WHERE daw_id = $1::uuid
            ORDER BY updated_at DESC
            """,
            daw_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "content": r["content"],
                "source_type": r["source_type"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
        )
    return out


@router.post("/{daw_id}")
async def create_note(
    daw_id: uuid.UUID,
    body: NoteCreate,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    st = (body.source_type or "manual").strip()
    if st not in _ALLOWED_SOURCE_TYPES:
        raise HTTPException(400, "Invalid source_type")
    title = body.title.strip() if body.title else None
    if not title:
        title = _default_title_from_content(body.content)
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if not daw_exists:
            raise HTTPException(404, "DAW not found")
        row = await conn.fetchrow(
            """
            INSERT INTO notes (daw_id, title, content, source_type, message_id)
            VALUES ($1::uuid, $2, $3, $4, $5::uuid)
            RETURNING id, daw_id, group_id, title, content, source_type, message_id,
                      converted_to_source_id, created_at, updated_at
            """,
            daw_id,
            title,
            body.content,
            st,
            body.message_id,
        )
    return _note_row_dict(row)


@router.put("/{note_id}")
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    if body.title is None and body.content is None:
        raise HTTPException(400, "No fields to update")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, daw_id, title, content FROM notes WHERE id = $1::uuid",
            note_id,
        )
        if row is None:
            raise HTTPException(404, "Note not found")
        new_title = body.title if body.title is not None else row["title"]
        new_content = body.content if body.content is not None else row["content"]
        updated = await conn.fetchrow(
            """
            UPDATE notes
            SET title = $2, content = $3, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, daw_id, group_id, title, content, source_type, message_id,
                      converted_to_source_id, created_at, updated_at
            """,
            note_id,
            new_title,
            new_content,
        )
    return _note_row_dict(updated)


@router.delete("/{note_id}")
async def delete_note(
    note_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, daw_id FROM notes WHERE id = $1::uuid", note_id)
        if row is None:
            raise HTTPException(404, "Note not found")
        await conn.execute("DELETE FROM notes WHERE id = $1::uuid", note_id)
    return {"deleted": str(note_id)}
