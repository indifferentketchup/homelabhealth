"""Single-user always-owner stub. The whole app trusts every request as the owner.

Self-hosters who want real auth should add a reverse proxy (e.g. Authelia,
oauth2-proxy) in front of the API container. The principal returned here is
the seeded owner row from the `users` table — found by `LIMIT 1` since this
deployment only ever has one user.
"""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from fastapi import HTTPException

from db import get_pool

# Required by mode CHECK constraints on chats/daws/memory_entries/mode_memory.
_SCHEMA_MODE_VALUE = "808notes"

_owner_user_id: uuid.UUID | None = None


async def _resolve_owner_user_id() -> uuid.UUID:
    global _owner_user_id
    if _owner_user_id is not None:
        return _owner_user_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users LIMIT 1")
    if row is None:
        raise HTTPException(status_code=503, detail="owner_user_missing")
    _owner_user_id = row["id"]
    return _owner_user_id


async def get_principal() -> dict[str, Any]:
    uid = await _resolve_owner_user_id()
    return {"kind": "owner", "user_id": uid, "username": "owner"}


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


async def assert_workspace_usable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    workspace_id: uuid.UUID | None,
) -> None:
    if workspace_id is None:
        return
    row = await conn.fetchrow(
        "SELECT 1 FROM daws WHERE id = $1::uuid",
        workspace_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="workspace_id not found")


def persona_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    return True


def workspace_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    return True


async def fetch_workspace_if_visible(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    workspace_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, owner_id FROM daws WHERE id = $1::uuid",
        workspace_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row


async def assert_persona_mutable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    persona_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        SELECT id, owner_id, is_default_808notes
        FROM personas WHERE id = $1::uuid
        """,
        persona_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return row


async def assert_workspace_mutable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    workspace_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, owner_id, mode FROM daws WHERE id = $1::uuid",
        workspace_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row
