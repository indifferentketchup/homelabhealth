"""System hardware detection + tier picker (Phase 0).

Design: docs/hlh_phase0_design.md §API endpoints.

Endpoints (all admin-only via the existing `require_admin` dep, same shape
as `routers/providers.py`):

    GET  /api/system/hardware  — live sysinfo collection, no DB write.
    GET  /api/system/profile   — current singleton row + computed
                                 `recommended_tier`.
    PUT  /api/system/profile   — body {tier, tier_source}; validates tier
                                 against ALL_TIERS; sets chosen_at = NOW(),
                                 setup_complete = TRUE.
    POST /api/system/redetect  — re-run sysinfo, store under sysinfo_json,
                                 update detected_at; never changes tier.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from db import get_pool
from deps import require_admin
from services.audit import AuditEventHandle, audit_event
from services import bundled_providers
from services.sysinfo import ALL_TIERS, collect, recommend_tier

router = APIRouter()


_TIER_SOURCES = ("auto", "manual")


class ProfilePut(BaseModel):
    tier: str = Field(..., min_length=1, max_length=64)
    tier_source: str = Field(default="manual", min_length=1, max_length=32)




def _profile_response(row: Any) -> dict[str, Any]:
    """Shape the system_profile row + the computed recommended_tier.

    asyncpg's default behavior for JSONB returns the column as a `str`
    (the raw JSON text) unless a codec is registered on the connection.
    Without modifying db.py to register one, we parse on read here.
    """
    sj = row["sysinfo_json"]
    sysinfo_json: dict[str, Any]
    if isinstance(sj, dict):
        sysinfo_json = sj
    elif isinstance(sj, str):
        try:
            parsed = json.loads(sj)
        except json.JSONDecodeError:
            parsed = None
        sysinfo_json = parsed if isinstance(parsed, dict) else {}
    else:
        sysinfo_json = {}
    return {
        "id": int(row["id"]),
        "tier": row["tier"],
        "tier_source": row["tier_source"],
        "sysinfo_json": sysinfo_json,
        "detected_at": row["detected_at"].isoformat() if row["detected_at"] else None,
        "chosen_at": row["chosen_at"].isoformat() if row["chosen_at"] else None,
        "setup_complete": bool(row["setup_complete"]),
        "acknowledged_at": row["acknowledged_at"].isoformat() if row.get("acknowledged_at") else None,
        "recommended_tier": recommend_tier(sysinfo_json),
    }


_PROFILE_COLS = (
    "id, tier, tier_source, sysinfo_json, detected_at, chosen_at, setup_complete, acknowledged_at"
)


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints.
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/hardware")
async def get_hardware(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Live sysinfo collection. Does not write to DB."""
    return collect()


@router.get("/profile")
async def get_profile(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Current singleton row + the recommended_tier computed from stored sysinfo_json."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_PROFILE_COLS} FROM system_profile WHERE id = 1"
        )
    if row is None:
        # Shouldn't happen (singleton row seeded by schema), but fail clearly.
        raise HTTPException(status_code=503, detail="system_profile row missing")
    return _profile_response(row)


@router.put("/profile")
async def put_profile(
    body: ProfilePut,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    """Persist operator's tier choice. Sets chosen_at = NOW(), setup_complete = TRUE."""
    if body.tier not in ALL_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid tier: {body.tier!r}; allowed: {sorted(ALL_TIERS)}",
        )
    if body.tier_source not in _TIER_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid tier_source: {body.tier_source!r}; allowed: {list(_TIER_SOURCES)}",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE system_profile
               SET tier = $1, tier_source = $2, chosen_at = NOW(), setup_complete = TRUE
             WHERE id = 1
            RETURNING {_PROFILE_COLS}
            """,
            body.tier,
            body.tier_source,
        )
        if row is None:
            raise HTTPException(status_code=503, detail="system_profile row missing")
        await bundled_providers.apply_bundled_bindings(conn, body.tier)
    async with audit.targeting("system", None):
        pass
    return _profile_response(row)


@router.post("/redetect")
async def redetect(
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    """Re-run sysinfo collection, store under sysinfo_json, update detected_at.

    Does NOT change `tier`, `tier_source`, or `setup_complete`. The operator
    explicitly picks via PUT /profile after seeing the new detection.
    """
    fresh = collect()
    pool = await get_pool()
    # JSONB write convention: pass json.dumps(d), per CLAUDE.md `asyncpg + JSONB`.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE system_profile
               SET sysinfo_json = $1::jsonb, detected_at = NOW()
             WHERE id = 1
            RETURNING {_PROFILE_COLS}
            """,
            json.dumps(fresh),
        )
    if row is None:
        raise HTTPException(status_code=503, detail="system_profile row missing")
    async with audit.targeting("system", None):
        pass
    return _profile_response(row)




@router.post("/acknowledge")
async def post_acknowledge(
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Stamp acknowledged_at = NOW() on the singleton system_profile row."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE system_profile SET acknowledged_at = NOW() WHERE id = 1"
        )
    async with audit.targeting("system", None):
        pass
    return Response(status_code=204)


@router.get("/doctor")
async def get_doctor(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    from hlh.doctor import run_checks, summarize
    all_checks = await run_checks()
    checks = [c for c in all_checks if not c.get("advanced")]
    return {"checks": checks, "summary": summarize(checks)}
