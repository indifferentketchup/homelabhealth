"""Per-DAW memory entries (owner-only CRUD); injected into chat system prompt."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth_deps import require_owner
from db import get_pool

router = APIRouter(prefix="/daws", tags=["daw-memory"])

_MAX_CONTENT = 2000


class DawMemoryCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def strip_nonempty(cls, v: str) -> str:
        s = (str(v) if v is not None else "").strip()
        if not s:
            raise ValueError("content must not be empty")
        if len(s) > _MAX_CONTENT:
            raise ValueError(f"content must be at most {_MAX_CONTENT} characters")
        return s


def _entry_row(r: Any) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "daw_id": str(r["daw_id"]),
        "content": r["content"],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("/{daw_id}/memory")
async def list_daw_memory(
    daw_id: uuid.UUID,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_ok = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if daw_ok is None:
            raise HTTPException(status_code=404, detail="DAW not found")
        rows = await conn.fetch(
            """
            SELECT id, daw_id, content, created_at
            FROM daw_memory
            WHERE daw_id = $1::uuid
            ORDER BY created_at ASC
            """,
            daw_id,
        )
    return [_entry_row(r) for r in rows]


@router.post("/{daw_id}/memory")
async def create_daw_memory(
    daw_id: uuid.UUID,
    body: DawMemoryCreate,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_ok = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if daw_ok is None:
            raise HTTPException(status_code=404, detail="DAW not found")
        row = await conn.fetchrow(
            """
            INSERT INTO daw_memory (daw_id, content)
            VALUES ($1::uuid, $2)
            RETURNING id, daw_id, content, created_at
            """,
            daw_id,
            body.content,
        )
    assert row is not None
    return _entry_row(row)


@router.delete("/{daw_id}/memory/{entry_id}")
async def delete_daw_memory(
    daw_id: uuid.UUID,
    entry_id: int,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_ok = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id)
        if daw_ok is None:
            raise HTTPException(status_code=404, detail="DAW not found")
        result = await conn.execute(
            """
            DELETE FROM daw_memory
            WHERE id = $1 AND daw_id = $2::uuid
            """,
            entry_id,
            daw_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"ok": True}
