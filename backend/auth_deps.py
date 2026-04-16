"""Single-user stub. Authelia gates everything upstream; inside the app every request is samkintop (owner)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import asyncpg
from fastapi import HTTPException

from db import get_pool

SUPER_ADMIN_USERNAME = (os.environ.get("SUPER_ADMIN_USERNAME") or "samkintop").strip() or "samkintop"

_owner_user_id: uuid.UUID | None = None


async def _resolve_owner_user_id() -> uuid.UUID:
    global _owner_user_id
    if _owner_user_id is not None:
        return _owner_user_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE username = $1 LIMIT 1",
            SUPER_ADMIN_USERNAME,
        )
    if row is None:
        raise HTTPException(status_code=503, detail="owner_user_missing")
    _owner_user_id = row["id"]
    return _owner_user_id


async def get_principal() -> dict[str, Any]:
    uid = await _resolve_owner_user_id()
    return {"kind": "owner", "user_id": uid, "username": SUPER_ADMIN_USERNAME}


async def require_owner() -> dict[str, Any]:
    return await get_principal()


async def require_admin() -> dict[str, Any]:
    return await get_principal()


def principal_can_access_chat(principal: dict[str, Any], row: asyncpg.Record) -> bool:
    return True


async def assert_persona_usable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    persona_id: uuid.UUID | None,
) -> None:
    if persona_id is None:
        return
    row = await conn.fetchrow(
        "SELECT 1 FROM personas WHERE id = $1::uuid",
        persona_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="persona_id not found")


async def assert_daw_usable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    daw_id: uuid.UUID | None,
) -> None:
    if daw_id is None:
        return
    row = await conn.fetchrow(
        "SELECT 1 FROM daws WHERE id = $1::uuid",
        daw_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="daw_id not found")


def persona_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    return True


def daw_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    return True


async def fetch_daw_if_visible(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    daw_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, owner_id FROM daws WHERE id = $1::uuid",
        daw_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="DAW not found")
    return row


async def assert_persona_mutable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    persona_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        SELECT id, owner_id, is_default_booops, is_default_808notes
        FROM personas WHERE id = $1::uuid
        """,
        persona_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return row


async def assert_daw_mutable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    daw_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, owner_id, mode FROM daws WHERE id = $1::uuid",
        daw_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="DAW not found")
    return row
