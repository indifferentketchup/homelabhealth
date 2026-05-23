"""Providers CRUD + connection-test + live model listing.

Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §3
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from db import get_pool
from deps import require_admin
from services.audit import AuditEventHandle, audit_event
from services.crypto import decrypt_secret, encrypt_secret

router = APIRouter()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────


class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=2048)
    api_key: str | None = None
    enabled: bool = True
    sort_order: int = 0


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _redact_provider(r: Any) -> dict[str, Any]:
    """Shape a providers row for API response. Never returns the api_key."""
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "base_url": r["base_url"],
        "api_key": "***" if r.get("api_key") else None,
        "enabled": bool(r["enabled"]),
        "sort_order": int(r["sort_order"]),
        "last_verified_at": r["last_verified_at"].isoformat() if r.get("last_verified_at") else None,
        "last_verified_status": r["last_verified_status"],
        "is_bundled": bool(r.get("is_bundled") or False),
        "role": r.get("role"),
        "bundle_group": r.get("bundle_group"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def _normalize_base_url(raw: str) -> str:
    v = (raw or "").strip().rstrip("/")
    if not v:
        raise HTTPException(status_code=400, detail="base_url is required")
    return v


def _short_err(e: BaseException, limit: int = 200) -> str:
    s = f"{type(e).__name__}: {e}"
    return s if len(s) <= limit else s[: limit - 1] + "…"


async def _fetch_provider_row(conn: Any, provider_id: uuid.UUID) -> Any:
    row = await conn.fetchrow(
        """
        SELECT id, name, base_url, api_key, enabled, sort_order,
               last_verified_at, last_verified_status,
               is_bundled, role, bundle_group,
               created_at, updated_at
          FROM providers
         WHERE id = $1::uuid
        """,
        provider_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return row


async def _count_references(conn: Any, provider_id: uuid.UUID) -> dict[str, Any]:
    ws_count = await conn.fetchval(
        "SELECT COUNT(*) FROM workspaces WHERE provider_id = $1::uuid",
        provider_id,
    )
    emb_row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = 'embedding_provider_id'"
    )
    rrk_row = await conn.fetchrow(
        "SELECT value FROM global_settings WHERE key = 'reranker_provider_id'"
    )
    pid = str(provider_id)
    return {
        "workspaces": int(ws_count or 0),
        "embedding": bool(emb_row and emb_row["value"] == pid),
        "reranker": bool(rrk_row and rrk_row["value"] == pid),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("")
async def list_providers(
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, base_url, api_key, enabled, sort_order,
                   last_verified_at, last_verified_status,
                   is_bundled, role, bundle_group,
                   created_at, updated_at
              FROM providers
             ORDER BY sort_order ASC, created_at ASC
            """,
        )
    async with audit.targeting("provider", None):
        pass
    return {"items": [_redact_provider(r) for r in rows]}


@router.get("/{provider_id}")
async def get_provider(
    provider_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_provider_row(conn, provider_id)
    async with audit.targeting("provider", provider_id):
        pass
    return _redact_provider(row)


@router.post("", status_code=201)
async def create_provider(
    body: ProviderCreate,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    base_url = _normalize_base_url(body.base_url)

    if body.api_key is not None and body.api_key == "":
        raise HTTPException(
            status_code=400,
            detail="api_key cannot be empty string; send null to clear or omit to keep",
        )
    encrypted_key = encrypt_secret(body.api_key)

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO providers (name, base_url, api_key, enabled, sort_order)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, name, base_url, api_key, enabled, sort_order,
                          last_verified_at, last_verified_status,
                          is_bundled, role, bundle_group,
                          created_at, updated_at
                """,
                name,
                base_url,
                encrypted_key,
                bool(body.enabled),
                int(body.sort_order),
            )
        except Exception as e:
            # UniqueViolation on name surfaces as a generic asyncpg exception; map cleanly.
            msg = str(e)
            if "providers_name_key" in msg or "duplicate key" in msg.lower():
                raise HTTPException(status_code=409, detail="provider name already exists") from e
            raise
    async with audit.targeting("provider", row["id"]):
        pass
    return _redact_provider(row)


@router.patch("/{provider_id}")
async def patch_provider(
    provider_id: uuid.UUID,
    body: ProviderPatch,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    data = body.model_dump(exclude_unset=True)

    # api_key semantics: absent = leave alone; null = clear; non-empty = encrypt; "" = reject.
    update_api_key = False
    new_api_key: str | None = None
    if "api_key" in data:
        v = data["api_key"]
        if v is None:
            update_api_key = True
            new_api_key = None
        elif isinstance(v, str) and v == "":
            raise HTTPException(
                status_code=400,
                detail="api_key cannot be empty string; send null to clear or omit to keep",
            )
        elif isinstance(v, str):
            update_api_key = True
            new_api_key = encrypt_secret(v)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_provider_row(conn, provider_id)

        if row.get("is_bundled"):
            raise HTTPException(
                status_code=403,
                detail="Bundled providers are not editable. Adjust hardware tier in Settings → System.",
            )

        if not data:
            return _redact_provider(row)

        # Build the SET clause dynamically; updated_at always bumps if anything changes.
        new_name = data.get("name", row["name"])
        if isinstance(new_name, str):
            new_name = new_name.strip() or row["name"]
        new_base_url = (
            _normalize_base_url(data["base_url"]) if "base_url" in data else row["base_url"]
        )
        new_enabled = data.get("enabled", row["enabled"])
        new_sort_order = data.get("sort_order", row["sort_order"])

        try:
            if update_api_key:
                updated = await conn.fetchrow(
                    """
                    UPDATE providers
                       SET name = $2,
                           base_url = $3,
                           api_key = $4,
                           enabled = $5,
                           sort_order = $6,
                           updated_at = NOW()
                     WHERE id = $1::uuid
                    RETURNING id, name, base_url, api_key, enabled, sort_order,
                              last_verified_at, last_verified_status,
                              is_bundled, role, bundle_group,
                              created_at, updated_at
                    """,
                    provider_id,
                    new_name,
                    new_base_url,
                    new_api_key,
                    bool(new_enabled),
                    int(new_sort_order),
                )
            else:
                updated = await conn.fetchrow(
                    """
                    UPDATE providers
                       SET name = $2,
                           base_url = $3,
                           enabled = $4,
                           sort_order = $5,
                           updated_at = NOW()
                     WHERE id = $1::uuid
                    RETURNING id, name, base_url, api_key, enabled, sort_order,
                              last_verified_at, last_verified_status,
                              is_bundled, role, bundle_group,
                              created_at, updated_at
                    """,
                    provider_id,
                    new_name,
                    new_base_url,
                    bool(new_enabled),
                    int(new_sort_order),
                )
        except Exception as e:
            msg = str(e)
            if "providers_name_key" in msg or "duplicate key" in msg.lower():
                raise HTTPException(status_code=409, detail="provider name already exists") from e
            raise
    async with audit.targeting("provider", provider_id):
        pass
    return _redact_provider(updated)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: uuid.UUID,
    force: bool = Query(default=False),
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Ensure the provider exists (404 first, bundled check second, references third).
        row = await _fetch_provider_row(conn, provider_id)
        if row.get("is_bundled"):
            raise HTTPException(
                status_code=403,
                detail="Bundled providers are not editable. Adjust hardware tier in Settings → System.",
            )
        refs = await _count_references(conn, provider_id)
        in_use = refs["workspaces"] > 0 or refs["embedding"] or refs["reranker"]

        if in_use and not force:
            raise HTTPException(
                status_code=409,
                detail={"detail": "provider in use", "references": refs},
            )

        async with conn.transaction():
            if refs["embedding"]:
                await conn.execute(
                    "DELETE FROM global_settings WHERE key IN ('embedding_provider_id', 'embedding_model')"
                )
            if refs["reranker"]:
                await conn.execute(
                    "DELETE FROM global_settings WHERE key IN ('reranker_provider_id', 'reranker_model')"
                )
            # Null both provider_id AND model in one UPDATE so the CHECK
            # constraint stays satisfied at every intermediate state. The
            # subsequent DELETE's ON DELETE SET NULL cascade is then a no-op.
            if refs["workspaces"] > 0:
                await conn.execute(
                    "UPDATE workspaces SET provider_id = NULL, model = NULL WHERE provider_id = $1::uuid",
                    provider_id,
                )
            await conn.execute("DELETE FROM providers WHERE id = $1::uuid", provider_id)
    async with audit.targeting("provider", provider_id):
        pass
    return Response(status_code=204)


async def _resolve_embed_model_via_conn() -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT value FROM global_settings WHERE key = 'embedding_model'"
        )
    return val or "BAAI/bge-m3"


async def _resolve_rerank_model_via_conn() -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT value FROM global_settings WHERE key = 'reranker_model'"
        )
    return val or "BAAI/bge-reranker-v2-m3"


def _interpret_embed_response(r: Any) -> tuple[bool, str]:
    if r.status_code >= 400:
        return False, f"error: HTTP {r.status_code}"
    try:
        body = r.json()
        embedding = body.get("data", [{}])[0].get("embedding")
        if not isinstance(embedding, list):
            return False, "error: malformed /v1/embeddings response (no embedding list)"
        dim = len(embedding)
        if dim != 1024:
            return False, f"error: embedding dim mismatch: expected 1024, got {dim}"
        return True, "ok"
    except Exception as e:
        return False, f"error: {_short_err(e)}"


def _interpret_rerank_response(r: Any) -> tuple[bool, str]:
    if r.status_code >= 400:
        return False, f"error: HTTP {r.status_code}"
    try:
        body = r.json()
        results = body.get("results")
        if not isinstance(results, list):
            return False, "error: malformed /rerank response (no results list)"
        return True, "ok"
    except Exception as e:
        return False, f"error: {_short_err(e)}"


def _interpret_models_response(r: Any) -> tuple[bool, str | None, list[str] | None]:
    """Existing /v1/models flow, extracted for symmetry.

    Returns (ok, status_str, model_ids_or_None).
    """
    if r.status_code >= 400:
        return False, f"error: HTTP {r.status_code}", None
    try:
        body = r.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return False, "error: malformed /v1/models response (no 'data' list)", None
        model_ids = [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]
        return True, "ok", model_ids
    except Exception as e:
        return False, f"error: {_short_err(e)}", None


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_provider_row(conn, provider_id)

    base_url = row["base_url"].rstrip("/")
    try:
        key = decrypt_secret(row["api_key"])
    except RuntimeError as e:
        # Bad encryption key configuration is a server-side issue, not an upstream one.
        # Surface as a probe failure so the UI can show it without crashing the request.
        status = f"error: {_short_err(e)}"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE providers SET last_verified_at = NOW(), last_verified_status = $2
                 WHERE id = $1::uuid
                """,
                provider_id,
                status,
            )
        return {"ok": False, "status": status}

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    role = row.get("role")
    model_ids: list[str] | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        try:
            if role == "embed":
                em_model = await _resolve_embed_model_via_conn()
                r = await client.post(
                    f"{base_url}/v1/embeddings",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"model": em_model, "input": ["test"]},
                )
                ok, status = _interpret_embed_response(r)
            elif role == "rerank":
                rr_model = await _resolve_rerank_model_via_conn()
                r = await client.post(
                    f"{base_url}/v1/rerank",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"model": rr_model, "query": "test", "documents": ["a", "b"]},
                )
                ok, status = _interpret_rerank_response(r)
            else:
                # Chat or external: keep existing /v1/models behavior
                r = await client.get(f"{base_url}/v1/models", headers=headers)
                ok, status, model_ids = _interpret_models_response(r)
        except Exception as e:
            ok, status = False, f"error: {_short_err(e)}"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE providers SET last_verified_at = NOW(), last_verified_status = $2
             WHERE id = $1::uuid
            """,
            provider_id,
            status,
        )

    result: dict[str, Any] = {"ok": ok, "status": status}
    if model_ids is not None:
        result["models"] = model_ids
    async with audit.targeting("provider", provider_id):
        pass
    return result


@router.get("/{provider_id}/models")
async def list_provider_models(
    provider_id: uuid.UUID,
    _: dict[str, Any] = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_provider_row(conn, provider_id)

    base_url = row["base_url"].rstrip("/")
    try:
        key = decrypt_secret(row["api_key"])
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"key decrypt failed: {_short_err(e)}",
        ) from e

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get(f"{base_url}/v1/models", headers=headers)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"upstream models fetch failed: {_short_err(e)}",
        ) from e
    async with audit.targeting("provider", provider_id):
        pass
    return r.json()
