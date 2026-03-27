"""808notes (and shared) knowledge source upload + listing."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth_deps import assert_daw_mutable, fetch_daw_if_visible, get_principal
from db import get_chroma_collection, get_pool
from services.chunking import chunk_text, parse_source_bytes
from services.embeddings import embed_batch

router = APIRouter(prefix="/sources", tags=["sources"])
logger = logging.getLogger(__name__)


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
    return "txt"


async def _ingest_source(source_id: uuid.UUID, daw_id: uuid.UUID, raw: bytes, mime: str, name: str) -> None:
    pool = await get_pool()
    try:
        text = parse_source_bytes(raw, mime)
        chunks = chunk_text(text)
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

        embeddings = await embed_batch(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("embedding count mismatch")

        sid = str(source_id)
        did = str(daw_id)
        ids_chroma = [f"{sid}_{i}" for i in range(len(chunks))]
        metadatas = [
            {"source_id": sid, "daw_id": did, "chunk_index": str(i), "source_name": name}
            for i in range(len(chunks))
        ]

        collection = get_chroma_collection(did)
        collection.add(ids=ids_chroma, documents=chunks, embeddings=embeddings, metadatas=metadatas)

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM source_chunks WHERE source_id = $1::uuid", source_id)
                for i, chunk in enumerate(chunks):
                    await conn.execute(
                        """
                        INSERT INTO source_chunks (id, source_id, chunk_index, text)
                        VALUES ($1::uuid, $2::uuid, $3, $4)
                        """,
                        uuid.uuid4(),
                        source_id,
                        i,
                        chunk,
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
        try:
            coll = get_chroma_collection(str(daw_id))
            coll.delete(ids=[f"{source_id}_{i}" for i in range(500)])
        except Exception:
            pass


@router.post("/{daw_id}/upload")
async def upload_source(
    daw_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: dict = Depends(get_principal),
) -> dict[str, Any]:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    max_b = 50 * 1024 * 1024
    if principal["kind"] == "member":
        max_b = 5 * 1024 * 1024
    if len(raw) > max_b:
        raise HTTPException(413, "File too large")

    mime = file.content_type or "application/octet-stream"
    stype = _mime_to_source_type(mime)
    try:
        parse_source_bytes(raw, mime)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    h = _sha256(raw)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await fetch_daw_if_visible(conn, principal, daw_id)
        if principal["kind"] == "member":
            n = await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM sources s
                INNER JOIN daws d ON d.id = s.daw_id
                WHERE d.owner_id = $1::uuid
                """,
                principal["user_id"],
            )
            cf = await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM daw_context_files f
                INNER JOIN daws d ON d.id = f.daw_id
                WHERE d.owner_id = $1::uuid
                """,
                principal["user_id"],
            )
            if int(n or 0) + int(cf or 0) >= 10:
                raise HTTPException(429, detail="upload_limit_reached")

        existing = await conn.fetchval("SELECT id FROM sources WHERE content_hash = $1 LIMIT 1", h)
        if existing:
            return {"source_id": str(existing), "status": "already_exists"}

        daw = await conn.fetchval("SELECT id FROM daws WHERE id = $1::uuid", daw_id)
        if not daw:
            raise HTTPException(404, "DAW not found")

        source_id = uuid.uuid4()
        name = (file.filename or "upload").strip() or "upload"
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
            name,
            stype,
            mime,
            len(raw),
            h,
        )

    asyncio.create_task(_ingest_source(source_id, daw_id, raw, mime, name))
    return {"source_id": str(source_id), "status": "ingesting"}


@router.get("/{daw_id}")
async def list_sources(
    daw_id: uuid.UUID,
    principal: dict = Depends(get_principal),
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await fetch_daw_if_visible(conn, principal, daw_id)
        rows = await conn.fetch(
            """
            SELECT id, name, chunk_count, embedding_status, created_at, source_type, mime_type
            FROM sources
            WHERE daw_id = $1::uuid
            ORDER BY created_at DESC
            """,
            daw_id,
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
    return out


@router.delete("/by-id/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    principal: dict = Depends(get_principal),
) -> dict[str, str]:
    if principal["kind"] == "guest":
        raise HTTPException(403, "Forbidden")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, daw_id FROM sources WHERE id = $1::uuid", source_id)
        if not row:
            raise HTTPException(404, "Source not found")
        await assert_daw_mutable(conn, principal, row["daw_id"])
        did = str(row["daw_id"])

    try:
        coll = get_chroma_collection(did)
        coll.delete(where={"source_id": str(source_id)})
    except Exception as e:
        logger.debug("Chroma delete best-effort: %s", e)

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sources WHERE id = $1::uuid", source_id)

    return {"deleted": str(source_id)}
