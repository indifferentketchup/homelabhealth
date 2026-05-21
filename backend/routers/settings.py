"""Global app settings in `global_settings` (non-route-specific keys)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import require_admin
from db import get_pool
from services.embeddings import EMBEDDING_DIM
from services.provider_client import build_headers, resolve_provider

router = APIRouter()

_UI_LAYOUT_KEY = "ui_layout"

_DEFAULT_UI_LAYOUT: dict[str, Any] = {
    "sidebarWidth": 260,
    "chatMaxWidth": 1200,
    "fontSize": 15,
    "fsNav": 13,
    "fsChat": 15,
    "fsInput": 14,
    "fsHeading": 18,
    "fsCode": 13,
}


def _coerce_layout(obj: dict[str, Any]) -> dict[str, Any]:
    allowed = set(_DEFAULT_UI_LAYOUT.keys())
    out: dict[str, Any] = {**_DEFAULT_UI_LAYOUT}
    for k in allowed:
        if k in obj and obj[k] is not None:
            out[k] = obj[k]
    for key in ("sidebarWidth", "chatMaxWidth", "fontSize", "fsNav", "fsChat", "fsInput", "fsHeading", "fsCode"):
        v = out.get(key)
        if isinstance(v, (int, float)):
            out[key] = int(round(v))
        elif isinstance(v, str) and v.strip():
            try:
                out[key] = int(round(float(v)))
            except ValueError:
                out[key] = _DEFAULT_UI_LAYOUT[key]
        else:
            out[key] = _DEFAULT_UI_LAYOUT[key]
    return out


async def _read_ui_layout(conn: Any) -> dict[str, Any]:
    row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", _UI_LAYOUT_KEY)
    if not row or not row["value"]:
        return {**_DEFAULT_UI_LAYOUT}
    try:
        parsed = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return {**_DEFAULT_UI_LAYOUT}
    if not isinstance(parsed, dict):
        return {**_DEFAULT_UI_LAYOUT}
    return _coerce_layout(parsed)


async def _write_ui_layout(conn: Any, data: dict[str, Any]) -> None:
    merged = _coerce_layout(data)
    await conn.execute(
        """
        INSERT INTO global_settings (key, value)
        VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        _UI_LAYOUT_KEY,
        json.dumps(merged),
    )


@router.get("/layout")
async def get_ui_layout() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _read_ui_layout(conn)


@router.patch("/layout")
async def patch_ui_layout(
    body: dict[str, Any],
    _owner: dict = Depends(require_admin),
) -> dict[str, Any]:
    if not isinstance(body, dict):
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await _read_ui_layout(conn)
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await _read_ui_layout(conn)
        merged = _coerce_layout({**cur, **body})
        await _write_ui_layout(conn, merged)
        return merged

_MODEL_SERVER_KEYS = ("flash_attention", "max_loaded_models", "keep_alive")


def _parse_flash_attention(raw: str | None) -> bool:
    if not raw:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ModelServerConfigPatch(BaseModel):
    """Save: all three fields (single form submit)."""

    flash_attention: bool
    max_loaded_models: int = Field(ge=1, le=8)
    keep_alive: str = Field(min_length=1, max_length=64)


async def _model_server_config_from_conn(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch(
        "SELECT key, value FROM ollama_config WHERE key = ANY($1::text[])",
        list(_MODEL_SERVER_KEYS),
    )
    m = {r["key"]: r["value"] for r in rows}
    try:
        ml = max(1, min(8, int(m.get("max_loaded_models") or "1")))
    except ValueError:
        ml = 1
    ka = (m.get("keep_alive") or "30m").strip() or "30m"
    return {
        "flash_attention": _parse_flash_attention(m.get("flash_attention")),
        "max_loaded_models": ml,
        "keep_alive": ka,
    }


@router.get("/inference")
async def get_model_server_config(_: dict = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _model_server_config_from_conn(conn)


@router.patch("/inference")
async def patch_model_server_config(
    body: ModelServerConfigPatch,
    _: dict = Depends(require_admin),
) -> dict[str, Any]:
    ka = body.keep_alive.strip() or "30m"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ollama_config (key, value) VALUES ('flash_attention', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            "1" if body.flash_attention else "0",
        )
        await conn.execute(
            """
            INSERT INTO ollama_config (key, value) VALUES ('max_loaded_models', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            str(int(body.max_loaded_models)),
        )
        await conn.execute(
            """
            INSERT INTO ollama_config (key, value) VALUES ('keep_alive', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            ka,
        )
        return await _model_server_config_from_conn(conn)


# ──────────────────────────────────────────────────────────────────────────────
# Embedding + reranker role bindings (spec §5).
# Both live as flat key/value rows in global_settings.
# ──────────────────────────────────────────────────────────────────────────────

_EMBEDDING_KEYS = ("embedding_provider_id", "embedding_model")
_RERANKER_KEYS = ("reranker_provider_id", "reranker_model")

_DIM_MISMATCH_TMPL = "embedding dimension mismatch: expected {expected}, got {got}"


class RoleBindingPut(BaseModel):
    """Request body for both /api/settings/embedding and /api/settings/reranker."""

    provider_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=256)


async def _read_role_binding(
    conn: Any, provider_key: str, model_key: str
) -> dict[str, Any]:
    rows = await conn.fetch(
        "SELECT key, value FROM global_settings WHERE key = ANY($1::text[])",
        [provider_key, model_key],
    )
    m = {r["key"]: r["value"] for r in rows}
    return {
        "provider_id": (m.get(provider_key) or None) or None,
        "model": (m.get(model_key) or None) or None,
    }


async def _write_role_binding(
    conn: Any,
    provider_key: str,
    model_key: str,
    provider_id: uuid.UUID | None,
    model: str | None,
) -> None:
    """Both None → delete both rows. Both set → upsert. Caller validates the pair."""
    if provider_id is None and model is None:
        await conn.execute(
            "DELETE FROM global_settings WHERE key = ANY($1::text[])",
            [provider_key, model_key],
        )
        return
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        provider_key,
        str(provider_id),
    )
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        model_key,
        model,
    )


def _validate_pair(provider_id: uuid.UUID | None, model: str | None) -> None:
    """Enforce both-set-or-both-null. Empty/whitespace model counts as null
    here only after the caller has trimmed it — the handler does that."""
    if (provider_id is None) != (model is None):
        raise HTTPException(
            status_code=400,
            detail="provider_id and model must both be set or both null",
        )


async def _probe_embedding_dim(provider_id: uuid.UUID, model: str) -> int:
    """Hit `/v1/embeddings` with one short input; return the embedding length."""
    provider = await resolve_provider(provider_id)  # 404/409 propagate cleanly
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.post(
                f"{provider.base_url}/v1/embeddings",
                json={"model": model, "input": ["probe"]},
                headers=build_headers(provider),
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=f"embedding probe failed: {type(e).__name__}: {e}"
        ) from e

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="embedding probe failed: non-dict response")
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise HTTPException(
            status_code=502, detail="embedding probe failed: response missing 'data' array"
        )
    first = items[0]
    if not isinstance(first, dict):
        raise HTTPException(status_code=502, detail="embedding probe failed: malformed 'data[0]'")
    emb = first.get("embedding")
    if not isinstance(emb, list):
        raise HTTPException(
            status_code=502, detail="embedding probe failed: missing 'embedding' list"
        )
    return len(emb)


@router.get("/embedding")
async def get_embedding_settings(_: dict = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        binding = await _read_role_binding(conn, *_EMBEDDING_KEYS)
    binding["dimension"] = EMBEDDING_DIM
    return binding


@router.put("/embedding")
async def put_embedding_settings(
    body: RoleBindingPut,
    _: dict = Depends(require_admin),
) -> dict[str, Any]:
    raw_model = (body.model or "").strip() if isinstance(body.model, str) else None
    norm_model = raw_model if raw_model else None
    norm_pid = body.provider_id

    _validate_pair(norm_pid, norm_model)

    pool = await get_pool()

    if norm_pid is None and norm_model is None:
        # Disable embeddings.
        async with pool.acquire() as conn:
            await _write_role_binding(conn, *_EMBEDDING_KEYS, None, None)
            binding = await _read_role_binding(conn, *_EMBEDDING_KEYS)
        binding["dimension"] = EMBEDDING_DIM
        return binding

    # Both set → probe before write so the DB state can't drift from a working config.
    dim = await _probe_embedding_dim(norm_pid, norm_model)
    if dim != EMBEDDING_DIM:
        # Exact spec string — load-bearing for the frontend error rendering
        # and for the §9 verification step.
        raise HTTPException(
            status_code=400,
            detail=_DIM_MISMATCH_TMPL.format(expected=EMBEDDING_DIM, got=dim),
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _write_role_binding(conn, *_EMBEDDING_KEYS, norm_pid, norm_model)
        binding = await _read_role_binding(conn, *_EMBEDDING_KEYS)
    binding["dimension"] = EMBEDDING_DIM
    return binding


@router.get("/reranker")
async def get_reranker_settings(_: dict = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _read_role_binding(conn, *_RERANKER_KEYS)


@router.put("/reranker")
async def put_reranker_settings(
    body: RoleBindingPut,
    _: dict = Depends(require_admin),
) -> dict[str, Any]:
    raw_model = (body.model or "").strip() if isinstance(body.model, str) else None
    norm_model = raw_model if raw_model else None
    norm_pid = body.provider_id

    _validate_pair(norm_pid, norm_model)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _write_role_binding(conn, *_RERANKER_KEYS, norm_pid, norm_model)
        return await _read_role_binding(conn, *_RERANKER_KEYS)
