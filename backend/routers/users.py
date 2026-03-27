"""User accounts (owner / members / super_admin)."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_deps import pwd_context, require_admin
from db import get_pool
from seed_users import SUPER_ADMIN_USERNAME

router = APIRouter()


class MemberCreate(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)


class AdminPasswordPatch(BaseModel):
    password: str = Field(..., min_length=8)


def _user_out(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "username": r["username"],
        "role": r["role"],
        "display_name": (r["display_name"] or r["username"] or "").strip(),
        "has_icon": bool(r.get("icon_url")),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("/")
async def list_members(_: dict[str, Any] = Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, username, role, display_name, icon_url, created_at FROM users
            ORDER BY role DESC, created_at ASC NULLS LAST, username ASC
            """,
        )
    return {"items": [_user_out(r) for r in rows]}


@router.post("/")
async def create_member(body: MemberCreate, _: dict[str, Any] = Depends(require_admin)):
    uname = body.username.strip()
    if not uname:
        raise HTTPException(status_code=400, detail="username required")
    if uname.lower() in ("owner", SUPER_ADMIN_USERNAME.lower()):
        raise HTTPException(status_code=400, detail="reserved_username")
    h = pwd_context.hash(body.password)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, role, display_name, avatar_emoji, bio)
                VALUES ($1, $2, 'member', $1, '👤', '')
                RETURNING id, username, role, display_name, icon_url, created_at
                """,
                uname,
                h,
            )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=400, detail="username_taken") from None
    assert row is not None
    return _user_out(row)


@router.patch("/{user_id}")
async def admin_set_password(
    user_id: uuid.UUID,
    body: AdminPasswordPatch,
    _: dict[str, Any] = Depends(require_admin),
):
    pool = await get_pool()
    h = pwd_context.hash(body.password)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET password_hash = $2 WHERE id = $1::uuid",
            user_id,
            h,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="user not found")
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_member(user_id: uuid.UUID, _: dict[str, Any] = Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username FROM users WHERE id = $1::uuid",
            user_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        if (row["username"] or "").lower() == SUPER_ADMIN_USERNAME.lower():
            raise HTTPException(status_code=403, detail="cannot_delete_protected_owner_user")
        result = await conn.execute("DELETE FROM users WHERE id = $1::uuid", user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="user not found")
    return {"ok": True}
