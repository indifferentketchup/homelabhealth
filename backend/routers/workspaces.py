"""Workspaces (`daws` table): project cards, prompt context, icons, instructions, pins."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from deps import _SCHEMA_MODE_VALUE, get_principal
from db import get_pool

router = APIRouter()

BRANDING_WORKSPACE_ICONS = Path("/data/branding/daw_icons")

# Common SELECT used by single-workspace fetch/return paths (create, get, patch, pin, upload-icon).
# list_workspaces uses a wider variant that includes repo_* columns.
DAWS_SELECT = """
    SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
        d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
        d.model, d.rag_mode,
        d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
    FROM daws d
    LEFT JOIN personas p ON p.id = d.persona_id
"""
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# dubdrive_* DB columns retained but not exposed via API
class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1)
    description: str | None = None
    system_prompt: str = ""
    persona_id: uuid.UUID | None = None
    color: str = "#7c3aed"
    shared: bool = False
    sort_order: int = 0
    workspace_model: str | None = Field(default=None, alias="model")
    rag_mode: Literal["auto", "always", "off"] | None = None


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    persona_id: uuid.UUID | None = None
    color: str | None = None
    shared: bool | None = None
    sort_order: int | None = None
    icon_url: str | None = None
    workspace_model: str | None = Field(default=None, alias="model")
    rag_mode: Literal["auto", "always", "off"] | None = None


class WorkspacePinBody(BaseModel):
    pinned: bool


class WorkspaceInstructionsBody(BaseModel):
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
        "pinned": bool(r["pinned_808notes"]),
        "icon_url": r["icon_url"],
        "model": (str(m).strip() if m else None) or None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "owner_id": str(r["owner_id"]) if r.get("owner_id") else None,
        "repo_path": r.get("repo_path"),
        "repo_branch": r.get("repo_branch") or "main",
        "repo_auto_sync": bool(r.get("repo_auto_sync")),
        "repo_sync_status": r.get("repo_sync_status") or "idle",
        "repo_last_synced_at": r["repo_last_synced_at"].isoformat()
        if r.get("repo_last_synced_at")
        else None,
        "repo_file_count": int(r.get("repo_file_count") or 0),
        "repo_chunk_count": int(r.get("repo_chunk_count") or 0),
        "rag_mode": cast(
            Literal["auto", "always", "off"],
            "always",
        ),
    }


def _delete_stored_icon(workspace_id: uuid.UUID) -> None:
    BRANDING_WORKSPACE_ICONS.mkdir(parents=True, exist_ok=True)
    sid = str(workspace_id)
    for p in BRANDING_WORKSPACE_ICONS.glob(f"{sid}.*"):
        try:
            p.unlink()
        except OSError:
            pass


def _icon_path_for_workspace(workspace_id: uuid.UUID, ext: str) -> Path:
    return BRANDING_WORKSPACE_ICONS / f"{workspace_id}{ext}"


async def _ensure_persona(conn: Any, persona_id: uuid.UUID | None) -> None:
    if persona_id is None:
        return
    ok = await conn.fetchval("SELECT 1 FROM personas WHERE id = $1::uuid", persona_id)
    if ok is None:
        raise HTTPException(status_code=400, detail="persona_id not found")


@router.get("/")
async def list_workspaces(
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    sel = """
                SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                    d.pinned_808notes, d.system_prompt, d.persona_id, d.mode,
                    d.model, d.rag_mode,
                    d.repo_path, d.repo_branch, d.repo_auto_sync, d.repo_sync_status,
                    d.repo_last_synced_at, d.repo_file_count, d.repo_chunk_count,
                    d.created_at, d.updated_at, d.owner_id, p.name AS persona_name
                FROM daws d
                LEFT JOIN personas p ON p.id = d.persona_id
            """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            sel + " ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
        )
    return {"items": [_row(r) for r in rows]}


@router.post("/")
async def create_workspace(body: WorkspaceCreate, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_persona(conn, body.persona_id)
        ins_model = (body.workspace_model or "").strip() or None
        rag_ins: Literal["auto", "always", "off"] = "always"
        row = await conn.fetchrow(
            """
            INSERT INTO daws (
                name, description, system_prompt, persona_id, mode, color, shared, sort_order,
                model, rag_mode, owner_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id, name, description, icon_url, color, shared, sort_order,
                pinned_808notes, system_prompt, persona_id, mode,
                model, rag_mode,
                repo_path, repo_branch, repo_auto_sync, repo_sync_status,
                repo_last_synced_at, repo_file_count, repo_chunk_count,
                created_at, updated_at, owner_id
            """,
            body.name.strip(),
            body.description,
            body.system_prompt or "",
            body.persona_id,
            _SCHEMA_MODE_VALUE,
            body.color or "#7c3aed",
            body.shared,
            body.sort_order,
            ins_model,
            rag_ins,
            principal["user_id"],
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            row["id"],
        )
    return _row(prow)


@router.get("/{workspace_id}/instructions")
async def get_workspace_instructions(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row = await conn.fetchrow(
            """
            SELECT content FROM daw_instructions
            WHERE daw_id = $1::uuid
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            workspace_id,
        )
    return {"content": (row["content"] or "") if row else ""}


@router.put("/{workspace_id}/instructions")
async def put_workspace_instructions(
    workspace_id: uuid.UUID,
    body: WorkspaceInstructionsBody,
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        existing = await conn.fetchrow(
            "SELECT id FROM daw_instructions WHERE daw_id = $1::uuid LIMIT 1",
            workspace_id,
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
                workspace_id,
                body.content or "",
            )
    return {"content": body.content or ""}


@router.post("/{workspace_id}/icon")
async def upload_workspace_icon(
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")

    orig = (file.filename or "").strip()
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_ICON_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Allowed icon extensions: {', '.join(sorted(ALLOWED_ICON_EXT))}",
        )

    _delete_stored_icon(workspace_id)
    BRANDING_WORKSPACE_ICONS.mkdir(parents=True, exist_ok=True)
    dest = _icon_path_for_workspace(workspace_id, ext)
    content = await file.read()
    dest.write_bytes(content)

    icon_url = f"/api/workspaces/{workspace_id}/icon-asset"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE daws SET icon_url = $2, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
            icon_url,
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    return _row(prow)


@router.get("/{workspace_id}/icon-asset")
async def serve_workspace_icon(workspace_id: uuid.UUID):
    BRANDING_WORKSPACE_ICONS.mkdir(parents=True, exist_ok=True)
    matches = list(BRANDING_WORKSPACE_ICONS.glob(f"{workspace_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = matches[0]
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")


@router.patch("/{workspace_id}/pin")
async def patch_workspace_pin(
    workspace_id: uuid.UUID,
    body: WorkspacePinBody,
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        await conn.execute(
            """
            UPDATE daws SET pinned_808notes = $2, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
            body.pinned,
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
        if prow is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return _row(prow)


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: uuid.UUID, _: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _row(row)


@router.patch("/{workspace_id}")
async def patch_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    _: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, description, icon_url, color, shared, sort_order,
                pinned_808notes, system_prompt, persona_id, mode,
                model, rag_mode,
                created_at, updated_at, owner_id
            FROM daws WHERE id = $1::uuid
            """,
            workspace_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if not data:
            prow = await conn.fetchrow(
                DAWS_SELECT + "WHERE d.id = $1::uuid",
                workspace_id,
            )
            return _row(prow)

        new_name = data.get("name", row["name"])
        new_desc = data.get("description", row["description"])
        new_sp = data.get("system_prompt", row["system_prompt"])
        new_pid = row["persona_id"] if "persona_id" not in data else data["persona_id"]
        new_mode = row["mode"]
        new_color = data.get("color", row["color"])
        new_shared = data.get("shared", row["shared"])
        new_sort = data.get("sort_order", row["sort_order"])
        if "workspace_model" in data:
            raw_m = data["workspace_model"]
            new_model = None if raw_m is None or str(raw_m).strip() == "" else str(raw_m).strip()
        else:
            raw_rm = row["model"]
            new_model = None if raw_rm is None or str(raw_rm).strip() == "" else str(raw_rm).strip()
        new_rag: Literal["auto", "always", "off"] = "always"
        new_icon = row["icon_url"]
        if "icon_url" in data:
            if data["icon_url"] is None:
                _delete_stored_icon(workspace_id)
                new_icon = None
            else:
                new_icon = data["icon_url"]
        if isinstance(new_name, str):
            new_name = new_name.strip() or row["name"]
        if isinstance(new_sp, str):
            new_sp = new_sp or ""

        await _ensure_persona(conn, new_pid)

        await conn.execute(
            """
            UPDATE daws
            SET name = $2, description = $3, system_prompt = $4, persona_id = $5, mode = $6,
                color = $7, shared = $8, sort_order = $9, icon_url = $10, model = $11,
                rag_mode = $12, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
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
            new_rag,
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    return _row(prow)


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: uuid.UUID, _: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(
            "SELECT id FROM daws WHERE id = $1::uuid",
            workspace_id,
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    _delete_stored_icon(workspace_id)
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM daws WHERE id = $1::uuid", workspace_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"ok": True}
