"""Authentication dependencies.

Replaces the old always-owner stub. Every request must have a valid
session cookie (set by POST /api/auth/login) unless it hits an
unauthenticated endpoint (login, setup, health).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request

from db import get_pool
from services.auth import validate_session

SESSION_COOKIE = "hlh_session"


async def get_principal(request: Request) -> dict[str, Any]:
    """Read session from cookie, validate, return user dict.

    Returns: {"kind": "authenticated", "user_id": UUID, "username": str, "role": str}
    Raises 401 if no valid session.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not_authenticated")
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await validate_session(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="session_expired")
    return {
        "kind": "authenticated",
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
    }


async def require_owner(request: Request) -> dict[str, Any]:
    principal = await get_principal(request)
    if principal["role"] not in ("owner", "super_admin"):
        raise HTTPException(status_code=403, detail="owner_required")
    return principal


async def require_admin(request: Request) -> dict[str, Any]:
    return await require_owner(request)


async def assert_workspace_usable(conn, principal, workspace_id):
    if workspace_id is None:
        return
    import asyncpg
    row = await conn.fetchrow(
        "SELECT 1 FROM workspaces WHERE id = $1::uuid",
        workspace_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="workspace_id not found")
