"""Global custom instructions (singleton row in `custom_instructions` table)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import require_admin
from db import get_pool
from services.audit import AuditEventHandle, audit_event

router = APIRouter()


class InstructionsBody(BaseModel):
    content: str = ""


def _row(r: Any) -> dict[str, Any]:
    return {
        "content": r["content"] or "",
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


@router.get("/")
async def get_instructions(
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO custom_instructions (content)
            VALUES ('')
            ON CONFLICT ((1)) DO NOTHING
            """
        )
        row = await conn.fetchrow(
            "SELECT content, updated_at FROM custom_instructions LIMIT 1"
        )
    async with audit.targeting("custom_instructions", None):
        pass
    return _row(row)


@router.put("/")
async def put_instructions(
    body: InstructionsBody,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO custom_instructions (content, updated_at)
            VALUES ($1, NOW())
            ON CONFLICT ((1)) DO UPDATE
                SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING content, updated_at
            """,
            body.content or "",
        )
    async with audit.targeting("custom_instructions", None):
        pass
    return _row(row)


@router.delete("/")
async def clear_instructions(
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO custom_instructions (content, updated_at)
            VALUES ('', NOW())
            ON CONFLICT ((1)) DO UPDATE
                SET content = '', updated_at = NOW()
            RETURNING content, updated_at
            """
        )
    async with audit.targeting("custom_instructions", None):
        pass
    return _row(row)
