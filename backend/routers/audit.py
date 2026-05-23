"""Audit log read endpoint.

GET /api/audit/recent?limit=100&offset=0 — newest-first, no hash fields.
Wrapped with audit_event so that reading the audit log is itself auditable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from db import get_pool
from deps import require_owner
from services.audit import AuditEventHandle, audit_event

router = APIRouter()


@router.get("/recent")
async def get_recent_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _owner: dict[str, Any] = Depends(require_owner),
    audit: AuditEventHandle = Depends(audit_event),
):
    async with audit.targeting("audit", None):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, ts, request_id, actor, action, target_type, target_id, status_code
                FROM audit_log
                ORDER BY id DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            total = await conn.fetchval("SELECT COUNT(*)::int FROM audit_log")

    return {
        "rows": [
            {
                "id": r["id"],
                "ts": r["ts"].isoformat() if r["ts"] else None,
                "request_id": str(r["request_id"]),
                "actor": r["actor"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "status_code": r["status_code"],
            }
            for r in rows
        ],
        "total": total,
    }
