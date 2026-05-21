"""Manage previously-exported chat history files.

The export endpoints in routers.chats write under
/data/history/chats/<workspace-slug>/. This router exposes list / read /
rename / delete over that tree.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_principal
from db import get_pool
from services.history import (
    VALID_KINDS,
    workspace_dir,
    safe_path,
    slugify,
)
from services.provider_client import resolve_provider_for_workspace

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB — keep the payload sane
EXT_FOR_KIND = {"chats": ".md"}


class RenameBody(BaseModel):
    old: str = Field(..., min_length=1)
    new: str = Field(..., min_length=1)  # manual slug or "__ai__"
    workspace_id: uuid.UUID


class DeleteBody(BaseModel):
    file: str = Field(..., min_length=1)
    workspace_id: uuid.UUID


async def _workspace_name(workspace_id: uuid.UUID) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name FROM workspaces WHERE id = $1::uuid", workspace_id,
        )
    if not row or not row["name"]:
        raise HTTPException(status_code=404, detail="workspace not found")
    return row["name"]


def _ensure_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown kind: {kind}")


@router.get("/{kind}")
async def list_history(
    kind: str,
    workspace_id: uuid.UUID = Query(...),
    principal: dict[str, Any] = Depends(get_principal),
) -> dict:
    _ensure_kind(kind)
    name = await _workspace_name(workspace_id)
    folder = workspace_dir(kind, name)  # creates if missing
    items = []
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix not in {".md", ".txt"}:
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        items.append({
            "filename": entry.name,
            "size": st.st_size,
            "modified_at": int(st.st_mtime),
        })
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return {"kind": kind, "workspace_id": str(workspace_id), "workspace_slug": slugify(name), "items": items}


@router.get("/{kind}/content")
async def read_history(
    kind: str,
    workspace_id: uuid.UUID = Query(...),
    file: str = Query(..., min_length=1),
    principal: dict[str, Any] = Depends(get_principal),
) -> dict:
    _ensure_kind(kind)
    name = await _workspace_name(workspace_id)
    try:
        path = safe_path(kind, name, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        size = path.stat().st_size
    except OSError:
        raise HTTPException(status_code=404, detail="file not found")
    if size > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {MAX_FILE_BYTES} bytes",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "kind": kind,
        "filename": file,
        "size": size,
        "content": text,
    }


@router.post("/{kind}/rename")
async def rename_history(kind: str, body: RenameBody, principal: dict[str, Any] = Depends(get_principal)) -> dict:
    _ensure_kind(kind)
    name = await _workspace_name(body.workspace_id)
    try:
        old_path = safe_path(kind, name, body.old)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not old_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    ext = EXT_FOR_KIND[kind]

    if body.new.strip() == "__ai__":
        # Import lazily to avoid circular with routers.chats when /history loads.
        try:
            from routers.chats import _openai_short_chat_title
        except Exception:
            _openai_short_chat_title = None
        proposed = None
        if _openai_short_chat_title is not None:
            try:
                text = old_path.read_text(encoding="utf-8", errors="replace")
                sample = text[:4000]
                # Resolve via the workspace whose history file we're renaming.
                # If the workspace has no provider configured, the resolver
                # raises HTTPException(400) with the spec message; we surface
                # it as 503 to match the existing "ai rename unavailable" UX.
                provider, model = await resolve_provider_for_workspace(body.workspace_id)
                proposed = await _openai_short_chat_title(
                    provider, model, user_message_text=sample
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("ai rename failed kind=%s file=%s err=%s", kind, body.old, e)
        if not proposed:
            raise HTTPException(status_code=503, detail="ai rename unavailable")
        slug = slugify(proposed, fallback="untitled", max_len=60)
    else:
        slug = slugify(body.new, fallback="untitled", max_len=60)

    if not slug:
        raise HTTPException(status_code=400, detail="new name resolved to empty slug")

    # Keep any trailing timestamp on the old name if present, so the rename
    # still disambiguates when multiple AI renames produce the same slug.
    base_old = old_path.stem
    ts_suffix = ""
    # Heuristic: if old stem ends with -YYYYMMDD-HHMMSS, preserve it.
    m = re.search(r"-(\d{8}-\d{6})$", base_old)
    if m:
        ts_suffix = "-" + m.group(1)

    # Collision handling: append -1, -2, ...
    attempt = 0
    while True:
        suffix = f"-{attempt}" if attempt else ""
        candidate = f"{slug}{ts_suffix}{suffix}{ext}"
        try:
            new_path = safe_path(kind, name, candidate)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not new_path.exists():
            break
        if new_path == old_path:
            break
        attempt += 1
        if attempt > 50:
            raise HTTPException(status_code=500, detail="rename collision loop")

    if new_path == old_path:
        return {"filename": candidate, "renamed": False}

    try:
        old_path.rename(new_path)
    except OSError as e:
        logger.warning("rename os error: %s", e)
        raise HTTPException(status_code=500, detail="rename failed")

    return {"filename": candidate, "renamed": True}


@router.delete("/{kind}")
async def delete_history(kind: str, body: DeleteBody, principal: dict[str, Any] = Depends(get_principal)) -> dict:
    _ensure_kind(kind)
    name = await _workspace_name(body.workspace_id)
    try:
        path = safe_path(kind, name, body.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        path.unlink()
    except OSError as e:
        logger.warning("delete os error: %s", e)
        raise HTTPException(status_code=500, detail="delete failed")
    return {"ok": True}
