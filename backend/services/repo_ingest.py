"""BooCode repo ingest: DubDrive → tree-sitter chunks → pgvector.

Mirrors 808notes' DubDrive sync pattern: reuse `_collect_files` and
`_dubdrive_read_bytes` from `routers.dubdrive_sync`, drop ingested rows
into `repo_files`/`repo_chunks`, update sync status on `daws`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import posixpath
import time
import uuid
from collections import defaultdict
from typing import Any

import asyncpg

from db import get_pool
from routers.dubdrive_sync import _collect_files, _dubdrive_read_bytes
from services import code_chunker
from services.embeddings import EmbeddingError, embed_batch, format_vector

logger = logging.getLogger(__name__)

MAX_FILES_PER_SYNC = 1000

ALLOWED_REPO_PREFIX = os.environ.get("BOOCODE_ALLOWED_REPO_PREFIX", "/HomeLabRepos/")
MAX_REPO_PATH_LEN = 512
MAX_REL_PATH_LEN = 1024


_progress_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def _emit_progress(daw_id, payload: dict) -> None:
    key = str(daw_id)
    dead: list[asyncio.Queue] = []
    for q in list(_progress_subscribers.get(key, set())):
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        _progress_subscribers[key].discard(q)


def subscribe_progress(daw_id) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=128)
    _progress_subscribers[str(daw_id)].add(q)
    return q


def unsubscribe_progress(daw_id, q: asyncio.Queue) -> None:
    _progress_subscribers[str(daw_id)].discard(q)


def validate_repo_path(path: str) -> str:
    """Validate a DubDrive repo root path. Returns normalized path or raises ValueError."""
    if not isinstance(path, str):
        raise ValueError("repo_path must be a string")
    p = path.strip()
    if not p:
        raise ValueError("repo_path is required")
    if len(p) > MAX_REPO_PATH_LEN:
        raise ValueError(f"repo_path exceeds {MAX_REPO_PATH_LEN} chars")
    if "\x00" in p:
        raise ValueError("repo_path contains null byte")
    if not p.startswith(ALLOWED_REPO_PREFIX):
        raise ValueError(f"repo_path must start with {ALLOWED_REPO_PREFIX}")
    if ".." in p.split("/"):
        raise ValueError("repo_path contains '..'")
    if len(p) > len(ALLOWED_REPO_PREFIX) and p.endswith("/"):
        p = p.rstrip("/")
    return p


def validate_relative_file_path(rel: str) -> str:
    """Validate a relative path inside a repo. Returns normalized rel path or raises ValueError."""
    if not isinstance(rel, str):
        raise ValueError("path must be a string")
    if not rel:
        raise ValueError("path is required")
    if len(rel) > MAX_REL_PATH_LEN:
        raise ValueError(f"path exceeds {MAX_REL_PATH_LEN} chars")
    if "\x00" in rel:
        raise ValueError("path contains null byte")
    if rel.startswith("/"):
        raise ValueError("path must be relative (no leading '/')")
    norm = posixpath.normpath(rel)
    if norm.startswith("/") or norm.startswith("../") or norm in ("..", ".", "/"):
        raise ValueError("path traversal detected")
    if any(part == ".." for part in norm.split("/")):
        raise ValueError("path contains '..'")
    return norm


async def list_repo_files(repo_path: str) -> list[dict[str, Any]]:
    """Walk DubDrive under repo_path, applying boocode ignore rules.

    Returns a list of {path, name, size} dicts.
    """
    files = await _collect_files(
        repo_path,
        max_files=MAX_FILES_PER_SYNC,
        skip_dirs=set(code_chunker.IGNORED_DIRS),
        skip_exts=set(code_chunker.IGNORED_BINARY_EXTS),
        skip_names=set(code_chunker.IGNORED_NAMES),
    )
    return [f for f in files if not code_chunker.is_ignored_path(f["path"])]


async def fetch_file_content(path: str) -> str | None:
    """Fetch file bytes from DubDrive, return decoded text or None.

    Skips: files > MAX_FILE_BYTES, binary sniff (NUL in first 4KB), decode failures.
    """
    raw = await _dubdrive_read_bytes(path)
    if raw is None:
        return None
    if len(raw) > code_chunker.MAX_FILE_BYTES:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except Exception:
            return None


async def ingest_file(
    conn: asyncpg.Connection,
    daw_id: uuid.UUID,
    path: str,
    content: str,
    size_bytes: int,
) -> tuple[str, int]:
    """Upsert repo_files row + chunks. Returns (status, chunk_count).

    status: 'skipped' (hash unchanged), 'added' (new file), 'updated' (hash changed).
    """
    chash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    language = code_chunker.resolve_language(path)

    existing = await conn.fetchrow(
        "SELECT id, content_hash FROM repo_files WHERE daw_id = $1::uuid AND path = $2 LIMIT 1",
        daw_id,
        path,
    )
    if existing and existing["content_hash"] == chash:
        return "skipped", 0

    if existing:
        file_id = existing["id"]
        status = "updated"
        await conn.execute("DELETE FROM repo_chunks WHERE file_id = $1::uuid", file_id)
        await conn.execute(
            """
            UPDATE repo_files
            SET language = $2, size_bytes = $3, content_hash = $4, last_ingested_at = NOW()
            WHERE id = $1::uuid
            """,
            file_id,
            language,
            size_bytes,
            chash,
        )
    else:
        file_id = uuid.uuid4()
        status = "added"
        await conn.execute(
            """
            INSERT INTO repo_files (id, daw_id, path, language, size_bytes, content_hash)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            """,
            file_id,
            daw_id,
            path,
            language,
            size_bytes,
            chash,
        )

    chunks = code_chunker.chunk_file(content, path)
    if not chunks:
        return status, 0

    texts = [c["content"] for c in chunks]
    embeddings = await embed_batch(texts)

    for i, c in enumerate(chunks):
        emb_vec = format_vector(embeddings[i])
        content_sanitized = c["content"].replace("\x00", "")
        await conn.execute(
            """
            INSERT INTO repo_chunks (
                id, file_id, daw_id, chunk_index, symbol_kind, symbol_name,
                start_line, end_line, content, embedding, tokens
            )
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10::vector, $11)
            """,
            uuid.uuid4(),
            file_id,
            daw_id,
            c["chunk_index"],
            c["symbol_kind"],
            c["symbol_name"],
            int(c["start_line"]),
            int(c["end_line"]),
            content_sanitized,
            emb_vec,
            int(c["tokens"]),
        )
    return status, len(chunks)


async def sync_daw_repo(daw_id: uuid.UUID) -> dict[str, Any]:
    """Full sync: list DubDrive → diff → ingest/update/delete → refresh counts."""
    started = time.monotonic()
    pool = await get_pool()

    async with pool.acquire() as conn:
        daw_row = await conn.fetchrow(
            "SELECT repo_path, repo_branch, repo_sync_status FROM daws WHERE id = $1::uuid",
            daw_id,
        )
        if daw_row is None:
            return {"status": "error", "error": "daw_not_found"}
        repo_path = daw_row["repo_path"]
        if not repo_path or not str(repo_path).strip():
            return {"status": "error", "error": "no_repo_path"}
        branch = daw_row["repo_branch"] or "main"

        # Atomic claim: only set to syncing if not already syncing.
        claim = await conn.execute(
            """
            UPDATE daws
            SET repo_sync_status = 'syncing', repo_sync_error = NULL, updated_at = NOW()
            WHERE id = $1::uuid AND (repo_sync_status IS NULL OR repo_sync_status <> 'syncing')
            """,
            daw_id,
        )
        if claim.split()[-1] == "0":
            return {"status": "error", "error": "already_syncing"}

    _emit_progress(daw_id, {"event": "start", "repo_path": repo_path, "branch": branch})

    deleted_count = 0
    files_done = 0
    files_total = 0
    chunks_total = 0
    try:
        files = await list_repo_files(str(repo_path).strip())
        remote_paths = {f["path"] for f in files}
        files_total = len(files)

        async with pool.acquire() as conn:
            existing_rows = await conn.fetch(
                "SELECT path FROM repo_files WHERE daw_id = $1::uuid",
                daw_id,
            )
            existing_paths = {r["path"] for r in existing_rows}
            deleted_paths = list(existing_paths - remote_paths)
            if deleted_paths:
                await conn.execute(
                    "DELETE FROM repo_files WHERE daw_id = $1::uuid AND path = ANY($2::text[])",
                    daw_id,
                    deleted_paths,
                )
                deleted_count = len(deleted_paths)

        added = 0
        updated = 0
        skipped = 0

        for f in files:
            path = f["path"]
            size = int(f.get("size") or 0)
            content = await fetch_file_content(path)
            if content is None:
                files_done += 1
                _emit_progress(daw_id, {
                    "event": "progress",
                    "files_done": files_done,
                    "files_total": files_total,
                    "chunks_total": chunks_total,
                    "current_file": path,
                })
                continue
            try:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        status, file_cc = await ingest_file(conn, daw_id, path, content, size)
                if status == "added":
                    added += 1
                elif status == "updated":
                    updated += 1
                elif status == "skipped":
                    skipped += 1
                chunks_total += int(file_cc or 0)
            except EmbeddingError as e:
                logger.warning("skipping %s due to embedding failure: %s", path, e)
            except Exception as e:
                logger.exception("ingest_file failed for %s: %s", path, e)
            finally:
                files_done += 1
                _emit_progress(daw_id, {
                    "event": "progress",
                    "files_done": files_done,
                    "files_total": files_total,
                    "chunks_total": chunks_total,
                    "current_file": path,
                })

        async with pool.acquire() as conn:
            agg = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM repo_files WHERE daw_id = $1::uuid)  AS fc,
                    (SELECT COUNT(*) FROM repo_chunks WHERE daw_id = $1::uuid) AS cc
                """,
                daw_id,
            )
            fc = int(agg["fc"] or 0)
            cc = int(agg["cc"] or 0)
            await conn.execute(
                """
                UPDATE daws
                SET repo_sync_status = 'idle', repo_sync_error = NULL,
                    repo_last_synced_at = NOW(), repo_file_count = $2,
                    repo_chunk_count = $3, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                daw_id,
                fc,
                cc,
            )

        _emit_progress(daw_id, {
            "event": "done",
            "files_total": fc,
            "chunks_total": cc,
        })

        return {
            "status": "ok",
            "files_added": added,
            "files_updated": updated,
            "files_skipped": skipped,
            "files_deleted": deleted_count,
            "files_total": fc,
            "chunks_total": cc,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    except Exception as e:
        logger.exception("sync_daw_repo failed daw_id=%s", daw_id)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daws
                SET repo_sync_status = 'error', repo_sync_error = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                daw_id,
                str(e)[:500],
            )
        _emit_progress(daw_id, {"event": "error", "detail": str(e)[:500]})
        return {"status": "error", "error": str(e)[:500]}
