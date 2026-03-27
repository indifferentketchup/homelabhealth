"""Global app settings in `global_settings` (non-route-specific keys)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth_deps import require_admin
from db import get_pool

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
    "fontBody": "Rajdhani",
    "fontMono": "Fira Code",
    "fontFamily": "'Rajdhani', sans-serif",
    "accentColor": "#ff2d78",
    "accentCyan": "#00e5ff",
    "accentPurple": "#9b5de5",
    "bgColor": "#080b14",
    "bgPanel": "#0d1120",
    "bgCard": "#0f1525",
    "textColor": "#cde0ff",
    "textDim": "#5a7a9e",
    "borderColor": "#1e2d50",
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

_OLLAMA_KEYS = ("flash_attention", "max_loaded_models", "keep_alive")


class GlobalSettingsBody(BaseModel):
    context_window_global: int | None = Field(
        default=None,
        ge=1024,
        le=32768,
    )


def _read_context_window(val: str | None) -> int:
    if not val:
        return 16384
    try:
        return max(1024, min(32768, int(val)))
    except ValueError:
        return 16384


@router.get("/global")
async def get_global_settings(_: dict = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM global_settings WHERE key = 'context_window_global'",
        )
    return {"context_window_global": _read_context_window(row["value"] if row else None)}


@router.patch("/global")
async def patch_global_settings(
    body: GlobalSettingsBody,
    _: dict = Depends(require_admin),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if not data:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM global_settings WHERE key = 'context_window_global'",
            )
        return {"context_window_global": _read_context_window(row["value"] if row else None)}

    cw = int(data["context_window_global"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO global_settings (key, value)
            VALUES ('context_window_global', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            str(cw),
        )
    return {"context_window_global": cw}


def _parse_flash_attention(raw: str | None) -> bool:
    if not raw:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


class OllamaConfigPatch(BaseModel):
    """Save: all three fields (single form submit)."""

    flash_attention: bool
    max_loaded_models: int = Field(ge=1, le=8)
    keep_alive: str = Field(min_length=1, max_length=64)


async def _ollama_config_from_conn(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch(
        "SELECT key, value FROM ollama_config WHERE key = ANY($1::text[])",
        list(_OLLAMA_KEYS),
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


@router.get("/ollama")
async def get_ollama_config(_: dict = Depends(require_admin)) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _ollama_config_from_conn(conn)


@router.patch("/ollama")
async def patch_ollama_config(
    body: OllamaConfigPatch,
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
        return await _ollama_config_from_conn(conn)
