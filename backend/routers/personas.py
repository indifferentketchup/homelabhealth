"""Personas CRUD: single-user; defaults per app via `is_default_booops` / `is_default_808notes`."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from auth_deps import get_principal, require_admin
from db import get_pool

router = APIRouter()

BRANDING_PERSONA_ICONS = Path("/data/branding/persona_icons")
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class PersonaCreate(BaseModel):
    name: str = Field(..., min_length=1)
    system_prompt: str = ""
    avatar_emoji: str = "🤖"


class PersonaUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    avatar_emoji: str | None = None
    is_default_booops: bool | None = None
    is_default_808notes: bool | None = None
    is_default_boocode: bool | None = None
    icon_url: str | None = None


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "icon_url": r["icon_url"],
        "system_prompt": r["system_prompt"] or "",
        "is_default_booops": bool(r["is_default_booops"]),
        "is_default_808notes": bool(r["is_default_808notes"]),
        "is_default_boocode": bool(r["is_default_boocode"]),
        "avatar_emoji": r["avatar_emoji"] or "🤖",
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "owner_id": str(r["owner_id"]) if r.get("owner_id") else None,
    }


def _delete_stored_persona_icon(persona_id: uuid.UUID) -> None:
    BRANDING_PERSONA_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(persona_id)
    for p in BRANDING_PERSONA_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


@router.get("/")
async def list_personas(_: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, icon_url, system_prompt, avatar_emoji,
                   is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
            FROM personas
            ORDER BY is_default_booops DESC, is_default_808notes DESC, is_default_boocode DESC, created_at ASC NULLS LAST
            """,
        )
    return {"items": [_row(r) for r in rows]}


@router.post("/")
async def create_persona(body: PersonaCreate, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO personas (
                name, system_prompt, avatar_emoji,
                is_default_booops, is_default_808notes, is_default_boocode,
                owner_id, default_model
            )
            VALUES ($1, $2, $3, FALSE, FALSE, FALSE, $4, NULL)
            RETURNING id, name, icon_url, system_prompt, avatar_emoji,
                      is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
            """,
            body.name.strip(),
            body.system_prompt or "",
            (body.avatar_emoji or "🤖").strip() or "🤖",
            principal["user_id"],
        )
    return _row(row)


@router.post("/{persona_id}/set-default")
async def set_default_persona(
    persona_id: uuid.UUID,
    slot: str = Query("booops"),
    _admin: dict[str, Any] = Depends(require_admin),
):
    m = slot if slot in ("booops", "808notes", "boocode") else "booops"
    col = {
        "booops": "is_default_booops",
        "808notes": "is_default_808notes",
        "boocode": "is_default_boocode",
    }[m]
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await conn.fetchval("SELECT 1 FROM personas WHERE id = $1::uuid", persona_id)
        if ok is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        async with conn.transaction():
            await conn.execute(
                f"UPDATE personas SET {col} = FALSE WHERE id <> $1::uuid",
                persona_id,
            )
            await conn.execute(
                f"UPDATE personas SET {col} = TRUE WHERE id = $1::uuid",
                persona_id,
            )
        row = await conn.fetchrow(
            """
            SELECT id, name, icon_url, system_prompt, avatar_emoji,
                   is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
            FROM personas WHERE id = $1::uuid
            """,
            persona_id,
        )
    return _row(row)


@router.get("/{persona_id}")
async def get_persona(persona_id: uuid.UUID, _: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, icon_url, system_prompt, avatar_emoji,
                   is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
            FROM personas
            WHERE id = $1::uuid
            """,
            persona_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return _row(row)


@router.post("/{persona_id}/icon")
async def upload_persona_icon(
    persona_id: uuid.UUID,
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM personas WHERE id = $1::uuid", persona_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Persona not found")

    orig = (file.filename or "").strip()
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_ICON_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Allowed icon extensions: {', '.join(sorted(ALLOWED_ICON_EXT))}",
        )

    _delete_stored_persona_icon(persona_id)
    BRANDING_PERSONA_ICONS.mkdir(parents=True, exist_ok=True)
    dest = BRANDING_PERSONA_ICONS / f"{persona_id}{ext}"
    dest.write_bytes(await file.read())

    icon_url = f"/api/personas/{persona_id}/icon-asset"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE personas SET icon_url = $2, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, name, icon_url, system_prompt, avatar_emoji,
                      is_default_booops, is_default_808notes, created_at, owner_id
            """,
            persona_id,
            icon_url,
        )
    return _row(row)


@router.get("/{persona_id}/icon-asset")
async def serve_persona_icon(persona_id: uuid.UUID):
    BRANDING_PERSONA_ICONS.mkdir(parents=True, exist_ok=True)
    matches = list(BRANDING_PERSONA_ICONS.glob(f"{persona_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = matches[0]
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")


@router.put("/{persona_id}")
async def update_persona(
    persona_id: uuid.UUID,
    body: PersonaUpdate,
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, icon_url, system_prompt, avatar_emoji,
                   is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
            FROM personas
            WHERE id = $1::uuid
            """,
            persona_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        if not data:
            return _row(row)

        new_name = data.get("name", row["name"])
        new_prompt = data.get("system_prompt", row["system_prompt"])
        new_emoji = data.get("avatar_emoji", row["avatar_emoji"])
        new_booops = data.get("is_default_booops", row["is_default_booops"])
        new_808 = data.get("is_default_808notes", row["is_default_808notes"])
        new_boocode = data.get("is_default_boocode", row["is_default_boocode"])
        new_icon = row["icon_url"]
        if "icon_url" in data and data["icon_url"] is None:
            _delete_stored_persona_icon(persona_id)
            new_icon = None

        if isinstance(new_name, str):
            new_name = new_name.strip() or row["name"]
        if isinstance(new_prompt, str):
            new_prompt = new_prompt or ""
        if isinstance(new_emoji, str):
            new_emoji = new_emoji.strip() or "🤖"

        async with conn.transaction():
            if new_booops is True:
                await conn.execute(
                    "UPDATE personas SET is_default_booops = FALSE WHERE id <> $1::uuid",
                    persona_id,
                )
            if new_808 is True:
                await conn.execute(
                    "UPDATE personas SET is_default_808notes = FALSE WHERE id <> $1::uuid",
                    persona_id,
                )
            if new_boocode is True:
                await conn.execute(
                    "UPDATE personas SET is_default_boocode = FALSE WHERE id <> $1::uuid",
                    persona_id,
                )
            updated = await conn.fetchrow(
                """
                UPDATE personas
                SET name = $2, system_prompt = $3, avatar_emoji = $4,
                    is_default_booops = $5, is_default_808notes = $6, is_default_boocode = $7,
                    icon_url = $8, updated_at = NOW()
                WHERE id = $1::uuid
                RETURNING id, name, icon_url, system_prompt, avatar_emoji,
                          is_default_booops, is_default_808notes, is_default_boocode, created_at, owner_id
                """,
                persona_id,
                new_name,
                new_prompt,
                new_emoji,
                bool(new_booops),
                bool(new_808),
                bool(new_boocode),
                new_icon,
            )
    return _row(updated)


@router.delete("/{persona_id}")
async def delete_persona(persona_id: uuid.UUID, _: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, is_default_booops, is_default_808notes, is_default_boocode
            FROM personas WHERE id = $1::uuid
            """,
            persona_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        if row["is_default_booops"] or row["is_default_808notes"] or row["is_default_boocode"]:
            raise HTTPException(status_code=400, detail="Cannot delete a default persona for BooOps, 808notes, or BooCode")
        await conn.execute("DELETE FROM personas WHERE id = $1::uuid", persona_id)
    return {"ok": True}
