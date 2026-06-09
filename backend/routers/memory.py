"""Per-mode memory blob (markdown) + OpenAI-compatible extraction.

Inference for extraction is routed via the most-recent chat's workspace provider.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_principal, require_admin
from db import get_pool
from services.audit import AuditEventHandle, audit_event
from services.memory.engine import get_engine
from services.provider_client import build_headers, resolve_provider_for_workspace
from services.reasoning_strip import strip_thinking_text

router = APIRouter()
logger = logging.getLogger(__name__)

# Track whether we've migrated mode_memory content to the new engine
_memory_migrated = False


class MemoryPut(BaseModel):
    content: str = ""


class MemoryEntryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    source: str = "manual"


class MemoryEntryPatch(BaseModel):
    content: str = Field(..., min_length=1)


@router.get("/")
async def get_memory(
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content, updated_at FROM mode_memory LIMIT 1",
        )
    if row is None:
        async with audit.targeting("memory", None):
            pass
        return {"content": "", "updated_at": None}

    global _memory_migrated
    if not _memory_migrated:
        content = row["content"] or ""
        if content.strip():
            engine = get_engine()
            await engine.migrate_from_mode_memory(content)
        _memory_migrated = True

    async with audit.targeting("memory", None):
        pass
    return {
        "content": row["content"] or "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.put("/")
async def put_memory(
    body: MemoryPut = Body(),
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mode_memory (content, updated_at)
            VALUES ($1, NOW())
            ON CONFLICT ((1)) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING content, updated_at
            """,
            body.content or "",
        )

    # Sync to the new memory engine
    content = row["content"] or ""
    if content.strip():
        engine = get_engine()
        await engine.manage(content, action="create", metadata={"source": "api_put"})

    async with audit.targeting("memory", None):
        pass
    return {
        "content": content,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/extract")
async def extract_memory(
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat_row = await conn.fetchrow(
            """
            SELECT c.id, c.workspace_id
            FROM chats c
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
            LIMIT 1
            """,
        )
        if chat_row is None:
            raise HTTPException(status_code=400, detail="No chats exist")
        if chat_row["workspace_id"] is None:
            raise HTTPException(
                status_code=400,
                detail="Most recent chat is not in a workspace; cannot resolve provider for memory extraction",
            )

        chat_id = chat_row["id"]
        mem_row = await conn.fetchrow(
            "SELECT content FROM mode_memory LIMIT 1",
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

    # resolve_provider_for_workspace raises HTTPException(400) with the exact
    # spec message if the workspace has no provider configured.
    provider, model = await resolve_provider_for_workspace(chat_row["workspace_id"])

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

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Inference error {resp.status_code}: {resp.text[:500]}",
                )
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Inference request failed: {e}") from e

    choices = data.get("choices") or []
    msg = choices[0].get("message") if choices else {}
    msg = msg or {}
    updated = strip_thinking_text((msg.get("content") or "").strip())
    if not updated:
        raise HTTPException(status_code=502, detail="Model returned empty memory")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mode_memory (content, updated_at)
            VALUES ($1, NOW())
            ON CONFLICT ((1)) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            RETURNING content, updated_at
            """,
            updated,
        )

    # Sync to the new memory engine
    if updated.strip():
        engine = get_engine()
        await engine.manage(
            updated, action="create", metadata={"source": "extraction"}
        )

    async with audit.targeting("memory", None):
        pass
    return {
        "content": row["content"] or "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


class MemorySearchQuery(BaseModel):
    q: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/search")
async def search_memory(
    body: MemorySearchQuery,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Hybrid search across all memory tiers using vector + keyword fusion."""
    engine = get_engine()
    results = await engine.search(body.q, limit=body.limit)
    async with audit.targeting("memory", None):
        pass
    return [
        {
            "path": r.path,
            "score": r.score,
            "snippet": r.snippet,
            "source": r.source,
        }
        for r in results
    ]


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
async def embed_all_memories(
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
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
    async with audit.targeting("memory", None):
        pass
    return {"embedded": count, "total": len(rows)}


@router.get("/entries/")
async def list_memory_entries(
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, source, created_at, updated_at,
                   embedded_at, (embedding IS NOT NULL) AS has_embedding
            FROM memory_entries
            WHERE is_deleted = FALSE
            ORDER BY created_at DESC NULLS LAST, id DESC
            """,
        )
    async with audit.targeting("memory", None):
        pass
    return [_memory_entry_row(r) for r in rows]


@router.post("/entries/")
async def create_memory_entry(
    body: MemoryEntryCreate,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    src = (body.source or "manual").strip().lower()
    if src not in ("manual", "auto"):
        raise HTTPException(status_code=400, detail="source must be manual or auto")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO memory_entries (content, source)
            VALUES ($1, $2)
            RETURNING id, content, source, created_at, updated_at
            """,
            body.content.strip(),
            src,
        )

    # Best-effort dual-write to MemoryEngine
    try:
        engine = get_engine()
        await engine.manage(
            body.content.strip(),
            action="create",
            metadata={"source": src, "scope": "shared"},
        )
    except Exception as exc:
        logger.debug("MemoryEngine dual-write skipped: %s", exc)

    async with audit.targeting("memory", row["id"]):
        pass
    return _memory_entry_row(row)


@router.patch("/entries/{entry_id}")
async def patch_memory_entry(
    entry_id: uuid.UUID,
    body: MemoryEntryPatch,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
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
    async with audit.targeting("memory", entry_id):
        pass
    return _memory_entry_row(row)


@router.delete("/entries/{entry_id}")
async def delete_memory_entry(
    entry_id: uuid.UUID,
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
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
    async with audit.targeting("memory", entry_id):
        pass
    return {"ok": True}
