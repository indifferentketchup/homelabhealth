"""Resolve Ollama base URL per model via ollamactl machine assignments."""

from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import quote

import httpx

OLLAMACTL_URL = os.getenv("OLLAMACTL_URL", "http://100.114.205.53:8700")

_cache: dict[str, tuple[float, str]] = {}
_lock = asyncio.Lock()
_TTL_SEC = 60.0


async def get_ollama_url_for_model(model_name: str) -> str:
    """
    Ask ollamactl for the assigned machine URL for this model.
    Returns the ollama_url string, or raises ValueError if unassigned.
    Caches result in-memory for 60 seconds to avoid per-request overhead.
    """
    key = (model_name or "").strip()
    if not key:
        raise ValueError("Model name is empty")

    now = time.monotonic()
    async with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL_SEC:
            return hit[1]

    base = OLLAMACTL_URL.rstrip("/")
    enc = quote(key, safe="")
    url = f"{base}/api/machines/route/{enc}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(url)
    except httpx.HTTPError as e:
        raise ValueError(f"Could not reach ollamactl for routing: {e}") from e

    if r.status_code == 404:
        raise ValueError(f"Model '{key}' is not assigned to any machine")

    if r.status_code >= 400:
        detail = (r.text or r.reason_phrase or "")[:2000]
        raise ValueError(f"ollamactl routing error ({r.status_code}): {detail}")

    try:
        data = r.json()
    except Exception as e:
        raise ValueError("Invalid JSON from ollamactl route endpoint") from e

    ollama_url = str(data.get("ollama_url") or "").rstrip("/")
    if not ollama_url:
        raise ValueError("ollamactl returned empty ollama_url")

    async with _lock:
        _cache[key] = (now, ollama_url)

    return ollama_url
