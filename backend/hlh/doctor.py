"""Pre-flight + runtime health checks for the bundled stack.

Each check returns {"name": str, "status": "ok"|"warn"|"error", "detail": str}.
Spec: docs/superpowers/specs/2026-05-22-a1.5-a1.7-bundled-tail-design.md §2
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
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


def _check_luks_status() -> dict[str, Any]:
    """Best-effort check that docker data root sits on LUKS (dm-crypt)."""
    try:
        # Step 1: try to resolve docker data root
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.DockerRootDir}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                root = result.stdout.strip() or "/var/lib/docker"
            else:
                root = "/var/lib/docker"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            root = "/var/lib/docker"

        # Step 2: find the block device for this path
        try:
            df_result = subprocess.run(
                ["df", "--output=source", root],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if df_result.returncode != 0:
                return {
                    "name": "luks_status",
                    "status": WARN,
                    "detail": "luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md",
                }
            lines = df_result.stdout.strip().splitlines()
            # df output has a header line; source is second line
            source = lines[-1].strip() if len(lines) >= 2 else lines[0].strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return {
                "name": "luks_status",
                "status": WARN,
                "detail": "luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md",
            }

        # Step 3: check lsblk TYPE column for the source device
        try:
            lsblk_result = subprocess.run(
                ["lsblk", "-no", "TYPE", source],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if lsblk_result.returncode != 0:
                return {
                    "name": "luks_status",
                    "status": WARN,
                    "detail": "luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md",
                }
            type_lines = [line.strip() for line in lsblk_result.stdout.splitlines() if line.strip()]
            if not type_lines:
                return {
                    "name": "luks_status",
                    "status": WARN,
                    "detail": "luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md",
                }
            if "crypt" in type_lines:
                return {
                    "name": "luks_status",
                    "status": OK,
                    "detail": f"dm-crypt detected on {source}",
                }
            return {
                "name": "luks_status",
                "status": WARN,
                "detail": "data volume is not on LUKS — see docs/operator/advanced/luks-setup.md",
            }
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return {
                "name": "luks_status",
                "status": WARN,
                "detail": "luks status unverifiable from container — confirm manually per docs/operator/advanced/luks-setup.md",
            }
    except Exception as e:
        return {"name": "luks_status", "status": WARN, "detail": f"{type(e).__name__}: {e}"}


_PASSPHRASE_PLACEHOLDERS = {"changeme", "example", "<paste your passphrase here>", "", "password"}


def _check_backrest_repo() -> dict[str, Any]:
    """Check that a non-placeholder backrest repo passphrase is configured."""
    try:
        # Priority 1: env var (treat set-but-empty as unset, fall through to secret file)
        passphrase = os.environ.get("BACKREST_REPO_PASSWORD", "").strip()

        # Priority 2: docker secret file fallback
        if not passphrase:
            try:
                secret_path = pathlib.Path("/run/secrets/backrest_password")
                if secret_path.exists():
                    passphrase = secret_path.read_text().strip()
            except OSError:
                passphrase = ""

        if not passphrase:
            return {
                "name": "backrest_repo",
                "status": WARN,
                "detail": "backrest passphrase not configured — see docs/operator/advanced/restore-drill.md",
            }
        if passphrase.lower() in _PASSPHRASE_PLACEHOLDERS:
            return {
                "name": "backrest_repo",
                "status": WARN,
                "detail": "passphrase matches placeholder — regenerate per docs/operator/advanced/key-custody.md",
            }
        len_chars = len(passphrase)
        if len_chars < 16:
            return {
                "name": "backrest_repo",
                "status": WARN,
                "detail": "passphrase shorter than recommended (16+ chars)",
            }
        return {"name": "backrest_repo", "status": OK, "detail": f"configured ({len_chars} chars)"}
    except Exception as e:
        return {"name": "backrest_repo", "status": WARN, "detail": f"{type(e).__name__}: {e}"}


def _check_master_key() -> dict[str, Any]:
    """Check that HLH_MASTER_KEY is set and non-placeholder (required at v0.18.0/C6)."""
    try:
        passphrase = os.environ.get("HLH_MASTER_KEY", "").strip()

        if not passphrase:
            return {
                "name": "master_key",
                "status": WARN,
                "detail": "HLH_MASTER_KEY not set — required at v0.18.0/C6, generate per docs/operator/advanced/key-custody.md",
            }
        if passphrase.lower() in _PASSPHRASE_PLACEHOLDERS:
            return {
                "name": "master_key",
                "status": WARN,
                "detail": "HLH_MASTER_KEY matches placeholder — regenerate per docs/operator/advanced/key-custody.md",
            }
        len_chars = len(passphrase)
        if len_chars < 32:
            return {
                "name": "master_key",
                "status": WARN,
                "detail": "HLH_MASTER_KEY shorter than recommended (32+ chars)",
            }
        return {"name": "master_key", "status": OK, "detail": f"configured ({len_chars} chars)"}
    except Exception as e:
        return {"name": "master_key", "status": WARN, "detail": f"{type(e).__name__}: {e}"}


async def run_checks() -> list[dict[str, Any]]:
    """Run all 14 checks. Returns ordered list."""
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
        _check_luks_status(),
        _check_backrest_repo(),
        _check_master_key(),
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
