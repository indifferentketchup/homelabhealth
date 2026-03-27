"""JWT auth, role dependencies, and request principal (owner / member / guest)."""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from db import get_pool

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    if request.client:
        return (request.client.host or "").strip() or "unknown"
    return "unknown"


def jwt_secret() -> str:
    s = (os.environ.get("JWT_SECRET") or "").strip()
    if not s:
        raise HTTPException(status_code=503, detail="auth_not_configured")
    return s


def verify_owner_password(plain: str) -> bool:
    ref = (os.environ.get("OWNER_PASSWORD") or "").strip()
    if not ref:
        return False
    if ref.startswith("$2"):
        return bool(pwd_context.verify(plain, ref))
    return secrets.compare_digest(plain, ref)


def create_access_token(*, sub: str, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    payload: dict[str, Any] = {"sub": sub, "role": role, "exp": exp}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def _decode_token(token: str) -> dict[str, Any] | None:
    secret = (os.environ.get("JWT_SECRET") or "").strip()
    if not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any] | None:
    if creds is None or (creds.scheme or "").lower() != "bearer":
        return None
    token = (creds.credentials or "").strip()
    if not token:
        return None
    payload = _decode_token(token)
    if not payload:
        return None
    role = payload.get("role")
    sub = payload.get("sub")
    if role == "owner" and sub == "owner":
        return {"role": "owner"}
    if role in ("member", "super_admin") and sub:
        try:
            uid = uuid.UUID(str(sub))
        except ValueError:
            return None
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, username, role, display_name, bio, icon_url, avatar_emoji
                FROM users WHERE id = $1::uuid
                """,
                uid,
            )
        if row is None:
            return None
        db_role = row["role"]
        if db_role not in ("member", "super_admin"):
            return None
        return {
            "role": db_role,
            "user_id": row["id"],
            "username": row["username"],
            "display_name": (row["display_name"] or row["username"] or "").strip() or row["username"],
            "bio": row["bio"] or "",
            "icon_url": row["icon_url"],
            "avatar_emoji": (row["avatar_emoji"] or "").strip(),
        }
    return None


def is_admin_user(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    return user.get("role") in ("owner", "super_admin")


async def require_owner(user: dict[str, Any] | None = Depends(get_current_user)) -> dict[str, Any]:
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="owner_only")
    return user


async def require_admin(user: dict[str, Any] | None = Depends(get_current_user)) -> dict[str, Any]:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="admin_only")
    return user


async def require_db_account(user: dict[str, Any] | None = Depends(get_current_user)) -> dict[str, Any]:
    if not user or user.get("role") not in ("member", "super_admin"):
        raise HTTPException(status_code=403, detail="account_required")
    return user


async def require_member_or_owner(
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    if not user or user.get("role") not in ("owner", "member", "super_admin"):
        raise HTTPException(status_code=401, detail="authentication_required")
    return user


async def get_principal(
    request: Request,
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    if user and user.get("role") == "owner":
        return {"kind": "owner", "ip": client_ip(request)}
    if user and user.get("role") in ("member", "super_admin"):
        return {
            "kind": "member",
            "user_id": user["user_id"],
            "username": user.get("username") or "",
            "ip": client_ip(request),
        }
    return {"kind": "guest", "ip": client_ip(request)}


def principal_can_access_chat(principal: dict[str, Any], row: asyncpg.Record) -> bool:
    oid = row.get("owner_id")
    gip = row.get("guest_ip")
    if principal["kind"] == "owner":
        return oid is None and gip is None
    if principal["kind"] == "member":
        return oid is not None and oid == principal["user_id"]
    if oid is not None:
        return False
    if not gip:
        return False
    return gip == principal["ip"]


async def assert_persona_usable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    persona_id: uuid.UUID | None,
) -> None:
    if persona_id is None:
        return
    row = await conn.fetchrow(
        "SELECT owner_id FROM personas WHERE id = $1::uuid",
        persona_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="persona_id not found")
    p_oid = row["owner_id"]
    if principal["kind"] == "owner":
        return
    if p_oid is None:
        return
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="persona_not_allowed")
    if principal["kind"] == "member" and p_oid == principal["user_id"]:
        return
    raise HTTPException(status_code=403, detail="persona_not_allowed")


async def assert_daw_usable(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    daw_id: uuid.UUID | None,
) -> None:
    if daw_id is None:
        return
    row = await conn.fetchrow(
        "SELECT owner_id FROM daws WHERE id = $1::uuid",
        daw_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="daw_id not found")
    d_oid = row["owner_id"]
    if principal["kind"] == "owner":
        return
    if d_oid is None:
        return
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="daw_not_allowed")
    if principal["kind"] == "member" and d_oid == principal["user_id"]:
        return
    raise HTTPException(status_code=403, detail="daw_not_allowed")


def persona_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    if principal["kind"] == "owner":
        return True
    if owner_id is None:
        return True
    if principal["kind"] == "member":
        return owner_id == principal["user_id"]
    return False


def daw_row_visible(principal: dict[str, Any], owner_id: Any) -> bool:
    return persona_row_visible(principal, owner_id)


async def fetch_daw_if_visible(
    conn: asyncpg.Connection,
    principal: dict[str, Any],
    daw_id: uuid.UUID,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, owner_id FROM daws WHERE id = $1::uuid",
        daw_id,
    )
    if row is None or not daw_row_visible(principal, row["owner_id"]):
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
    p_oid = row["owner_id"]
    if principal["kind"] == "owner":
        return row
    if p_oid is None:
        raise HTTPException(status_code=403, detail="cannot_modify_global_persona")
    if principal["kind"] != "member" or p_oid != principal["user_id"]:
        raise HTTPException(status_code=403, detail="persona_not_allowed")
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
    d_oid = row["owner_id"]
    if principal["kind"] == "owner":
        return row
    if d_oid is None:
        raise HTTPException(status_code=403, detail="cannot_modify_global_daw")
    if principal["kind"] != "member" or d_oid != principal["user_id"]:
        raise HTTPException(status_code=403, detail="daw_not_allowed")
    return row
