"""Per-workspace memory entries (owner-only CRUD); injected into chat system prompt."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from deps import require_owner
from db import get_pool

router = APIRouter(prefix="/workspaces", tags=["workspace-memory"])

_MAX_CONTENT = 2000


class WorkspaceMemoryCreate(BaseModel):
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
        "workspace_id": str(r["workspace_id"]),
        "content": r["content"],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("/{workspace_id}/memory")
async def list_workspace_memory(
    workspace_id: uuid.UUID,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_ok = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if workspace_ok is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        rows = await conn.fetch(
            """
            SELECT id, workspace_id, content, created_at
            FROM workspace_memory
            WHERE workspace_id = $1::uuid
            ORDER BY created_at ASC
            """,
            workspace_id,
        )
    return [_entry_row(r) for r in rows]


@router.post("/{workspace_id}/memory")
async def create_workspace_memory(
    workspace_id: uuid.UUID,
    body: WorkspaceMemoryCreate,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_ok = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if workspace_ok is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row = await conn.fetchrow(
            """
            INSERT INTO workspace_memory (workspace_id, content)
            VALUES ($1::uuid, $2)
            RETURNING id, workspace_id, content, created_at
            """,
            workspace_id,
            body.content,
        )
    assert row is not None
    return _entry_row(row)


@router.delete("/{workspace_id}/memory/{entry_id}")
async def delete_workspace_memory(
    workspace_id: uuid.UUID,
    entry_id: int,
    _owner: dict[str, Any] = Depends(require_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_ok = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if workspace_ok is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        result = await conn.execute(
            """
            DELETE FROM workspace_memory
            WHERE id = $1 AND workspace_id = $2::uuid
            """,
            entry_id,
            workspace_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"ok": True}
