"""Profile endpoints for the single-user samkintop account. Authelia handles auth upstream."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth_deps import get_principal
from db import get_pool

router = APIRouter()

USER_PROFILE_ICONS = Path("/data/branding/user_icons")
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ProfilePatch(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_emoji: str | None = None
    clear_icon: bool | None = None


def _delete_stored_user_icon(user_id: uuid.UUID) -> None:
    USER_PROFILE_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(user_id)
    for p in USER_PROFILE_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


def _me_payload(row: Any, user_id: uuid.UUID) -> dict[str, Any]:
    return {
        "role": "owner",
        "user_id": str(user_id),
        "username": row["username"],
        "display_name": (row["display_name"] or row["username"] or "").strip() or row["username"],
        "bio": row["bio"] or "",
        "avatar_emoji": (row["avatar_emoji"] or "").strip(),
        "icon_url": row["icon_url"],
    }


@router.get("/me")
async def me(principal: dict[str, Any] = Depends(get_principal)):
    uid = principal["user_id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT username, display_name, bio, icon_url, avatar_emoji
            FROM users WHERE id = $1::uuid
            """,
            uid,
        )
    if row is None:
        raise HTTPException(status_code=503, detail="owner_user_missing")
    return _me_payload(row, uid)


@router.patch("/profile")
async def patch_profile(body: ProfilePatch, principal: dict[str, Any] = Depends(get_principal)):
    uid = principal["user_id"]
    data = body.model_dump(exclude_unset=True)
    clear_icon = bool(data.pop("clear_icon", None))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT username, display_name, bio, avatar_emoji, icon_url
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
            new_name = new_name.strip() or row["username"]
        if not isinstance(new_bio, str):
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
            RETURNING username, display_name, bio, icon_url, avatar_emoji
            """,
            uid,
            new_name,
            new_bio,
            new_emoji,
            new_icon,
        )
    assert updated is not None
    return _me_payload(updated, uid)


@router.post("/profile/icon")
async def upload_profile_icon(
    file: UploadFile = File(...),
    principal: dict[str, Any] = Depends(get_principal),
):
    uid = principal["user_id"]
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
            SELECT username, display_name, bio, icon_url, avatar_emoji
            FROM users WHERE id = $1::uuid
            """,
            uid,
        )
    assert row is not None
    return _me_payload(row, uid)


@router.get("/profile/icon-asset")
async def serve_profile_icon(principal: dict[str, Any] = Depends(get_principal)):
    uid = principal["user_id"]
    USER_PROFILE_ICONS.mkdir(parents=True, exist_ok=True)
    matches = list(USER_PROFILE_ICONS.glob(f"{uid}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = matches[0]
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")
