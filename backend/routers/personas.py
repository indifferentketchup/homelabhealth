"""Personas CRUD: separate lists per app mode (booops / 808notes), each with its own default."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from db import get_pool

router = APIRouter()

BRANDING_PERSONA_ICONS = Path("/data/branding/persona_icons")
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class PersonaCreate(BaseModel):
    mode: str = "booops"
    name: str = Field(..., min_length=1)
    system_prompt: str = ""
    avatar_emoji: str = "🤖"


class PersonaUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    avatar_emoji: str | None = None
    is_default: bool | None = None
    icon_url: str | None = None


def _norm_mode(m: str) -> str:
    return m if m in ("booops", "808notes") else "booops"


def _row(r: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(r["id"]),
        "name": r["name"],
        "icon_url": r["icon_url"],
        "system_prompt": r["system_prompt"] or "",
        "is_default": bool(r["is_default"]),
        "avatar_emoji": r["avatar_emoji"] or "🤖",
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }
    if r.get("mode") is not None:
        out["mode"] = r["mode"]
    return out


def _delete_stored_persona_icon(persona_id: uuid.UUID) -> None:
    BRANDING_PERSONA_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(persona_id)
    for p in BRANDING_PERSONA_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


@router.get("/")
async def list_personas(mode: str = Query("booops")):
    m = _norm_mode(mode)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
            FROM personas
            WHERE mode = $1::text
            ORDER BY is_default DESC, created_at ASC
            """,
            m,
        )
    return {"items": [_row(r) for r in rows]}


@router.post("/")
async def create_persona(body: PersonaCreate):
    m = _norm_mode(body.mode)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO personas (name, system_prompt, avatar_emoji, is_default, mode)
            VALUES ($1, $2, $3, FALSE, $4::text)
            RETURNING id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
            """,
            body.name.strip(),
            body.system_prompt or "",
            (body.avatar_emoji or "🤖").strip() or "🤖",
            m,
        )
    return _row(row)


@router.get("/{persona_id}")
async def get_persona(persona_id: uuid.UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
            FROM personas
            WHERE id = $1::uuid
            """,
            persona_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return _row(row)


@router.post("/{persona_id}/icon")
async def upload_persona_icon(persona_id: uuid.UUID, file: UploadFile = File(...)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM personas WHERE id = $1::uuid", persona_id)
        if exists is None:
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
            RETURNING id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
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
async def update_persona(persona_id: uuid.UUID, body: PersonaUpdate):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
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
        new_default = data.get("is_default", row["is_default"])
        new_icon = row["icon_url"]
        if "icon_url" in data and data["icon_url"] is None:
            _delete_stored_persona_icon(persona_id)
            new_icon = None

        if isinstance(new_name, str):
            new_name = new_name.strip() or row["name"]
        if isinstance(new_prompt, str):
            new_prompt = new_prompt or ""
        if isinstance(new_emoji, str):
            new_emoji = (new_emoji.strip() or "🤖")

        async with conn.transaction():
            if new_default is True:
                await conn.execute(
                    """
                    UPDATE personas SET is_default = FALSE
                    WHERE mode = $2::text AND id <> $1::uuid
                    """,
                    persona_id,
                    row["mode"],
                )
            updated = await conn.fetchrow(
                """
                UPDATE personas
                SET name = $2, system_prompt = $3, avatar_emoji = $4,
                    is_default = $5, icon_url = $6, updated_at = NOW()
                WHERE id = $1::uuid
                RETURNING id, name, icon_url, system_prompt, is_default, avatar_emoji, mode, created_at
                """,
                persona_id,
                new_name,
                new_prompt,
                new_emoji,
                bool(new_default),
                new_icon,
            )
    return _row(updated)


@router.delete("/{persona_id}")
async def delete_persona(persona_id: uuid.UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, is_default FROM personas WHERE id = $1::uuid",
            persona_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        if row["is_default"]:
            raise HTTPException(status_code=400, detail="Cannot delete the default persona for this mode")
        await conn.execute("DELETE FROM personas WHERE id = $1::uuid", persona_id)
    return {"ok": True}
