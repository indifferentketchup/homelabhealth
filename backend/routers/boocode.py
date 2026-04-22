"""BooCode router: repo sync status + file tree + live DubDrive fetch + repo config."""

from __future__ import annotations

import asyncio
import logging
import posixpath
import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_deps import get_principal
from db import get_pool
from routers.dubdrive_sync import _dubdrive_read_bytes
from services import code_chunker
from services.repo_ingest import (
    sync_daw_repo,
    validate_relative_file_path,
    validate_repo_path,
)

router = APIRouter(prefix="/boocode", tags=["boocode"])
logger = logging.getLogger(__name__)


class RepoConfigBody(BaseModel):
    repo_path: str | None = None
    repo_branch: str | None = None
    repo_auto_sync: bool | None = None


async def _daw_exists(conn, daw_id: uuid.UUID) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM daws WHERE id = $1::uuid", daw_id))


async def _run_sync_fire_and_forget(daw_id: uuid.UUID) -> None:
    try:
        await sync_daw_repo(daw_id)
    except Exception:
        logger.exception("background sync_daw_repo crashed daw_id=%s", daw_id)


@router.post("/daws/{daw_id}/sync", status_code=202)
async def repo_sync(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT repo_path, repo_sync_status, repo_last_synced_at
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="daw_not_found")
        if not row["repo_path"] or not str(row["repo_path"]).strip():
            raise HTTPException(status_code=400, detail="no_repo_path")
        if row["repo_sync_status"] == "syncing":
            raise HTTPException(status_code=409, detail="already_syncing")

    asyncio.create_task(_run_sync_fire_and_forget(daw_id))
    return {
        "status": "queued",
        "daw_id": str(daw_id),
    }


@router.get("/daws/{daw_id}/sync/status")
async def repo_sync_status(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT repo_path, repo_branch, repo_auto_sync, repo_sync_status,
                   repo_sync_error, repo_last_synced_at,
                   repo_file_count, repo_chunk_count
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="daw_not_found")
    return {
        "repo_path": row["repo_path"],
        "repo_branch": row["repo_branch"],
        "repo_auto_sync": bool(row["repo_auto_sync"]),
        "status": row["repo_sync_status"] or "idle",
        "error": row["repo_sync_error"],
        "last_synced_at": row["repo_last_synced_at"].isoformat()
        if row["repo_last_synced_at"]
        else None,
        "file_count": int(row["repo_file_count"] or 0),
        "chunk_count": int(row["repo_chunk_count"] or 0),
    }


@router.get("/daws/{daw_id}/tree")
async def repo_tree(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await _daw_exists(conn, daw_id):
            raise HTTPException(status_code=404, detail="daw_not_found")
        rows = await conn.fetch(
            """
            SELECT path, language, size_bytes, last_ingested_at
            FROM repo_files
            WHERE daw_id = $1::uuid
            ORDER BY path ASC
            """,
            daw_id,
        )
    return {
        "daw_id": str(daw_id),
        "files": [
            {
                "path": r["path"],
                "language": r["language"],
                "size": int(r["size_bytes"] or 0),
                "last_ingested_at": r["last_ingested_at"].isoformat()
                if r["last_ingested_at"]
                else None,
            }
            for r in rows
        ],
    }


@router.get("/daws/{daw_id}/stats")
async def repo_stats(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await _daw_exists(conn, daw_id):
            raise HTTPException(status_code=404, detail="daw_not_found")
        lang_rows = await conn.fetch(
            """
            SELECT COALESCE(language, 'unknown') AS language, COUNT(*) AS files
            FROM repo_files
            WHERE daw_id = $1::uuid
            GROUP BY 1
            ORDER BY files DESC, language ASC
            """,
            daw_id,
        )
        chunk_rows = await conn.fetch(
            """
            SELECT COALESCE(language, 'unknown') AS language,
                   COUNT(*)          AS chunks,
                   SUM(rc.tokens)    AS tokens
            FROM repo_chunks rc
            JOIN repo_files rf ON rf.id = rc.file_id
            WHERE rc.daw_id = $1::uuid
            GROUP BY 1
            ORDER BY chunks DESC, language ASC
            """,
            daw_id,
        )
        kind_rows = await conn.fetch(
            """
            SELECT COALESCE(symbol_kind, 'unknown') AS symbol_kind, COUNT(*) AS chunks
            FROM repo_chunks
            WHERE daw_id = $1::uuid
            GROUP BY 1
            ORDER BY chunks DESC, symbol_kind ASC
            """,
            daw_id,
        )
        total_tokens = await conn.fetchval(
            "SELECT COALESCE(SUM(tokens), 0) FROM repo_chunks WHERE daw_id = $1::uuid",
            daw_id,
        )
    languages = [
        {
            "language": lr["language"],
            "files": int(lr["files"]),
            "chunks": next(
                (int(cr["chunks"]) for cr in chunk_rows if cr["language"] == lr["language"]),
                0,
            ),
            "tokens": next(
                (int(cr["tokens"] or 0) for cr in chunk_rows if cr["language"] == lr["language"]),
                0,
            ),
        }
        for lr in lang_rows
    ]
    symbol_kinds = [
        {"symbol_kind": kr["symbol_kind"], "chunks": int(kr["chunks"])}
        for kr in kind_rows
    ]
    return {
        "daw_id": str(daw_id),
        "languages": languages,
        "symbol_kinds": symbol_kinds,
        "total_tokens": int(total_tokens or 0),
        "total_files": sum(l["files"] for l in languages),
        "total_chunks": sum(l["chunks"] for l in languages),
    }


@router.get("/daws/{daw_id}/file")
async def repo_file(
    daw_id: uuid.UUID,
    path: str = Query(..., min_length=1),
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    try:
        rel = validate_relative_file_path(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pool = await get_pool()
    async with pool.acquire() as conn:
        daw_row = await conn.fetchrow(
            "SELECT repo_path FROM daws WHERE id = $1::uuid", daw_id
        )
        if daw_row is None:
            raise HTTPException(status_code=404, detail="daw_not_found")
        repo_root = (daw_row["repo_path"] or "").strip()
        if not repo_root:
            raise HTTPException(status_code=400, detail="no_repo_path")

    try:
        repo_root = validate_repo_path(repo_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid repo_path: {e}")

    full_path = posixpath.join(repo_root, rel)
    raw = await _dubdrive_read_bytes(full_path)
    if raw is None:
        raise HTTPException(status_code=404, detail="file_not_found")
    if len(raw) > code_chunker.MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if b"\x00" in raw[:4096]:
        raise HTTPException(status_code=415, detail="binary_file")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="replace")
    return {
        "path": rel,
        "language": code_chunker.resolve_language(rel),
        "size": len(raw),
        "content": content,
    }


@router.patch("/daws/{daw_id}/repo")
async def repo_update(
    daw_id: uuid.UUID,
    body: RepoConfigBody,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT repo_path, repo_branch, repo_auto_sync
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="daw_not_found")

        new_path = row["repo_path"]
        if "repo_path" in data:
            v = data["repo_path"]
            if v is None or not str(v).strip():
                new_path = None
            else:
                try:
                    new_path = validate_repo_path(str(v))
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))

        new_branch = row["repo_branch"] or "main"
        if "repo_branch" in data:
            v = data["repo_branch"]
            new_branch = (str(v).strip() or "main") if v is not None else "main"

        new_auto = bool(row["repo_auto_sync"])
        if "repo_auto_sync" in data and data["repo_auto_sync"] is not None:
            new_auto = bool(data["repo_auto_sync"])

        await conn.execute(
            """
            UPDATE daws
            SET repo_path = $2, repo_branch = $3, repo_auto_sync = $4, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            daw_id,
            new_path,
            new_branch,
            new_auto,
        )
    return {
        "daw_id": str(daw_id),
        "repo_path": new_path,
        "repo_branch": new_branch,
        "repo_auto_sync": new_auto,
    }


_branches_cache: dict[str, tuple[float, list[str]]] = {}
_BRANCHES_TTL = 60.0


def _item_name(item: dict[str, Any]) -> str:
    """Extract a file/dir name from a DubDrive /api/ls item, matching the key
    variance documented in routers.dubdrive_sync._collect_files."""
    name = (
        item.get("name")
        or item.get("filename")
        or item.get("FileName")
        or item.get("Name")
        or ""
    )
    if not name:
        path = item.get("path") or item.get("Path") or ""
        if path:
            name = str(path).rsplit("/", 1)[-1]
    return str(name or "")


def _item_is_dir(item: dict[str, Any]) -> bool:
    return bool(
        item.get("is_dir")
        or item.get("isDir")
        or item.get("directory")
        or item.get("type") == "dir"
        or item.get("Type") == "directory"
    )


async def _dubdrive_list_branches(repo_root: str) -> list[str] | None:
    """List branch names for a DubDrive-hosted git repo via the DubDrive
    /api/ls + /api/read HTTP surface.

    Probes both working-clone (``<repo>/.git/``) and bare-clone (``<repo>/``)
    layouts. For each layout, reads loose refs from ``refs/heads`` (recursing
    one level for names like ``release/1.0``) and packed refs from
    ``packed-refs``.

    Returns a sorted unique list of branch names, or ``None`` if the repo
    appears not to be a git directory accessible via DubDrive (caller should
    use a fallback).
    """
    from routers.dubdrive_sync import _dubdrive_ls, _dubdrive_read

    names: set[str] = set()
    found_any_git_layout = False

    # Try both working-clone (.git/) and bare-clone (root) layouts.
    candidates = [f"{repo_root.rstrip('/')}/.git", repo_root.rstrip("/")]

    for git_root in candidates:
        layout_names: set[str] = set()
        layout_found = False

        # Loose refs: <git_root>/refs/heads/<branch>
        items = await _dubdrive_ls(f"{git_root}/refs/heads")
        if items:
            layout_found = True
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = _item_name(it)
                if not name:
                    continue
                if _item_is_dir(it):
                    # Recurse one level for `release/1.0` style names.
                    sub = await _dubdrive_ls(f"{git_root}/refs/heads/{name}")
                    for s in sub or []:
                        if not isinstance(s, dict):
                            continue
                        sname = _item_name(s)
                        # Only include files one level down; deeper nesting is
                        # rare and can be added later if needed.
                        if sname and not _item_is_dir(s):
                            layout_names.add(f"{name}/{sname}")
                    continue
                layout_names.add(name)

        # Packed refs: single file with `<sha> refs/heads/<branch>` lines.
        packed = await _dubdrive_read(f"{git_root}/packed-refs")
        if packed is not None:
            layout_found = True
            for line in packed.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                _, ref = parts
                if ref.startswith("refs/heads/"):
                    layout_names.add(ref[len("refs/heads/"):].strip())

        if layout_found:
            # Prefer the first layout that returned anything — don't merge
            # working-clone refs with bare-clone refs.
            names = layout_names
            found_any_git_layout = True
            break

    if not found_any_git_layout:
        return None
    return sorted(names)


@router.get("/daws/{daw_id}/branches")
async def repo_branches(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT repo_path FROM daws WHERE id = $1::uuid", daw_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="daw_not_found")
        repo_root = (row["repo_path"] or "").strip()
        if not repo_root:
            raise HTTPException(status_code=400, detail="no_repo_path")
    try:
        repo_root = validate_repo_path(repo_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid repo_path: {e}")

    cached = _branches_cache.get(repo_root)
    now = time.time()
    if cached and (now - cached[0] < _BRANCHES_TTL):
        return {"branches": cached[1], "cached": True}

    try:
        names = await _dubdrive_list_branches(repo_root)
    except Exception:
        logger.exception("branch listing failed repo=%s", repo_root)
        names = None

    if not names:
        # Cache the fallback too, so repeated failures don't hammer DubDrive.
        _branches_cache[repo_root] = (now, ["main"])
        return {"branches": ["main"], "fallback": True}

    _branches_cache[repo_root] = (now, names)
    return {"branches": names}
