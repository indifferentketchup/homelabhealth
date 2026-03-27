"""Custom instructions per scope (`custom_instructions` table)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_deps import require_admin
from db import get_pool

router = APIRouter()

VALID_SCOPES = frozenset({"global", "booops", "808notes"})


class InstructionsBody(BaseModel):
    content: str = ""


def _norm_scope(scope: str) -> str:
    s = (scope or "").strip()
    if s not in VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail="scope must be one of: global, booops, 808notes",
        )
    return s


def _row(r: Any) -> dict[str, Any]:
    return {
        "scope": r["scope"],
        "content": r["content"] or "",
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


@router.get("/")
async def get_instructions(scope: str = Query(...), _: dict = Depends(require_admin)):
    s = _norm_scope(scope)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO custom_instructions (scope, content)
            VALUES ($1, '')
            ON CONFLICT (scope) DO NOTHING
            """,
            s,
        )
        row = await conn.fetchrow(
            "SELECT scope, content, updated_at FROM custom_instructions WHERE scope = $1",
            s,
        )
    return _row(row)


@router.put("/")
async def put_instructions(
    body: InstructionsBody,
    scope: str = Query(...),
    _: dict = Depends(require_admin),
):
    s = _norm_scope(scope)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO custom_instructions (scope, content, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (scope) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING scope, content, updated_at
            """,
            s,
            body.content or "",
        )
    return _row(row)


@router.delete("/")
async def clear_instructions(scope: str = Query(...), _: dict = Depends(require_admin)):
    s = _norm_scope(scope)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO custom_instructions (scope, content, updated_at)
            VALUES ($1, '', NOW())
            ON CONFLICT (scope) DO UPDATE SET content = '', updated_at = NOW()
            """,
            s,
        )
        row = await conn.fetchrow(
            "SELECT scope, content, updated_at FROM custom_instructions WHERE scope = $1",
            s,
        )
    return _row(row)
