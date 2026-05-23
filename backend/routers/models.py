"""Bundled-AI model artifact endpoints — Phase 1.

GET    /api/models                  — list all bundled_models rows
GET    /api/models/{id}             — single row
POST   /api/models/{id}/pull        — background-task trigger (202)
POST   /api/models/pull-for-tier    — body {tier}; queues every role with a spec (202)
POST   /api/models/{id}/cancel      — flip cancel flag for an active pull

All admin-only via the existing `require_admin` dep. Background tasks are
tracked in a module-level set so they don't get garbage-collected mid-pull.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from deps import require_admin
from services.audit import AuditEventHandle, audit_event
from services import model_puller
from services.model_puller import ALL_TIERS

router = APIRouter()


# Keep references to active background tasks; without this they can be
# garbage-collected mid-flight (Python may discard tasks not awaited and
# without a strong reference).
_BG_TASKS: set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> asyncio.Task:
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "role": r["role"],
        "tier": r["tier"],
        "model_id": r["model_id"],
        "quant": r["quant"],
        "repo": r["repo"],
        "filename": r["filename"],
        "expected_bytes": int(r["expected_bytes"]) if r["expected_bytes"] is not None else None,
        "pulled_bytes": int(r["pulled_bytes"] or 0),
        "sha256": r["sha256"],
        "license": r["license"],
        "license_url": r["license_url"],
        "status": r["status"],
        "error_message": r["error_message"],
        "pull_started_at": r["pull_started_at"].isoformat() if r.get("pull_started_at") else None,
        "pull_finished_at": r["pull_finished_at"].isoformat() if r.get("pull_finished_at") else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


_SELECT_COLS = (
    "id, role, tier, model_id, quant, repo, filename, expected_bytes, "
    "pulled_bytes, sha256, license, license_url, status, error_message, "
    "pull_started_at, pull_finished_at, created_at, updated_at"
)


class PullForTierBody(BaseModel):
    tier: str = Field(..., min_length=1, max_length=64)


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints.
# ──────────────────────────────────────────────────────────────────────────────


@router.get("")
async def list_models(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_SELECT_COLS} FROM bundled_models "
            "ORDER BY role, tier, model_id"
        )
    return {"items": [_row(r) for r in rows]}


@router.get("/{model_id}")
async def get_model(
    model_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SELECT_COLS} FROM bundled_models WHERE id = $1::uuid",
            model_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="model not found")
    return _row(row)


@router.post("/{model_id}/pull", status_code=202)
async def pull_one(
    model_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SELECT_COLS} FROM bundled_models WHERE id = $1::uuid",
            model_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="model not found")
    if row["status"] == "pulling":
        raise HTTPException(status_code=409, detail="model is already pulling")
    if row["status"] == "ready":
        # Idempotent retry path — allow re-pull but tell the caller so they
        # can confirm. Frontend re-uses the same button label "Pull".
        pass

    _track(asyncio.create_task(model_puller.pull_model(pool, str(model_id))))
    async with audit.targeting("models", model_id):
        pass
    return _row(row)


@router.post("/pull-for-tier", status_code=202)
async def pull_for_tier(
    body: PullForTierBody,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    if body.tier not in ALL_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid tier: {body.tier!r}; allowed: {sorted(ALL_TIERS)}",
        )
    pool = await get_pool()
    queued = await model_puller.pull_for_tier(pool, body.tier)
    for _role, mid in queued.items():
        _track(asyncio.create_task(model_puller.pull_model(pool, mid)))
    async with audit.targeting("models", None):
        pass
    return {"queued": list(queued.values())}


@router.post("/{model_id}/cancel", status_code=200)
async def cancel(
    model_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
) -> dict[str, Any]:
    triggered = model_puller.request_cancel(str(model_id))
    async with audit.targeting("models", model_id):
        pass
    return {"ok": True, "cancel_requested": triggered}
