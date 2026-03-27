"""Login, JWT session, and account profile (/api/auth)."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from auth_deps import (
    create_access_token,
    get_current_user,
    pwd_context,
    require_db_account,
    verify_owner_password,
)
from db import get_pool

router = APIRouter()

USER_PROFILE_ICONS = Path("/data/branding/user_icons")
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ProfilePatch(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_emoji: str | None = None
    clear_icon: bool | None = None


class PasswordChangeBody(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


def _delete_stored_user_icon(user_id: uuid.UUID) -> None:
    USER_PROFILE_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(user_id)
    for p in USER_PROFILE_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


def _me_payload(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") == "owner":
        return {"role": "owner"}
    if user.get("role") in ("member", "super_admin"):
        icon = user.get("icon_url")
        return {
            "role": user["role"],
            "user_id": str(user["user_id"]),
            "username": user.get("username") or "",
            "display_name": user.get("display_name") or user.get("username") or "",
            "bio": user.get("bio") or "",
            "avatar_emoji": (user.get("avatar_emoji") or "").strip(),
            "icon_url": icon,
        }
    raise HTTPException(status_code=401, detail="not_authenticated")


@router.post("/login")
async def login(body: LoginBody):
    uname = body.username.strip()
    if uname.lower() == "owner":
        if not verify_owner_password(body.password):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        token = create_access_token(sub="owner", role="owner")
        return {"access_token": token, "token_type": "bearer"}

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash, role FROM users WHERE lower(username) = lower($1)",
            uname,
        )
    if row is None or not pwd_context.verify(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    db_role = row["role"]
    if db_role not in ("member", "super_admin"):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    token = create_access_token(sub=str(row["id"]), role=db_role)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
async def logout():
    return {"ok": True}


@router.get("/me")
async def me(user: dict[str, Any] | None = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return _me_payload(user)


@router.patch("/profile")
async def patch_profile(body: ProfilePatch, user: dict[str, Any] = Depends(require_db_account)):
    uid = user["user_id"]
    data = body.model_dump(exclude_unset=True)
    clear_icon = bool(data.pop("clear_icon", None))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT display_name, bio, avatar_emoji, icon_url
            FROM users WHERE id = $1::uuid
            """,
            uid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        new_name = data.get("display_name", row["display_name"])
        new_bio = data.get("bio", row["bio"])
        new_emoji = data.get("avatar_emoji", row["avatar_emoji"])
        new_icon = row["icon_url"]
        if clear_icon:
            _delete_stored_user_icon(uid)
            new_icon = None
        if isinstance(new_name, str):
            new_name = new_name.strip() or user.get("username") or "User"
        if isinstance(new_bio, str):
            new_bio = new_bio
        else:
            new_bio = row["bio"] or ""
        if isinstance(new_emoji, str):
            new_emoji = new_emoji.strip()
        else:
            new_emoji = (row["avatar_emoji"] or "").strip()

        updated = await conn.fetchrow(
            """
            UPDATE users
            SET display_name = $2, bio = $3, avatar_emoji = $4, icon_url = $5
            WHERE id = $1::uuid
            RETURNING id, username, role, display_name, bio, icon_url, avatar_emoji
            """,
            uid,
            new_name,
            new_bio,
            new_emoji,
            new_icon,
        )
    assert updated is not None
    u = {
        "role": updated["role"],
        "user_id": updated["id"],
        "username": updated["username"],
        "display_name": (updated["display_name"] or updated["username"] or "").strip(),
        "bio": updated["bio"] or "",
        "icon_url": updated["icon_url"],
        "avatar_emoji": (updated["avatar_emoji"] or "👤").strip(),
    }
    return _me_payload(u)


@router.post("/profile/icon")
async def upload_profile_icon(
    user: dict[str, Any] = Depends(require_db_account),
    file: UploadFile = File(...),
):
    uid = user["user_id"]
    orig = (file.filename or "").strip()
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_ICON_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Allowed icon extensions: {', '.join(sorted(ALLOWED_ICON_EXT))}",
        )
    _delete_stored_user_icon(uid)
    USER_PROFILE_ICONS.mkdir(parents=True, exist_ok=True)
    dest = USER_PROFILE_ICONS / f"{uid}{ext}"
    dest.write_bytes(await file.read())
    icon_url = "/api/auth/profile/icon-asset"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET icon_url = $2 WHERE id = $1::uuid",
            uid,
            icon_url,
        )
        row = await conn.fetchrow(
            """
            SELECT id, username, role, display_name, bio, icon_url, avatar_emoji
            FROM users WHERE id = $1::uuid
            """,
            uid,
        )
    assert row is not None
    u = {
        "role": row["role"],
        "user_id": row["id"],
        "username": row["username"],
        "display_name": (row["display_name"] or row["username"] or "").strip(),
        "bio": row["bio"] or "",
        "icon_url": row["icon_url"],
        "avatar_emoji": (row["avatar_emoji"] or "👤").strip(),
    }
    return _me_payload(u)


@router.get("/profile/icon-asset")
async def serve_profile_icon(user: dict[str, Any] | None = Depends(get_current_user)):
    if not user or user.get("role") not in ("member", "super_admin"):
        raise HTTPException(status_code=401, detail="not_authenticated")
    uid = user["user_id"]
    USER_PROFILE_ICONS.mkdir(parents=True, exist_ok=True)
    matches = list(USER_PROFILE_ICONS.glob(f"{uid}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = matches[0]
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")


@router.patch("/profile/password")
async def change_own_password(body: PasswordChangeBody, user: dict[str, Any] = Depends(require_db_account)):
    uid = user["user_id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password_hash FROM users WHERE id = $1::uuid",
            uid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        if not pwd_context.verify(body.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="current_password_invalid")
        new_hash = pwd_context.hash(body.new_password)
        await conn.execute(
            "UPDATE users SET password_hash = $2 WHERE id = $1::uuid",
            uid,
            new_hash,
        )
    return {"ok": True}
