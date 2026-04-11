"""DAWs (`daws` table): project cards, prompt context, icons, instructions, pins."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from auth_deps import (
    assert_daw_mutable,
    assert_persona_usable,
    daw_row_visible,
    fetch_daw_if_visible,
    get_principal,
)
from db import get_pool

router = APIRouter()

BRANDING_DAW_ICONS = Path("/data/branding/daw_icons")
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _norm_mode(m: str | None) -> str:
    if m is None:
        return "booops"
    return m if m in ("booops", "808notes") else "booops"


class DawCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1)
    description: str | None = None
    system_prompt: str = ""
    persona_id: uuid.UUID | None = None
    mode: str = "booops"
    color: str = "#7c3aed"
    shared: bool = False
    sort_order: int = 0
    daw_model: str | None = Field(default=None, alias="model")
    dubdrive_sync_folder: str | None = None
    dubdrive_sync_enabled: bool = False
    rag_mode: Literal["auto", "always", "off"] | None = None


class DawUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    persona_id: uuid.UUID | None = None
    mode: str | None = None
    color: str | None = None
    shared: bool | None = None
    sort_order: int | None = None
    icon_url: str | None = None
    daw_model: str | None = Field(default=None, alias="model")
    dubdrive_sync_folder: str | None = None
    dubdrive_sync_enabled: bool = False
    rag_mode: Literal["auto", "always", "off"] | None = None


class DawPinBody(BaseModel):
    slot: Literal["booops", "808notes"]
    pinned: bool


class DawInstructionsBody(BaseModel):
    content: str = ""


def _row(r: Any) -> dict[str, Any]:
    pn = r.get("persona_name")
    m = r.get("model")
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r["description"] or "",
        "system_prompt": r["system_prompt"] or "",
        "persona_id": str(r["persona_id"]) if r["persona_id"] else None,
        "persona_name": pn,
        "mode": r["mode"],
        "color": r["color"] or "#7c3aed",
        "shared": bool(r["shared"]),
        "sort_order": int(r["sort_order"] or 0),
        "pinned_booops": bool(r["pinned_booops"]),
        "pinned_808notes": bool(r["pinned_808notes"]),
        "icon_url": r["icon_url"],
        "model": (str(m).strip() if m else None) or None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "owner_id": str(r["owner_id"]) if r.get("owner_id") else None,
        "dubdrive_sync_folder": r.get("dubdrive_sync_folder"),
        "dubdrive_sync_enabled": bool(r.get("dubdrive_sync_enabled")),
        "dubdrive_last_synced_at": r["dubdrive_last_synced_at"].isoformat()
        if r.get("dubdrive_last_synced_at")
        else None,
        "rag_mode": cast(
            Literal["auto", "always", "off"],
            (
                "always"
                if r.get("mode") == "808notes"
                else (
                    str(r["rag_mode"])
                    if r.get("rag_mode") in ("auto", "always", "off")
                    else "auto"
                )
            ),
        ),
    }


def _delete_stored_icon(daw_id: uuid.UUID) -> None:
    BRANDING_DAW_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(daw_id)
    for p in BRANDING_DAW_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


def _icon_path_for_daw(daw_id: uuid.UUID, ext: str) -> Path:
    return BRANDING_DAW_ICONS / f"{daw_id}{ext}"


async def _ensure_persona(conn: Any, persona_id: uuid.UUID | None) -> None:
    if persona_id is None:
        return
    ok = await conn.fetchval("SELECT 1 FROM personas WHERE id = $1::uuid", persona_id)
    if ok is None:
        raise HTTPException(status_code=400, detail="persona_id not found")


@router.get("/")
async def list_daws(
    mode: str | None = Query(None),
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    m = _norm_mode(mode) if mode is not None else None
    sel = """
                SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                    d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                    d.model, d.rag_mode,
                    d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                    d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
                FROM daws d
                LEFT JOIN personas p ON p.id = d.persona_id
            """
    async with pool.acquire() as conn:
        if principal["kind"] == "owner":
            if m is None:
                rows = await conn.fetch(
                    sel + " ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                )
            else:
                rows = await conn.fetch(
                    sel + " WHERE d.mode = $1 ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                    m,
                )
        elif principal["kind"] == "guest":
            if m is None:
                rows = await conn.fetch(
                    sel + " WHERE d.owner_id IS NULL ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                )
            else:
                rows = await conn.fetch(
                    sel + " WHERE d.mode = $1 AND d.owner_id IS NULL ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                    m,
                )
        else:
            uid = principal["user_id"]
            if m is None:
                rows = await conn.fetch(
                    sel + " WHERE (d.owner_id IS NULL OR d.owner_id = $1::uuid) ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                    uid,
                )
            else:
                rows = await conn.fetch(
                    sel + " WHERE d.mode = $1 AND (d.owner_id IS NULL OR d.owner_id = $2::uuid) ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
                    m,
                    uid,
                )
    return {"items": [_row(r) for r in rows]}


@router.post("/")
async def create_daw(body: DawCreate, principal: dict[str, Any] = Depends(get_principal)):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    mo = _norm_mode(body.mode)
    pool = await get_pool()
    owner_uuid = None
    async with pool.acquire() as conn:
        if principal["kind"] == "member":
            n = await conn.fetchval(
                "SELECT COUNT(*)::int FROM daws WHERE owner_id = $1::uuid AND mode = $2",
                principal["user_id"],
                mo,
            )
            if int(n or 0) >= 2:
                raise HTTPException(status_code=429, detail="daw_limit_reached")
            owner_uuid = principal["user_id"]
        await assert_persona_usable(conn, principal, body.persona_id)
        await _ensure_persona(conn, body.persona_id)
        ins_model = (body.daw_model or "").strip() or None
        if mo == "808notes":
            rag_ins: Literal["auto", "always", "off"] = "always"
        else:
            br = body.rag_mode
            rag_ins = br if br in ("auto", "always", "off") else "auto"
        row = await conn.fetchrow(
            """
            INSERT INTO daws (
                name, description, system_prompt, persona_id, mode, color, shared, sort_order,
                model, rag_mode, owner_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id, name, description, icon_url, color, shared, sort_order,
                pinned_booops, pinned_808notes, system_prompt, persona_id, mode,
                model, rag_mode,
                dubdrive_sync_folder, dubdrive_sync_enabled, dubdrive_last_synced_at,
                created_at, updated_at, owner_id
            """,
            body.name.strip(),
            body.description,
            body.system_prompt or "",
            body.persona_id,
            mo,
            body.color or "#7c3aed",
            body.shared,
            body.sort_order,
            ins_model,
            rag_ins,
            owner_uuid,
        )
        prow = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            row["id"],
        )
    return _row(prow)


@router.get("/{daw_id}/instructions")
async def get_daw_instructions(
    daw_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await fetch_daw_if_visible(conn, principal, daw_id)
        row = await conn.fetchrow(
            """
            SELECT content FROM daw_instructions
            WHERE daw_id = $1::uuid
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            daw_id,
        )
    return {"content": (row["content"] or "") if row else ""}


@router.put("/{daw_id}/instructions")
async def put_daw_instructions(
    daw_id: uuid.UUID,
    body: DawInstructionsBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await assert_daw_mutable(conn, principal, daw_id)
        existing = await conn.fetchrow(
            "SELECT id FROM daw_instructions WHERE daw_id = $1::uuid LIMIT 1",
            daw_id,
        )
        if existing:
            await conn.execute(
                """
                UPDATE daw_instructions
                SET content = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                existing["id"],
                body.content or "",
            )
        else:
            await conn.execute(
                """
                INSERT INTO daw_instructions (daw_id, content)
                VALUES ($1::uuid, $2)
                """,
                daw_id,
                body.content or "",
            )
    return {"content": body.content or ""}


@router.post("/{daw_id}/icon")
async def upload_daw_icon(
    daw_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: dict[str, Any] = Depends(get_principal),
):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await assert_daw_mutable(conn, principal, daw_id)

    orig = (file.filename or "").strip()
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_ICON_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Allowed icon extensions: {', '.join(sorted(ALLOWED_ICON_EXT))}",
        )

    _delete_stored_icon(daw_id)
    BRANDING_DAW_ICONS.mkdir(parents=True, exist_ok=True)
    dest = _icon_path_for_daw(daw_id, ext)
    content = await file.read()
    dest.write_bytes(content)

    icon_url = f"/api/daws/{daw_id}/icon-asset"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE daws SET icon_url = $2, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            daw_id,
            icon_url,
        )
        prow = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            daw_id,
        )
    return _row(prow)


@router.get("/{daw_id}/icon-asset")
async def serve_daw_icon(daw_id: uuid.UUID):
    BRANDING_DAW_ICONS.mkdir(parents=True, exist_ok=True)
    matches = list(BRANDING_DAW_ICONS.glob(f"{daw_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = matches[0]
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")


@router.patch("/{daw_id}/pin")
async def patch_daw_pin(
    daw_id: uuid.UUID,
    body: DawPinBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await assert_daw_mutable(conn, principal, daw_id)
        if body.slot == "booops":
            await conn.execute(
                """
                UPDATE daws SET pinned_booops = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                daw_id,
                body.pinned,
            )
        else:
            await conn.execute(
                """
                UPDATE daws SET pinned_808notes = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                daw_id,
                body.pinned,
            )
        prow = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            daw_id,
        )
        if prow is None:
            raise HTTPException(status_code=404, detail="DAW not found")
    return _row(prow)


@router.get("/{daw_id}")
async def get_daw(daw_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            daw_id,
        )
    if row is None or not daw_row_visible(principal, row["owner_id"]):
        raise HTTPException(status_code=404, detail="DAW not found")
    return _row(row)


@router.patch("/{daw_id}")
async def patch_daw(
    daw_id: uuid.UUID,
    body: DawUpdate,
    principal: dict[str, Any] = Depends(get_principal),
):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        await assert_daw_mutable(conn, principal, daw_id)
        row = await conn.fetchrow(
            """
            SELECT id, name, description, icon_url, color, shared, sort_order,
                pinned_booops, pinned_808notes, system_prompt, persona_id, mode,
                model, rag_mode,
                dubdrive_sync_folder, dubdrive_sync_enabled, dubdrive_last_synced_at,
                created_at, updated_at, owner_id
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="DAW not found")
        if not data:
            prow = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            daw_id,
        )
            return _row(prow)

        new_name = data.get("name", row["name"])
        new_desc = data.get("description", row["description"])
        new_sp = data.get("system_prompt", row["system_prompt"])
        new_pid = row["persona_id"] if "persona_id" not in data else data["persona_id"]
        new_mode = _norm_mode(data["mode"]) if "mode" in data else row["mode"]
        new_color = data.get("color", row["color"])
        new_shared = data.get("shared", row["shared"])
        new_sort = data.get("sort_order", row["sort_order"])
        if "daw_model" in data:
            raw_m = data["daw_model"]
            new_model = None if raw_m is None or str(raw_m).strip() == "" else str(raw_m).strip()
        else:
            raw_rm = row["model"]
            new_model = None if raw_rm is None or str(raw_rm).strip() == "" else str(raw_rm).strip()
        cur_rm = row.get("rag_mode")
        if cur_rm not in ("auto", "always", "off"):
            cur_rm = "auto"
        new_rag = cast(Literal["auto", "always", "off"], cur_rm)
        if "rag_mode" in data and data["rag_mode"] is not None:
            cand = data["rag_mode"]
            if cand not in ("auto", "always", "off"):
                raise HTTPException(status_code=400, detail="invalid rag_mode")
            new_rag = cand
        if new_mode == "808notes":
            new_rag = "always"
        new_icon = row["icon_url"]
        if "icon_url" in data:
            if data["icon_url"] is None:
                _delete_stored_icon(daw_id)
                new_icon = None
            else:
                new_icon = data["icon_url"]
        if isinstance(new_name, str):
            new_name = new_name.strip() or row["name"]
        if isinstance(new_sp, str):
            new_sp = new_sp or ""

        await assert_persona_usable(conn, principal, new_pid)
        await _ensure_persona(conn, new_pid)

        await conn.execute(
            """
            UPDATE daws
            SET name = $2, description = $3, system_prompt = $4, persona_id = $5, mode = $6,
                color = $7, shared = $8, sort_order = $9, icon_url = $10, model = $11,
                dubdrive_sync_folder = $12, dubdrive_sync_enabled = $13, rag_mode = $14, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            daw_id,
            new_name,
            new_desc,
            new_sp,
            new_pid,
            new_mode,
            new_color,
            new_shared,
            new_sort,
            new_icon,
            new_model,
            new_dd_folder,
            new_dd_enabled,
            new_rag,
        )
        prow = await conn.fetchrow(
            """
            SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                d.pinned_booops, d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                d.model, d.rag_mode,
                d.dubdrive_sync_folder, d.dubdrive_sync_enabled, d.dubdrive_last_synced_at,
                d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
            FROM daws d
            LEFT JOIN personas p ON p.id = d.persona_id
            WHERE d.id = $1::uuid
            """,
            daw_id,
        )
    return _row(prow)


@router.delete("/{daw_id}")
async def delete_daw(daw_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    if principal["kind"] == "guest":
        raise HTTPException(status_code=403, detail="forbidden")
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(
            "SELECT owner_id FROM daws WHERE id = $1::uuid",
            daw_id,
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="DAW not found")
        if meta["owner_id"] is None:
            raise HTTPException(status_code=403, detail="cannot_delete_global_daw")
        if principal["kind"] == "member" and meta["owner_id"] != principal["user_id"]:
            raise HTTPException(status_code=403, detail="daw_not_allowed")
    _delete_stored_icon(daw_id)
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM daws WHERE id = $1::uuid", daw_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="DAW not found")
    return {"ok": True}
