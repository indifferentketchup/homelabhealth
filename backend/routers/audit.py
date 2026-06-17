"""Audit log read endpoints.

GET /api/audit/recent?limit=100&offset=0  -  newest-first, no hash fields.
GET /api/audit/refusals?limit=50&offset=0  -  safeguard.* events only.
GET /api/audit/recover?level=N&session_id=X  -  graded context recovery (L0-L4).
Wrapped with audit_event so that reading the audit log is itself auditable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from db import get_pool
from deps import require_owner
from services.audit import AuditEventHandle, audit_event
# Import audit_recovery to register its hooks AND make recovery fns available.
from services.audit_recovery import recover as recovery_query

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


@router.get("/refusals")
async def get_refusals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _owner: dict[str, Any] = Depends(require_owner),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Return audit_log rows where action starts with ``safeguard.``."""
    async with audit.targeting("audit", None):
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, ts, action, target_type, target_id
                FROM audit_log
                WHERE action LIKE 'safeguard.%'
                ORDER BY ts DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM audit_log WHERE action LIKE 'safeguard.%'"
            )

    return {
        "rows": [
            {
                "id": r["id"],
                "ts": r["ts"].isoformat() if r["ts"] else None,
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/recover")
async def get_audit_recovery(
    level: int = Query(0, ge=0, le=4),
    session_id: str | None = Query(None, description="UUID to filter by request_id"),
    limit: int = Query(20, ge=1, le=500),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=10, le=200),
    _owner: dict[str, Any] = Depends(require_owner),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Graded context recovery from the audit log.

    Levels:
      0  -  Index summary (session count, timestamps, last 5 events)
      1  -  Session trail (last N events, optionally by session_id)
      2  -  Corrections (correction/edit events only)
      3  -  Full context (paginated complete trail)
      4  -  Cross-day aggregates (event type distribution, daily counts, top actors)
    """
    async with audit.targeting("audit", f"recover/level={level}"):
        return await recovery_query(
            level=level,
            session_id=session_id,
            limit=limit,
            page=page,
            page_size=page_size,
        )
