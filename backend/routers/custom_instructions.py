"""Global custom instructions (singleton row in `custom_instructions` table)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import uuid

from deps import require_admin
from db import get_pool
from services.audit import AuditEventHandle, audit_event
from services.crypto import encrypt_column, decrypt_column

router = APIRouter()


class InstructionsBody(BaseModel):
    content: str = ""


def _row(r: Any) -> dict[str, Any]:
    raw_content = r["content"] or ""
    return {
        "content": decrypt_column(raw_content, str(r["id"])) if raw_content else raw_content,
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
            "SELECT id, content, updated_at FROM custom_instructions LIMIT 1"
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
        # Fetch or create the singleton row id so we can derive the per-record DEK.
        existing = await conn.fetchrow("SELECT id FROM custom_instructions LIMIT 1")
        row_id: uuid.UUID = existing["id"] if existing else uuid.uuid4()
        encrypted_content = encrypt_column(body.content or "", str(row_id))
        row = await conn.fetchrow(
            """
            INSERT INTO custom_instructions (id, content, updated_at)
            VALUES ($1::uuid, $2, NOW())
            ON CONFLICT ((1)) DO UPDATE
                SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING id, content, updated_at
            """,
            row_id,
            encrypted_content,
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
        # Always write empty string (not encrypted) — passthrough for empty content.
        row = await conn.fetchrow(
            """
            INSERT INTO custom_instructions (content, updated_at)
            VALUES ('', NOW())
            ON CONFLICT ((1)) DO UPDATE
                SET content = '', updated_at = NOW()
            RETURNING id, content, updated_at
            """
        )
    async with audit.targeting("custom_instructions", None):
        pass
    return _row(row)
