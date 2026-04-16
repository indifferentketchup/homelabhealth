"""DubDrive → boolab RAG sync. Fetches files from a DAW's configured sync folder and ingests them."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import pathlib
import uuid
from collections import deque
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_deps import get_principal
from db import get_pool
from routers.sources import _ingest_source, _mime_to_source_type
from services import dubdrive_auth

router = APIRouter(prefix="/dubdrive-sync", tags=["dubdrive-sync"])
logger = logging.getLogger(__name__)

_DEFAULT_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", ".cache",
    "vendor", "target", "coverage", ".tox",
})

_DEFAULT_SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".pdf", ".lock", ".pyc", ".pyo", ".class", ".o", ".obj",
    ".map", ".min.js", ".min.css",
})

_DEFAULT_SKIP_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Thumbs.db", "desktop.ini", ".DS_Store",
})


async def _load_dubignore(root: str) -> tuple[set[str], set[str], set[str]]:
    """
    Load .dubignore from root of sync folder via DubDrive API.
    Returns (skip_dirs, skip_extensions, skip_names) merged with defaults.
    
    .dubignore format (one pattern per line, # comments):
      dir:node_modules        — skip directory by name
      ext:.png                — skip files by extension
      name:package-lock.json  — skip files by exact name
    
    Lines without a prefix are treated as dir: patterns.
    """
    skip_dirs = set(_DEFAULT_SKIP_DIRS)
    skip_exts = set(_DEFAULT_SKIP_EXTENSIONS)
    skip_names = set(_DEFAULT_SKIP_NAMES)
    try:
        sep = "/" if root.endswith("/") else "/"
        ignore_path = f"{root}{sep}.dubignore"
        content = await _dubdrive_read(ignore_path)
        if not content:
            return skip_dirs, skip_exts, skip_names
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("dir:"):
                skip_dirs.add(line[4:].strip())
            elif line.startswith("ext:"):
                e = line[4:].strip()
                if not e.startswith("."):
                    e = "." + e
                skip_exts.add(e)
            elif line.startswith("name:"):
                skip_names.add(line[5:].strip())
            else:
                # bare word = directory name
                skip_dirs.add(line)
        logger.info(".dubignore loaded: +%d dirs, +%d exts, +%d names",
                     len(skip_dirs) - len(_DEFAULT_SKIP_DIRS),
                     len(skip_exts) - len(_DEFAULT_SKIP_EXTENSIONS),
                     len(skip_names) - len(_DEFAULT_SKIP_NAMES))
    except Exception as e:
        logger.debug(".dubignore not found or unreadable: %s", e)
    return skip_dirs, skip_exts, skip_names


async def _dubdrive_ls(path: str) -> list[dict[str, Any]]:
    """Call DubDrive GET /api/ls?path= and return the items list."""
    base = dubdrive_auth._dubdrive_base_url()
    url = f"{base}/api/ls"
    try:
        token = await dubdrive_auth.get_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params={"path": path}, cookies=dubdrive_auth.get_cookies(token))

        if r.status_code == 401:
            token = await dubdrive_auth.invalidate_and_relogin()
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url, params={"path": path}, cookies=dubdrive_auth.get_cookies(token))

        if r.status_code != 200:
            logger.warning("DubDrive ls failed path=%r: %s %s", path, r.status_code, r.text[:200])
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("files", []))
        return []
    except Exception as e:
        logger.warning("DubDrive ls failed path=%r: %s", path, e)
        return []


async def _dubdrive_read(path: str) -> str | None:
    """Read a text file from DubDrive. Returns content string or None."""
    try:
        base = dubdrive_auth._dubdrive_base_url()
        token = await dubdrive_auth.get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{base}/api/read",
                params={"path": path},
                cookies=dubdrive_auth.get_cookies(token),
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            return data.get("content") or data.get("text") or None
    except Exception:
        return None


async def _dubdrive_read_bytes(path: str) -> bytes | None:
    """Call DubDrive GET /api/raw?path= and return raw bytes."""
    base = dubdrive_auth._dubdrive_base_url()
    url = f"{base}/api/raw"
    try:
        token = await dubdrive_auth.get_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params={"path": path}, cookies=dubdrive_auth.get_cookies(token))

        if r.status_code == 401:
            token = await dubdrive_auth.invalidate_and_relogin()
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url, params={"path": path}, cookies=dubdrive_auth.get_cookies(token))

        if r.status_code != 200:
            logger.warning("DubDrive raw read failed path=%r: %s %s", path, r.status_code, r.text[:200])
            return None
        return r.content
    except Exception as e:
        logger.warning("DubDrive raw read failed path=%r: %s", path, e)
        return None


async def _collect_files(root: str, max_files: int = 200,
                         skip_dirs: set[str] | None = None,
                         skip_exts: set[str] | None = None,
                         skip_names: set[str] | None = None) -> list[dict[str, Any]]:
    """
    Recursively walk DubDrive directory tree starting at root.
    Returns list of {path, name, size} for files only (not dirs).
    Stops at max_files total. Non-recursive: BFS using a queue.
    Skip hidden files (name starting with .).
    """
    files: list[dict[str, Any]] = []
    queue: deque[str] = deque([root])
    seen_dirs: set[str] = set()
    while queue and len(files) < max_files:
        dir_path = queue.popleft()
        if dir_path in seen_dirs:
            continue
        seen_dirs.add(dir_path)
        items = await _dubdrive_ls(dir_path)
        for item in items:
            if len(files) >= max_files:
                break
            name = (
                item.get("name")
                or item.get("filename")
                or item.get("FileName")
                or ""
            )
            if not name or str(name).startswith("."):
                continue
            path = item.get("path") or item.get("Path")
            if not path:
                sep = "/" if dir_path.endswith("/") or not dir_path else "/"
                path = f"{dir_path}{sep}{name}" if dir_path else str(name)
            is_dir = bool(
                item.get("is_dir")
                or item.get("isDir")
                or item.get("directory")
                or item.get("type") == "dir"
                or item.get("Type") == "directory"
            )
            if is_dir:
                if skip_dirs and name in skip_dirs:
                    continue
                queue.append(str(path))
            else:
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if (skip_names and name in skip_names) or (skip_exts and ext in skip_exts):
                    continue
                size = item.get("size") or item.get("Size") or 0
                try:
                    size_i = int(size)
                except (TypeError, ValueError):
                    size_i = 0
                files.append({"path": str(path), "name": str(name), "size": size_i})
    return files


def _mime_from_name(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".md", ".markdown")):
        return "text/markdown"
    if lower.endswith(".txt"):
        return "text/plain"
    if lower.endswith(
        (
            ".py",
            ".go",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".sh",
            ".yaml",
            ".yml",
            ".toml",
            ".json",
            ".env",
        )
    ):
        return "text/plain"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


async def _ingest_dubdrive_file(
    path: str,
    name: str,
    source_id: uuid.UUID,
    daw_id: uuid.UUID,
) -> None:
    """
    Fetch file bytes from DubDrive, run through the existing _ingest_source pipeline.
    """
    raw = await _dubdrive_read_bytes(path)
    if raw is None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sources
                SET embedding_status = 'error', error_message = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                source_id,
                "DubDrive fetch failed",
            )
        return
    mime = _mime_from_name(name)
    await _ingest_source(source_id, daw_id, raw, mime, name)


@router.post("/{daw_id}/sync")
async def dubdrive_sync_run(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT dubdrive_sync_folder, dubdrive_sync_enabled
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="DAW not found")

        sync_folder = row["dubdrive_sync_folder"]
        sync_enabled = bool(row["dubdrive_sync_enabled"])
        folder_ok = sync_folder is not None and str(sync_folder).strip() != ""
        if not sync_enabled or not folder_ok:
            raise HTTPException(status_code=400, detail="sync_not_configured")

        sync_folder_str = str(sync_folder).strip()

    skip_dirs, skip_exts, skip_names = await _load_dubignore(sync_folder_str)
    files = await _collect_files(sync_folder_str, skip_dirs=skip_dirs, skip_exts=skip_exts, skip_names=skip_names)
    total_found = len(files)
    queued = 0
    skipped = 0

    for f in files:
        fpath = f["path"]
        fname = f["name"]
        content_hash = hashlib.sha256(fpath.encode()).hexdigest()

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id, embedding_status FROM sources
                WHERE daw_id = $1::uuid AND content_hash = $2
                LIMIT 1
                """,
                daw_id,
                content_hash,
            )

            if existing:
                st = existing["embedding_status"]
                if st == "complete":
                    skipped += 1
                    continue
                if st in ("error", "pending"):
                    await conn.execute("DELETE FROM sources WHERE id = $1::uuid", existing["id"])
                else:
                    skipped += 1
                    continue

            mime = _mime_from_name(fname)
            stype = _mime_to_source_type(mime)
            size_i = int(f.get("size") or 0)
            source_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO sources (
                    id, daw_id, name, source_type, mime_type, file_size_bytes,
                    content_hash, embedding_status, updated_at
                )
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, 'processing', NOW())
                """,
                source_id,
                daw_id,
                fname,
                stype,
                mime,
                size_i,
                content_hash,
            )

        queued += 1
        asyncio.create_task(_ingest_dubdrive_file(fpath, fname, source_id, daw_id))

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE daws SET dubdrive_last_synced_at = NOW(), updated_at = NOW()
            WHERE id = $1::uuid
            """,
            daw_id,
        )

    return {"queued": queued, "skipped": skipped, "total_found": total_found}


@router.get("/{daw_id}/status")
async def dubdrive_sync_status(
    daw_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        daw = await conn.fetchrow(
            """
            SELECT dubdrive_sync_folder, dubdrive_sync_enabled, dubdrive_last_synced_at
            FROM daws WHERE id = $1::uuid
            """,
            daw_id,
        )
        if daw is None:
            raise HTTPException(status_code=404, detail="DAW not found")

        src_rows = await conn.fetch(
            """
            SELECT id, name, embedding_status, content_hash
            FROM sources
            WHERE daw_id = $1::uuid
            ORDER BY created_at DESC
            """,
            daw_id,
        )

    sources_out = [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "embedding_status": r["embedding_status"],
            "content_hash": r["content_hash"],
        }
        for r in src_rows
    ]
    return {
        "sync_folder": daw["dubdrive_sync_folder"],
        "sync_enabled": bool(daw["dubdrive_sync_enabled"]),
        "last_synced_at": daw["dubdrive_last_synced_at"].isoformat()
        if daw["dubdrive_last_synced_at"]
        else None,
        "sources": sources_out,
    }
