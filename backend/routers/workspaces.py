"""Workspaces (`workspaces` table): project cards, prompt context, icons, instructions, pins."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from deps import get_principal
from db import get_pool
from services import bundled_providers
from services.audit import AuditEventHandle, audit_event

router = APIRouter()

BRANDING_WORKSPACE_ICONS = Path("/data/branding/daw_icons")

DAWS_SELECT = """
    SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
        d.pinned, d.system_prompt,
        d.model, d.rag_mode, d.provider_id,
        d.created_at, d.updated_at, d.owner_id
    FROM workspaces d
"""
ALLOWED_ICON_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# dubdrive_* DB columns retained but not exposed via API
class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1)
    description: str | None = None
    system_prompt: str = ""
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
    color: str | None = None
    shared: bool | None = None
    sort_order: int | None = None
    icon_url: str | None = None
    workspace_model: str | None = Field(default=None, alias="model")
    provider_id: uuid.UUID | None = None
    rag_mode: Literal["auto", "always", "off"] | None = None


class WorkspacePinBody(BaseModel):
    pinned: bool


class WorkspaceInstructionsBody(BaseModel):
    content: str = ""


def _row(r: Any) -> dict[str, Any]:
    m = r.get("model")
    pid = r.get("provider_id")
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "description": r["description"] or "",
        "system_prompt": r["system_prompt"] or "",
        "color": r["color"] or "#7c3aed",
        "shared": bool(r["shared"]),
        "sort_order": int(r["sort_order"] or 0),
        "pinned": bool(r["pinned"]),
        "icon_url": r["icon_url"],
        "model": (str(m).strip() if m else None) or None,
        "provider_id": str(pid) if pid else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "owner_id": str(r["owner_id"]) if r.get("owner_id") else None,
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


@router.get("/")
async def list_workspaces(
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    sel = """
                SELECT d.id, d.name, d.description, d.icon_url, d.color, d.shared, d.sort_order,
                    d.pinned, d.system_prompt,
                    d.model, d.rag_mode,
                    d.created_at, d.updated_at, d.owner_id
                FROM workspaces d
            """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            sel + " ORDER BY d.sort_order ASC NULLS LAST, d.name ASC",
        )
    async with audit.targeting("workspace", None):
        pass
    return {"items": [_row(r) for r in rows]}


@router.post("/")
async def create_workspace(
    body: WorkspaceCreate,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ins_model = (body.workspace_model or "").strip() or None
        rag_ins: Literal["auto", "always", "off"] = "always"
        row = await conn.fetchrow(
            """
            INSERT INTO workspaces (
                name, description, system_prompt, color, shared, sort_order,
                model, rag_mode, owner_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            body.name.strip(),
            body.description,
            body.system_prompt or "",
            body.color or "#7c3aed",
            body.shared,
            body.sort_order,
            ins_model,
            rag_ins,
            principal["user_id"],
        )
        # Bind the new workspace to the bundled chat provider when tier ≠ external.
        # apply_bundled_bindings is idempotent; it will pick up the just-created
        # workspace via its WHERE provider_id IS NULL UPDATE.
        profile_row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
        if profile_row is not None and profile_row["tier"] not in (None, "external", "apple-mlx"):
            await bundled_providers.apply_bundled_bindings(conn, profile_row["tier"])

        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            row["id"],
        )
    async with audit.targeting("workspace", row["id"]):
        pass
    return _row(prow)


@router.get("/{workspace_id}/instructions")
async def get_workspace_instructions(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row = await conn.fetchrow(
            """
            SELECT content FROM workspace_instructions
            WHERE workspace_id = $1::uuid
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            workspace_id,
        )
    async with audit.targeting("workspace", workspace_id):
        pass
    return {"content": (row["content"] or "") if row else ""}


@router.put("/{workspace_id}/instructions")
async def put_workspace_instructions(
    workspace_id: uuid.UUID,
    body: WorkspaceInstructionsBody,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        existing = await conn.fetchrow(
            "SELECT id FROM workspace_instructions WHERE workspace_id = $1::uuid LIMIT 1",
            workspace_id,
        )
        if existing:
            await conn.execute(
                """
                UPDATE workspace_instructions
                SET content = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                existing["id"],
                body.content or "",
            )
        else:
            await conn.execute(
                """
                INSERT INTO workspace_instructions (workspace_id, content)
                VALUES ($1::uuid, $2)
                """,
                workspace_id,
                body.content or "",
            )
    async with audit.targeting("workspace", workspace_id):
        pass
    return {"content": body.content or ""}


@router.post("/{workspace_id}/icon")
async def upload_workspace_icon(
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
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
            UPDATE workspaces SET icon_url = $2, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
            icon_url,
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    async with audit.targeting("workspace", workspace_id):
        pass
    return _row(prow)


@router.get("/{workspace_id}/icon-asset")
async def serve_workspace_icon(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
):
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
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        await conn.execute(
            """
            UPDATE workspaces SET pinned = $2, updated_at = NOW()
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
    async with audit.targeting("workspace", workspace_id):
        pass
    return _row(prow)


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    async with audit.targeting("workspace", workspace_id):
        pass
    return _row(row)


@router.patch("/{workspace_id}")
async def patch_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, description, icon_url, color, shared, sort_order,
                pinned, system_prompt,
                model, rag_mode, provider_id,
                created_at, updated_at, owner_id
            FROM workspaces WHERE id = $1::uuid
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
        new_color = data.get("color", row["color"])
        new_shared = data.get("shared", row["shared"])
        new_sort = data.get("sort_order", row["sort_order"])
        if "workspace_model" in data:
            raw_m = data["workspace_model"]
            new_model = None if raw_m is None or str(raw_m).strip() == "" else str(raw_m).strip()
        else:
            raw_rm = row["model"]
            new_model = None if raw_rm is None or str(raw_rm).strip() == "" else str(raw_rm).strip()
        # provider_id: same exclude_unset semantics — absent = preserve.
        if "provider_id" in data:
            new_provider_id = data["provider_id"]  # uuid.UUID | None
        else:
            new_provider_id = row["provider_id"]
        # Validate the (provider_id, model) pair before hitting the DB so we
        # return a clean 400 instead of a CheckViolationError.
        if (new_provider_id is None) != (new_model is None):
            raise HTTPException(
                status_code=400,
                detail="provider_id and model must both be set or both null",
            )
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

        await conn.execute(
            """
            UPDATE workspaces
            SET name = $2, description = $3, system_prompt = $4,
                color = $5, shared = $6, sort_order = $7, icon_url = $8, model = $9,
                rag_mode = $10, provider_id = $11, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            workspace_id,
            new_name,
            new_desc,
            new_sp,
            new_color,
            new_shared,
            new_sort,
            new_icon,
            new_model,
            new_rag,
            new_provider_id,
        )
        prow = await conn.fetchrow(
            DAWS_SELECT + "WHERE d.id = $1::uuid",
            workspace_id,
        )
    async with audit.targeting("workspace", workspace_id):
        pass
    return _row(prow)


class PatientProfileBody(BaseModel):
    profile: dict[str, Any]


@router.get("/{workspace_id}/patient-profile")
async def get_patient_profile(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Return the structured patient profile for a workspace.

    Returns 404 if the workspace does not exist.
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row = await conn.fetchrow(
            "SELECT profile, updated_at FROM workspace_patient_profile WHERE workspace_id = $1::uuid",
            workspace_id,
        )
    async with audit.targeting("workspace", workspace_id):
        pass

    import json as _json

    if row is None:
        return {
            "workspace_id": str(workspace_id),
            "profile": {},
            "updated_at": None,
        }
    raw = row["profile"]
    profile_dict = _json.loads(raw) if isinstance(raw, str) else dict(raw)
    return {
        "workspace_id": str(workspace_id),
        "profile": profile_dict,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.put("/{workspace_id}/patient-profile")
async def put_patient_profile(
    workspace_id: uuid.UUID,
    body: PatientProfileBody,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Upsert the structured patient profile for a workspace."""
    from services.patient_profile import upsert_profile

    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Workspace not found")
        await upsert_profile(conn, workspace_id, body.profile)
        updated_row = await conn.fetchrow(
            "SELECT updated_at FROM workspace_patient_profile WHERE workspace_id = $1::uuid",
            workspace_id,
        )
    async with audit.targeting("workspace", workspace_id):
        pass
    return {
        "workspace_id": str(workspace_id),
        "updated_at": updated_row["updated_at"].isoformat() if updated_row and updated_row["updated_at"] else None,
    }


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: uuid.UUID,
    _: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE id = $1::uuid",
            workspace_id,
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    _delete_stored_icon(workspace_id)
    async with pool.acquire() as conn:
        source_rows = await conn.fetch(
            "SELECT id, file_url, content_hash FROM sources WHERE workspace_id = $1::uuid",
            workspace_id,
        )
        result = await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", workspace_id)
    import pathlib
    for sr in source_rows:
        if sr["file_url"] and sr["content_hash"]:
            remaining = 0
            async with pool.acquire() as chk:
                remaining = await chk.fetchval(
                    "SELECT COUNT(*) FROM sources WHERE content_hash = $1",
                    sr["content_hash"],
                )
            if remaining == 0:
                try:
                    pathlib.Path(sr["file_url"]).unlink(missing_ok=True)
                except OSError:
                    pass
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Workspace not found")
    async with audit.targeting("workspace", workspace_id):
        pass
    return {"ok": True}
