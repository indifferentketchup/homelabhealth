"""Demo data loader: synthetic patient records for trying HLH.

POST /api/demo/load    -- create a Demo workspace with synthea fixtures
DELETE /api/demo/unload -- remove the Demo workspace and its records
"""

from __future__ import annotations

import asyncio
import json
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


def _fhir_bundle_to_text(data: dict) -> str:
    """Convert a FHIR Bundle to readable text for chunking + embedding."""
    parts: list[str] = []
    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rtype = r.get("resourceType", "")
        if rtype == "Patient":
            names = r.get("name", [{}])
            name = f"{' '.join(names[0].get('given', []))} {names[0].get('family', '')}"
            parts.append(f"Patient: {name}")
            parts.append(f"Gender: {r.get('gender', 'unknown')}")
            parts.append(f"Date of birth: {r.get('birthDate', 'unknown')}")
            addr = r.get("address", [{}])[0] if r.get("address") else {}
            if addr:
                parts.append(f"Address: {addr.get('city', '')}, {addr.get('state', '')} {addr.get('postalCode', '')}")
            for ident in r.get("identifier", []):
                parts.append(f"MRN: {ident.get('value', '')}")
        elif rtype == "Condition":
            codings = r.get("code", {}).get("coding", [])
            for c in codings:
                parts.append(f"Condition: {c.get('display', c.get('code', 'unknown'))}")
            onset = r.get("onsetDateTime", "")
            if onset:
                parts.append(f"Onset: {onset}")
        else:
            parts.append(f"{rtype}: {json.dumps(r, indent=2)[:500]}")
    return "\n".join(parts)


@router.post("/load")
async def load_demo(
    _: dict[str, Any] = Depends(require_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE name = $1 LIMIT 1", DEMO_WS_NAME
        )
        if existing:
            return {"status": "exists", "workspace_id": str(existing["id"])}

        ws_id = await conn.fetchval(
            """
            INSERT INTO workspaces (name, description, system_prompt)
            VALUES ($1, 'Synthetic patient records for demo purposes.', '')
            RETURNING id
            """,
            DEMO_WS_NAME,
        )

    if not DEMO_DIR.exists():
        raise HTTPException(status_code=500, detail="demo data directory not found in image")

    loaded = 0
    for f in sorted(DEMO_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        text = _fhir_bundle_to_text(data)
        if not text.strip():
            continue

        source_id = uuid.uuid4()
        raw = text.encode("utf-8")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sources (id, workspace_id, name, source_type, mime_type,
                                     file_size_bytes, embedding_status)
                VALUES ($1::uuid, $2::uuid, $3, 'txt', 'text/plain', $4, 'pending')
                """,
                source_id, ws_id, f.stem.replace("_", " ").title(), len(raw),
            )

        from routers.sources import _ingest_source
        asyncio.create_task(_ingest_source(source_id, ws_id, raw, "text/plain", f.stem))
        loaded += 1

    return {"status": "loaded", "workspace_id": str(ws_id), "documents": loaded}


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
