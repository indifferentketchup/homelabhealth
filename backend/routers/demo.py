"""Demo data loader: synthetic health records for trying HLH.

POST /api/demo/load    -- create a Demo workspace with synthea fixtures
DELETE /api/demo/unload -- remove the Demo workspace and its records
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from db import get_pool
from deps import require_admin

router = APIRouter()
logger = logging.getLogger(__name__)

DEMO_DIR = pathlib.Path("/app/demo_data")
DEMO_WS_NAME = "Demo"
UPLOADS_DIR = pathlib.Path("/data/uploads")


@router.post("/load")
async def load_demo(
    _: dict[str, Any] = Depends(require_admin),
):
    pool = await get_pool()

    if not DEMO_DIR.exists():
        raise HTTPException(status_code=500, detail="demo data directory not found in image")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    from routers.sources import _ingest_source

    # Collect files first so we can validate before touching the DB.
    files = sorted(f for f in DEMO_DIR.iterdir() if f.suffix == ".txt" and f.read_text().strip())

    # Pre-read file contents before touching the DB.
    file_batch: list[tuple[uuid.UUID, str, bytes]] = [
        (uuid.uuid4(), f.stem, f.read_bytes()) for f in files
    ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            # FOR UPDATE serializes concurrent load calls — prevents two requests
            # from both passing the "no workspace" check and creating duplicates.
            existing = await conn.fetchrow(
                """
                SELECT id,
                       (SELECT bool_and(embedding_status = 'complete')
                        FROM sources WHERE workspace_id = workspaces.id) AS all_complete
                FROM workspaces WHERE name = $1 LIMIT 1 FOR UPDATE
                """,
                DEMO_WS_NAME,
            )
            if existing and existing["all_complete"]:
                return {"status": "exists", "workspace_id": str(existing["id"])}

            if existing:
                logger.info("demo: partial workspace found, removing and re-creating")
                await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", existing["id"])

            ws_id = await conn.fetchval(
                """
                INSERT INTO workspaces (name, description, system_prompt)
                VALUES ($1, 'Synthetic health records for demo purposes.', '')
                RETURNING id
                """,
                DEMO_WS_NAME,
            )

            for source_id, stem, raw in file_batch:
                file_url = str(UPLOADS_DIR / f"{source_id}.txt")
                await conn.execute(
                    """
                    INSERT INTO sources (id, workspace_id, name, source_type, mime_type,
                                         file_size_bytes, embedding_status, file_url)
                    VALUES ($1::uuid, $2::uuid, $3, 'txt', 'text/plain', $4, 'pending', $5)
                    """,
                    source_id, ws_id, stem, len(raw), file_url,
                )

    # Transaction committed. Write files to disk AFTER commit so a write failure
    # doesn't leave orphaned DB rows, and a DB rollback doesn't leave orphaned files.
    written: list[pathlib.Path] = []
    try:
        for source_id, _, raw in file_batch:
            p = UPLOADS_DIR / f"{source_id}.txt"
            p.write_bytes(raw)
            written.append(p)
    except OSError as exc:
        logger.error("demo: file write failed after DB commit, cleaning up: %s", exc)
        for p in written:
            p.unlink(missing_ok=True)
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", ws_id)
        raise HTTPException(status_code=500, detail="Failed to write demo files to disk.")

    # Fire ingest tasks after files are on disk.
    tasks = [
        asyncio.create_task(_ingest_source(sid, ws_id, raw, "text/plain", name))
        for sid, name, raw in file_batch
    ]
    logger.info("demo: created workspace %s with %d sources, %d ingest tasks queued", ws_id, len(tasks), len(tasks))

    return {"status": "loaded", "workspace_id": str(ws_id), "documents": len(tasks)}


@router.delete("/unload")
async def unload_demo(
    _: dict[str, Any] = Depends(require_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ws = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE name = $1 LIMIT 1", DEMO_WS_NAME
        )
        if not ws:
            return {"status": "absent"}
        await conn.execute("DELETE FROM workspaces WHERE id = $1::uuid", ws["id"])
    return {"status": "removed"}
