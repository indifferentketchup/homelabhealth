"""Per-mode memory blob (markdown) + Ollama extraction."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_deps import get_principal, require_admin
from db import get_pool

router = APIRouter()
logger = logging.getLogger(__name__)


def _norm_mode(m: str) -> str:
    return m if m in ("booops", "808notes") else "booops"


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


class MemoryPut(BaseModel):
    content: str = ""


class MemoryEntryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    source: str = "manual"


class MemoryEntryPatch(BaseModel):
    content: str = Field(..., min_length=1)


@router.get("/")
async def get_memory(mode: str = Query("booops"), _: dict = Depends(require_admin)):
    m = _norm_mode(mode)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mode, content, updated_at FROM mode_memory WHERE mode = $1",
            m,
        )
    if row is None:
        return {"mode": m, "content": "", "updated_at": None}
    return {
        "mode": row["mode"],
        "content": row["content"] or "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.put("/")
async def put_memory(mode: str = Query("booops"), body: MemoryPut = Body(), _: dict = Depends(require_admin)):
    m = _norm_mode(mode)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mode_memory (mode, content, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (mode) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING mode, content, updated_at
            """,
            m,
            body.content or "",
        )
    return {
        "content": row["content"] or "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/extract")
async def extract_memory(mode: str = Query("booops"), _: dict = Depends(require_admin)):
    m = _norm_mode(mode)
    model = (os.environ.get("DEFAULT_MODEL") or "qwen3.5:9b").strip()
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat_id = await conn.fetchval(
            """
            SELECT c.id
            FROM chats c
            WHERE c.mode = $1
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
            LIMIT 1
            """,
            m,
        )
        if chat_id is None:
            raise HTTPException(status_code=400, detail="No chats exist for this mode")

        mem_row = await conn.fetchrow(
            "SELECT content FROM mode_memory WHERE mode = $1",
            m,
        )
        current_memory = (mem_row["content"] or "") if mem_row else ""

        msg_rows = await conn.fetch(
            """
            WITH recent AS (
                SELECT m.id, m.role, m.content, m.created_at
                FROM messages m
                WHERE m.chat_id = $1::uuid
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 20
            )
            SELECT role, content FROM recent
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

    lines: list[str] = []
    for r in msg_rows:
        role = r["role"]
        content = (r["content"] or "").strip()
        if not content:
            continue
        lines.append(f"{role.upper()}: {content}")
    messages_text = "\n".join(lines) if lines else "(empty)"

    user_prompt = (
        "You are a memory extraction assistant. Given the conversation below and the existing memory, "
        "update the memory to reflect new facts about the user. Keep it concise — use markdown headings "
        "and bullet points. Do not repeat existing facts. Do not invent facts. "
        "Return only the updated memory text, nothing else.\n\n"
        f"Existing memory:\n{current_memory}\n\n"
        f"Recent conversation:\n{messages_text}"
    )

    base = _ollama_base()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(f"{base}/api/chat", json=payload)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Ollama error {resp.status_code}: {resp.text[:500]}",
                )
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {e}") from e

    msg = data.get("message") or {}
    updated = (msg.get("content") or "").strip()
    if not updated:
        raise HTTPException(status_code=502, detail="Model returned empty memory")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mode_memory (mode, content, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (mode) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING content, updated_at
            """,
            m,
            updated,
        )

    return {
        "content": row["content"] or "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _memory_entry_row(r: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(r["id"]),
        "content": r["content"] or "",
        "source": r["source"] or "manual",
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }
    if "embedded_at" in r:
        ea = r["embedded_at"]
        out["embedded_at"] = ea.isoformat() if ea else None
    if "has_embedding" in r:
        out["has_embedding"] = bool(r["has_embedding"])
    return out


@router.post("/embed-all")
async def embed_all_memories(principal: dict[str, Any] = Depends(get_principal)):
    if principal.get("kind") != "owner":
        raise HTTPException(status_code=403, detail="owner_only")
    pool = await get_pool()
    from services.embeddings import embed_text

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content FROM memory_entries
            WHERE embedding IS NULL AND is_deleted = FALSE
            """
        )
    count = 0
    for row in rows:
        try:
            emb = await embed_text(row["content"])
            if emb:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE memory_entries
                        SET embedding = $1::vector, embedded_at = NOW()
                        WHERE id = $2::uuid
                        """,
                        str(emb),
                        row["id"],
                    )
                count += 1
        except Exception as e:
            logger.warning("embed_all_memories failed for %s: %s", row["id"], e)
    return {"embedded": count, "total": len(rows)}


@router.get("/entries/")
async def list_memory_entries(mode: str = Query("booops"), _: dict = Depends(require_admin)):
    m = _norm_mode(mode)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, source, created_at, updated_at,
                   embedded_at, (embedding IS NOT NULL) AS has_embedding
            FROM memory_entries
            WHERE mode = $1 AND is_deleted = FALSE
            ORDER BY created_at DESC NULLS LAST, id DESC
            """,
            m,
        )
    return [_memory_entry_row(r) for r in rows]


@router.post("/entries/")
async def create_memory_entry(
    body: MemoryEntryCreate,
    mode: str = Query("booops"),
    _: dict = Depends(require_admin),
):
    m = _norm_mode(mode)
    src = (body.source or "manual").strip().lower()
    if src not in ("manual", "auto"):
        raise HTTPException(status_code=400, detail="source must be manual or auto")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO memory_entries (content, source, mode)
            VALUES ($1, $2, $3)
            RETURNING id, content, source, created_at, updated_at
            """,
            body.content.strip(),
            src,
            m,
        )
    return _memory_entry_row(row)


@router.patch("/entries/{entry_id}")
async def patch_memory_entry(
    entry_id: uuid.UUID,
    body: MemoryEntryPatch,
    _: dict = Depends(require_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE memory_entries
            SET content = $2, updated_at = NOW()
            WHERE id = $1::uuid AND is_deleted = FALSE
            RETURNING id, content, source, created_at, updated_at
            """,
            entry_id,
            body.content.strip(),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return _memory_entry_row(row)


@router.delete("/entries/{entry_id}")
async def delete_memory_entry(entry_id: uuid.UUID, _: dict = Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE memory_entries
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE id = $1::uuid AND is_deleted = FALSE
            """,
            entry_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"ok": True}
