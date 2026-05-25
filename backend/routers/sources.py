"""Workspace knowledge source upload + listing."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import pathlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from deps import get_principal
from db import get_pool
from services.audit import AuditEventHandle, audit_event
from services.chunking import chunk_text, parse_source_bytes
from services.deid import is_enabled as deid_enabled, redact_chunks
from services.embeddings import EmbeddingError, embed_batch, format_vector

router = APIRouter(prefix="/sources", tags=["sources"])
logger = logging.getLogger(__name__)

UPLOADS_DIR = pathlib.Path("/data/uploads")


def _try_delete_file(file_url: str | None) -> None:
    """Delete a stored file from disk. Silently ignores missing files."""
    if not file_url:
        return
    try:
        pathlib.Path(file_url).unlink(missing_ok=True)
    except OSError:
        pass


def _ext_from_mime(mime: str) -> str:
    m = mime.lower().split(";")[0].strip()
    if m == "application/pdf":
        return ".pdf"
    if "wordprocessingml" in m:
        return ".docx"
    if m in ("text/markdown", "text/x-markdown"):
        return ".md"
    if m.startswith("image/png"):
        return ".png"
    if m.startswith("image/jpeg"):
        return ".jpg"
    if m.startswith("image/tiff"):
        return ".tiff"
    if m.startswith("image/bmp"):
        return ".bmp"
    return ".txt"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mime_to_source_type(mime: str | None) -> str:
    m = (mime or "").lower().split(";")[0].strip()
    if m == "text/plain":
        return "txt"
    if m in ("text/markdown", "text/x-markdown"):
        return "md"
    if m == "application/pdf":
        return "pdf"
    if m == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if m.startswith("image/"):
        return "image"
    return "txt"


def _normalize_declared_mime(declared: str | None) -> str:
    return (declared or "application/octet-stream").lower().split(";")[0].strip()


def _octet_stream_utf8_text_body(raw: bytes) -> bool:
    """Best-effort: extensionless uploads as octet-stream that are plain UTF-8 text."""
    if len(raw) > 10 * 1024 * 1024:
        return False
    preview = raw[:65536]
    if b"\x00" in preview:
        return False
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _resolve_upload_parse_mime(raw: bytes, declared: str | None, filename: str | None) -> str:
    """
    MIME used for parse_source_bytes + ingest. Handles application/octet-stream and bad
    Content-Type when the body is text (by extension or UTF-8 without NUL).
    """
    m = _normalize_declared_mime(declared)
    try:
        parse_source_bytes(raw, m)
        return m
    except ValueError:
        pass
    fn = (filename or "").lower()
    if fn.endswith((".md", ".markdown")):
        parse_source_bytes(raw, "text/markdown")
        return "text/markdown"
    if fn.endswith((".txt", ".text")):
        parse_source_bytes(raw, "text/plain")
        return "text/plain"
    if m == "application/octet-stream" and _octet_stream_utf8_text_body(raw):
        parse_source_bytes(raw, "text/plain")
        return "text/plain"
    raise ValueError(f"Unsupported MIME type: {m}")


async def _ingest_source(source_id: uuid.UUID, workspace_id: uuid.UUID, raw: bytes, mime: str, name: str) -> None:
    pool = await get_pool()
    try:
        text = parse_source_bytes(raw, mime)
        chunks = chunk_text(text, filename=name)
        if not chunks:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE sources
                    SET embedding_status = 'error', error_message = $2, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    source_id,
                    "No text extracted",
                )
            return

        if deid_enabled():
            chunks, deid_findings = redact_chunks(chunks)
            total_findings = sum(len(f) for f in deid_findings)
            if total_findings:
                logger.info(
                    "deid: redacted %d PHI findings across %d chunks for source_id=%s",
                    total_findings, len(chunks), source_id,
                )

        try:
            embeddings = await embed_batch(chunks)
        except EmbeddingError as e:
            logger.error("RAG ingest embedding failed source_id=%s: %s", source_id, e)
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE sources
                    SET embedding_status = 'error', error_message = $2, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    source_id,
                    f"embedding backend failed: {e}"[:900],
                )
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM source_chunks WHERE source_id = $1::uuid", source_id)
                for i, chunk in enumerate(chunks):
                    emb_param = format_vector(embeddings[i])
                    text = chunk.replace('\x00', '')
                    await conn.execute(
                        """
                        INSERT INTO source_chunks (id, source_id, chunk_index, text, embedding)
                        VALUES ($1::uuid, $2::uuid, $3, $4, $5::vector)
                        """,
                        uuid.uuid4(),
                        source_id,
                        i,
                        text,
                        emb_param,
                    )
                await conn.execute(
                    """
                    UPDATE sources
                    SET embedding_status = 'complete', chunk_count = $2, updated_at = NOW(), error_message = NULL
                    WHERE id = $1::uuid
                    """,
                    source_id,
                    len(chunks),
                )
        logger.info("RAG ingest complete source_id=%s chunks=%d", source_id, len(chunks))
    except Exception as e:
        logger.exception("RAG ingest failed source_id=%s", source_id)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM source_chunks WHERE source_id = $1::uuid",
                    source_id,
                )
                await conn.execute(
                    """
                    UPDATE sources
                    SET embedding_status = 'error', error_message = $2, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    source_id,
                    str(e)[:900],
                )
        except Exception:
            pass


@router.post("/{workspace_id}/upload")
async def upload_source(
    workspace_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    _: dict = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "No files provided")
    results = []
    for file in files:
        result = await _upload_single(workspace_id, file)
        results.append(result)
    async with audit.targeting("source", None):
        pass
    if len(results) == 1:
        return results[0]
    return {"sources": results}


async def _upload_single(workspace_id: uuid.UUID, file: UploadFile) -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        return {"filename": file.filename, "error": "Empty file"}
    if len(raw) > 50 * 1024 * 1024:
        return {"filename": file.filename, "error": "File too large (50MB max)"}

    try:
        mime = _resolve_upload_parse_mime(raw, file.content_type, file.filename)
    except ValueError as e:
        return {"filename": file.filename, "error": str(e)}

    stype = _mime_to_source_type(mime)
    h = _sha256(raw)
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not workspace_exists:
            return {"filename": file.filename, "error": "Workspace not found"}
        existing = await conn.fetchval("SELECT id FROM sources WHERE content_hash = $1 AND workspace_id = $2::uuid LIMIT 1", h, workspace_id)
        if existing:
            return {"source_id": str(existing), "filename": file.filename, "status": "already_exists"}

        source_id = uuid.uuid4()
        name = (file.filename or "upload").strip() or "upload"
        file_url = f"/data/uploads/{source_id}{_ext_from_mime(mime)}"
        await conn.execute(
            """
            INSERT INTO sources (
                id, workspace_id, name, source_type, mime_type, file_size_bytes,
                content_hash, embedding_status, file_url, updated_at
            )
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, 'processing', $8, NOW())
            """,
            source_id,
            workspace_id,
            name,
            stype,
            mime,
            len(raw),
            h,
            file_url,
        )

    upload_path = UPLOADS_DIR / f"{source_id}{_ext_from_mime(mime)}"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(raw)

    asyncio.create_task(_ingest_source(source_id, workspace_id, raw, mime, name))
    return {"source_id": str(source_id), "filename": file.filename, "status": "ingesting"}


@router.get("/by-id/{source_id}/content")
async def get_source_content(
    source_id: uuid.UUID,
    _: dict = Depends(get_principal),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, mime_type, file_url FROM sources WHERE id = $1::uuid",
            source_id,
        )
    if row is None:
        raise HTTPException(404, "Source not found")

    file_path = pathlib.Path(row["file_url"] or "")
    if not file_path.exists():
        raise HTTPException(404, "Source file not stored on disk")

    raw = file_path.read_bytes()
    text = parse_source_bytes(raw, row["mime_type"] or "text/plain")
    if deid_enabled():
        from services.deid import redact_text
        result = redact_text(text)
        text = result.text
    return {"id": str(row["id"]), "name": row["name"], "content": text}


@router.get("/{workspace_id}")
async def list_sources(
    workspace_id: uuid.UUID,
    _: dict = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not workspace_exists:
            raise HTTPException(404, "Workspace not found")
        rows = await conn.fetch(
            """
            SELECT id, name, chunk_count, embedding_status, created_at, source_type, mime_type
            FROM sources
            WHERE workspace_id = $1::uuid
            ORDER BY created_at DESC
            """,
            workspace_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "name": r["name"],
                "chunk_count": r["chunk_count"],
                "embedding_status": r["embedding_status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "source_type": r["source_type"],
                "mime_type": r["mime_type"],
            }
        )
    async with audit.targeting("source", workspace_id):
        pass
    return out


class SourcePatch(BaseModel):
    name: str | None = None


@router.patch("/by-id/{source_id}")
async def patch_source(
    source_id: uuid.UUID,
    body: SourcePatch,
    _: dict = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.name is not None:
            await conn.execute(
                "UPDATE sources SET name = $1, updated_at = NOW() WHERE id = $2::uuid",
                body.name.strip(), source_id,
            )
        row = await conn.fetchrow("SELECT id, name FROM sources WHERE id = $1::uuid", source_id)
        if row is None:
            raise HTTPException(404, "Source not found")
    async with audit.targeting("source", source_id):
        pass
    return {"id": str(row["id"]), "name": row["name"]}


@router.delete("/by-id/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    _: dict = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, file_url, content_hash FROM sources WHERE id = $1::uuid", source_id)
        if not row:
            raise HTTPException(404, "Source not found")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sources WHERE id = $1::uuid", source_id)
        others = await conn.fetchval(
            "SELECT COUNT(*) FROM sources WHERE content_hash = $1",
            row["content_hash"],
        )
    if others == 0:
        _try_delete_file(row["file_url"])
    async with audit.targeting("source", source_id):
        pass
    return {"deleted": str(source_id)}


@router.delete("/{workspace_id}/chunks")
async def clear_workspace_chunks(
    workspace_id: uuid.UUID,
    _: dict = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    """Delete all chunks and reset embedding status for all sources in a workspace."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        workspace_exists = await conn.fetchval("SELECT 1 FROM workspaces WHERE id = $1::uuid", workspace_id)
        if not workspace_exists:
            raise HTTPException(404, "Workspace not found")
        result = await conn.fetchval(
            """
            DELETE FROM source_chunks
            WHERE source_id IN (SELECT id FROM sources WHERE workspace_id = $1::uuid)
            RETURNING id
            """,
            workspace_id,
        )
        deleted_count = int(result or 0)
        result = await conn.fetchval(
            """
            UPDATE sources
            SET embedding_status = 'pending', chunk_count = 0, error_message = NULL, updated_at = NOW()
            WHERE workspace_id = $1::uuid
            RETURNING id
            """,
            workspace_id,
        )
        reset_count = int(result or 0)
    async with audit.targeting("source", workspace_id):
        pass
    return {"deleted_chunks": deleted_count, "reset_sources": reset_count}
