"""Pre-flight + runtime health checks for the bundled stack.

Each check returns {"name": str, "status": "ok"|"warn"|"error", "detail": str}.
Spec: docs/superpowers/specs/2026-05-22-a1.5-a1.7-bundled-tail-design.md §2
"""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

import httpx

from db import get_pool


# Status constants
OK = "ok"
WARN = "warn"
ERROR = "error"


async def _check_db_pool() -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"name": "db_pool", "status": OK, "detail": "healthy"}
    except Exception as e:
        return {"name": "db_pool", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_schema_applied() -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM system_profile WHERE id = 1")
        if row is None:
            return {"name": "schema_applied", "status": ERROR, "detail": "system_profile row missing"}
        return {"name": "schema_applied", "status": OK, "detail": "system_profile.id=1 present"}
    except Exception as e:
        return {"name": "schema_applied", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_setup_complete() -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT setup_complete FROM system_profile WHERE id = 1")
        if row and bool(row["setup_complete"]):
            return {"name": "setup_complete", "status": OK, "detail": "true"}
        return {"name": "setup_complete", "status": WARN, "detail": "false — visit Settings → System to pick a tier"}
    except Exception as e:
        return {"name": "setup_complete", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_sidecar(name: str, url: str, ok_msg: str = "reachable") -> dict[str, Any]:
    """Probe a sidecar's health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as c:
            r = await c.get(url)
        if r.status_code == 200:
            return {"name": f"{name}_reachable", "status": OK, "detail": ok_msg}
        return {"name": f"{name}_reachable", "status": WARN, "detail": f"HTTP {r.status_code} — sidecar may still be booting"}
    except httpx.ConnectError:
        return {"name": f"{name}_reachable", "status": ERROR, "detail": f"connection refused to {url}"}
    except Exception as e:
        return {"name": f"{name}_reachable", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_safeguard_version() -> dict[str, Any]:
    """Scoped to 'import succeeds + value non-empty'. No singleton DB version exists yet."""
    try:
        from services.safeguards import SAFEGUARD_VERSION
        if not SAFEGUARD_VERSION or not isinstance(SAFEGUARD_VERSION, str):
            return {"name": "safeguard_version", "status": ERROR, "detail": "SAFEGUARD_VERSION is blank or wrong type"}
        return {"name": "safeguard_version", "status": OK, "detail": SAFEGUARD_VERSION}
    except Exception as e:
        return {"name": "safeguard_version", "status": ERROR, "detail": f"import failed: {type(e).__name__}: {e}"}


def _check_disk_free(label: str, path: str, threshold_gb: int = 5) -> dict[str, Any]:
    try:
        free_gb = shutil.disk_usage(path).free / (1024 ** 3)
        if free_gb >= 10:
            return {"name": label, "status": OK, "detail": f"{free_gb:.1f} GB free at {path}"}
        if free_gb >= threshold_gb:
            return {"name": label, "status": WARN, "detail": f"{free_gb:.1f} GB free at {path} (low headroom)"}
        return {"name": label, "status": ERROR, "detail": f"{free_gb:.1f} GB free at {path} — below {threshold_gb} GB threshold"}
    except Exception as e:
        return {"name": label, "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


def _check_provider_key() -> dict[str, Any]:
    """Reuse services.crypto._key() — single source of truth for validation."""
    raw = (os.environ.get("PROVIDER_KEY_ENCRYPTION_KEY") or "").strip()
    if not raw:
        return {
            "name": "provider_key",
            "status": WARN,
            "detail": "PROVIDER_KEY_ENCRYPTION_KEY unset — provider api_keys + HF token stored in cleartext",
        }
    try:
        from services.crypto import _key
        k = _key()
        if k is None or len(k) != 32:
            return {"name": "provider_key", "status": ERROR, "detail": "key resolution returned None/wrong length"}
        return {"name": "provider_key", "status": OK, "detail": "32 bytes, valid base64"}
    except Exception as e:
        return {"name": "provider_key", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_hf_token() -> dict[str, Any]:
    """Configured via DB (hf_token.get) OR HF_TOKEN env."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            from services.hf_token import get as hf_get
            token = await hf_get(conn)
        if token:
            return {"name": "hf_token", "status": OK, "detail": "configured via DB"}
        env_token = (os.environ.get("HF_TOKEN") or "").strip()
        if env_token:
            return {"name": "hf_token", "status": OK, "detail": "configured via env"}
        return {
            "name": "hf_token",
            "status": WARN,
            "detail": "unset — gated models (MedGemma) will fail with 401",
        }
    except Exception as e:
        return {"name": "hf_token", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def run_checks() -> list[dict[str, Any]]:
    """Run all 11 checks. Returns ordered list."""
    return [
        await _check_db_pool(),
        await _check_schema_applied(),
        await _check_setup_complete(),
        await _check_sidecar("hlh_chat", "http://hlh_chat:9610/health"),
        await _check_sidecar("hlh_infer", "http://hlh_infer:9611/health"),
        await _check_sidecar("hlh_search", "http://hlh_search:8080/healthz"),
        await _check_safeguard_version(),
        _check_disk_free("disk_free_data", "/data"),
        _check_disk_free("disk_free_models", "/models"),
        _check_provider_key(),
        await _check_hf_token(),
    ]


def summarize(checks: list[dict[str, Any]]) -> dict[str, int]:
    out = {"ok": 0, "warn": 0, "error": 0}
    for c in checks:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


# CLI entrypoint
def _print_cli(checks: list[dict[str, Any]]) -> int:
    SYMBOLS = {"ok": "✓", "warn": "⚠", "error": "✗"}
    for c in checks:
        sym = SYMBOLS.get(c["status"], "?")
        print(f"{sym} {c['name']}: {c['detail']}")
    s = summarize(checks)
    print()
    print(f"{s['warn']} warnings, {s['error']} errors.")
    return 0 if s["error"] == 0 else 1


def _main_cli() -> int:
    async def _run():
        from db import init_pool, close_pool
        await init_pool()
        try:
            return await run_checks()
        finally:
            await close_pool()
    checks = asyncio.run(_run())
    return _print_cli(checks)


if __name__ == "__main__":
    import sys
    sys.exit(_main_cli())
