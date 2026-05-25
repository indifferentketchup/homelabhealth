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
            "detail": "PROVIDER_KEY_ENCRYPTION_KEY not set — keys should auto-generate on launch; check /data/keys/.hlh_keys",
        }
    try:
        from services.crypto import _key
        k = _key()
        if k is None or len(k) != 32:
            return {"name": "provider_key", "status": ERROR, "detail": "key resolution returned None/wrong length"}
        return {"name": "provider_key", "status": OK, "detail": "32 bytes, valid base64"}
    except Exception as e:
        return {"name": "provider_key", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}




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
                "detail": "HLH_MASTER_KEY not set — keys should auto-generate on launch; check /data/keys/.hlh_keys",
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


async def _check_audit_log_chain() -> dict[str, Any]:
    """Verify the audit_log rows form a valid hash chain.

    Reads ALL rows ordered by id ASC and the chain anchor from
    audit_log_chain_head.first_anchor_hash. Pre-prune, the anchor is 32 zero
    bytes (genesis). Post-prune, audit_retention atomically advances it to
    the prev_hash of the new oldest row, so verify_chain still validates the
    remaining rows. A "last 100 rows" window would skip the anchor check and
    silently pass a corrupted chain; if performance becomes an issue at scale
    we can add a windowed mode later. For v0.11.0 read all.

    Returns ERROR on break — chain integrity is a real invariant, not
    operator-prudence (no C1-style demotion to WARN here).
    """
    try:
        from services.audit import verify_chain
        pool = await get_pool()
        async with pool.acquire() as conn:
            anchor_row = await conn.fetchrow(
                "SELECT first_anchor_hash FROM audit_log_chain_head WHERE id = 1"
            )
            rows = await conn.fetch(
                "SELECT * FROM audit_log ORDER BY id ASC"
            )
        if not rows:
            return {"name": "audit_log_chain", "status": OK, "detail": "empty (no rows yet)"}
        anchor = bytes(anchor_row["first_anchor_hash"]) if anchor_row else b"\x00" * 32
        ok, bad_id = verify_chain(rows, expected_first_prev=anchor)
        if ok:
            note = f"{len(rows)} rows verified"
            if anchor != b"\x00" * 32:
                note += " (post-prune anchor)"
            return {"name": "audit_log_chain", "status": OK, "detail": note}
        return {"name": "audit_log_chain", "status": ERROR, "detail": f"chain break detected at row id={bad_id}"}
    except Exception as e:
        return {"name": "audit_log_chain", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


def _check_guard_scanners() -> dict[str, Any]:
    try:
        from services.guard import scanner_summary
        summary = scanner_summary()
        total = sum(summary.values())
        return {"name": "guard_scanners", "status": OK, "detail": f"{total} patterns across {len(summary)} categories"}
    except Exception as e:
        return {"name": "guard_scanners", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


def _check_deid_pipeline() -> dict[str, Any]:
    try:
        from services.deid import pipeline_summary
        s = pipeline_summary()
        if not s["enabled"]:
            return {"name": "deid_pipeline", "status": WARN, "detail": "disabled (HLH_DEID_ENABLED=false)"}
        return {"name": "deid_pipeline", "status": OK, "detail": f"enabled, policy={s['policy']}, {s['pattern_count']} patterns"}
    except Exception as e:
        return {"name": "deid_pipeline", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


def _check_column_encryption() -> dict[str, Any]:
    try:
        from services.crypto import column_encryption_summary
        s = column_encryption_summary()
        if not s.get("enabled"):
            detail = s.get("status") or s.get("error", "unknown")
            return {"name": "column_encryption", "status": WARN, "detail": detail}
        return {"name": "column_encryption", "status": OK, "detail": s["status"]}
    except Exception as e:
        return {"name": "column_encryption", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def _check_vision_available() -> dict[str, Any]:
    """Check that the mmproj file is present for the current tier."""
    try:
        from services.model_puller import MODEL_REGISTRY, MODELS_BASE_DIR

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
        if not row or not row["tier"]:
            return {"name": "vision_available", "status": WARN, "detail": "tier not set in system_profile"}

        tier = row["tier"]

        # cpu-min uses an MTP model that is mmproj-incompatible
        if tier == "cpu-min":
            return {
                "name": "vision_available",
                "status": WARN,
                "detail": "Vision not available on cpu-min tier (upgrade to cpu-std+ for image/PDF understanding)",
            }

        spec = MODEL_REGISTRY.get("vision", {}).get(tier)
        if spec is None:
            return {
                "name": "vision_available",
                "status": WARN,
                "detail": f"no vision model spec for tier {tier}",
            }

        mmproj_path = MODELS_BASE_DIR / "vision" / tier / spec.filename
        active_symlink = MODELS_BASE_DIR / "vision" / "active-mmproj.gguf"

        if mmproj_path.exists() or active_symlink.exists():
            return {
                "name": "vision_available",
                "status": OK,
                "detail": "Vision available (MedGemma mmproj loaded)",
            }

        return {
            "name": "vision_available",
            "status": ERROR,
            "detail": f"mmproj file not found at {mmproj_path}; pull the vision model from Settings → System",
        }
    except Exception as e:
        return {"name": "vision_available", "status": ERROR, "detail": f"{type(e).__name__}: {e}"}


async def run_checks() -> list[dict[str, Any]]:
    """Run all 18 checks. Returns ordered list."""
    return [
        await _check_db_pool(),
        await _check_schema_applied(),
        await _check_setup_complete(),
        await _check_sidecar("hlh_chat", "http://hlh_chat:9610/health"),
        await _check_sidecar("hlh_infer", "http://hlh_infer:9611/health"),
        await _check_sidecar("hlh_search", "http://hlh_search:8080/healthz"),
        await _check_vision_available(),
        await _check_safeguard_version(),
        _check_disk_free("disk_free_data", "/data"),
        _check_disk_free("disk_free_models", "/models"),
        _check_provider_key(),
        {**_check_luks_status(), "advanced": True},
        {**_check_backrest_repo(), "advanced": True},
        {**_check_master_key(), "advanced": True},
        await _check_audit_log_chain(),
        _check_guard_scanners(),
        _check_deid_pipeline(),
        _check_column_encryption(),
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
    # Ensure encryption keys are available before any check that reads them.
    # This mirrors what main.py lifespan does on server start.
    from services.key_manager import ensure_keys
    ensure_keys()

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
