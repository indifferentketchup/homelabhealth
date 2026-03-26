"""SearXNG client — failures are silent (empty results)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from db import get_pool


async def _load_runtime_config(mode: str) -> dict[str, Any] | None:
    if not mode or mode not in ("booops", "808notes"):
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT safe_search, image_proxy, enabled_engines, autocomplete
            FROM searxng_config
            WHERE mode = $1
            """,
            mode,
        )
    if not row:
        return None
    engines_str = row["enabled_engines"] or ""
    enabled_engines = [p.strip().lower() for p in engines_str.split(",") if p.strip()]
    return {
        "safe_search": int(row["safe_search"] or 0),
        "image_proxy": bool(row["image_proxy"]),
        "enabled_engines": enabled_engines,
        "autocomplete": (row["autocomplete"] or "").strip(),
    }


async def searx_search_sources(
    query: str,
    *,
    mode: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    """
    Returns (sources_for_ui, markdown_block_for_model).
    sources: {title, url}; block is injected into system prompt only (not persisted).
    """
    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    q = (query or "").strip()
    if not base or not q:
        return [], ""

    params: dict[str, str | int] = {"q": q, "format": "json"}
    if mode:
        cfg = await _load_runtime_config(mode)
        if cfg:
            params["safesearch"] = max(0, min(2, int(cfg["safe_search"])))
            eng = cfg.get("enabled_engines") or []
            if eng:
                params["engines"] = ",".join(eng)
            params["image_proxy"] = "true" if cfg["image_proxy"] else "false"
            ac = cfg.get("autocomplete") or ""
            if ac:
                params["autocomplete"] = ac

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(f"{base}/search", params=params)
        if resp.status_code >= 400:
            return [], ""
        data: dict[str, Any] = resp.json()
    except Exception:
        return [], ""

    raw = data.get("results") or []
    sources: list[dict[str, str]] = []
    lines: list[str] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not url:
            continue
        snippet = (item.get("content") or item.get("snippet") or "")
        if isinstance(snippet, str):
            snippet = snippet.strip()[:500]
        else:
            snippet = ""
        label = title or url
        sources.append({"title": label, "url": url})
        if snippet:
            lines.append(f"- {label}\n  URL: {url}\n  {snippet}")
        else:
            lines.append(f"- {label}\n  URL: {url}")

    block = "\n\n".join(lines) if lines else ""
    return sources, block
