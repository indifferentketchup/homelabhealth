"""Startup observability: access-log noise filter + a boot summary banner.

Two readability wins motivated by real debugging pain:

1. The UI polls a handful of endpoints every ~2s, so uvicorn's access log
   buries real errors under a flood of `GET /api/models 200 OK`. The filter
   drops *successful* polls of those endpoints (errors always pass through),
   and quiets httpx's per-request INFO chatter (the vision/status poll).

2. `log_startup_banner` emits one greppable block at boot — version, tier,
   chat model, on-disk GGUFs, pull-state counts — so "is this healthy?" is a
   single glance instead of a log archaeology dig.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("hlh.startup")

# Successful GETs of these exact paths are dropped from the access log. They're
# the high-frequency UI polls; anything non-2xx/3xx still gets logged.
_NOISY_PATHS = frozenset({
    "/health",
    "/api/models",
    "/api/inference/state",
    "/api/inference/settings",
    "/api/auth/needs-setup",
    "/api/auth/me",
    "/api/profile/me",
    "/api/settings/layout",
    "/api/system/profile",
    "/api/workspaces",
})


class _AccessLogNoiseFilter(logging.Filter):
    """Drop successful access-log lines for high-frequency poll endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        try:
            path = str(args[2]).split("?", 1)[0].rstrip("/") or "/"
            status = int(args[4])
        except (ValueError, TypeError, IndexError):
            return True
        if status >= 400:
            return True  # never hide errors
        return path not in _NOISY_PATHS


def install_access_log_filter() -> None:
    """Attach the noise filter and quiet httpx's per-request INFO logs."""
    logging.getLogger("uvicorn.access").addFilter(_AccessLogNoiseFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _gguf_summary(models_dir: Path) -> tuple[int, float]:
    """(count, total GB) of flat *.gguf files in /models."""
    try:
        files = [p for p in models_dir.glob("*.gguf") if p.is_file()]
    except OSError:
        return 0, 0.0
    total = 0
    for p in files:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return len(files), total / 1e9


async def log_startup_banner(conn, *, seeded: int, orphaned: int) -> None:
    """Emit a one-block summary of API + model state at boot. Best-effort."""
    try:
        from services.bundled_providers import (
            ACTIVE_MEDGEMMA,
            ACTIVE_QWEN,
            TIER_CHAT_MODELS,
        )

        version = os.environ.get("HLH_VERSION", "unknown")
        row = await conn.fetchrow(
            "SELECT tier, setup_complete, sysinfo_json FROM system_profile WHERE id = 1"
        )
        tier = (row["tier"] if row and row["tier"] else "unset")
        setup = bool(row and row["setup_complete"])
        chat_alias = TIER_CHAT_MODELS.get(tier, "—")

        status_rows = await conn.fetch(
            "SELECT status, count(*) AS n FROM bundled_models GROUP BY status ORDER BY status"
        )
        states = ", ".join(f"{r['n']} {r['status']}" for r in status_rows) or "none"

        models_dir = Path(os.environ.get("HLH_MODELS_DIR", "/models"))
        n_gguf, gb = _gguf_summary(models_dir)

        active = "not linked"
        try:
            link = ACTIVE_MEDGEMMA if chat_alias != "qwen-chat" else ACTIVE_QWEN
            if link.is_symlink():
                active = os.readlink(link)
            elif link.exists():
                active = link.name
        except OSError:
            pass

        gpus = "—"
        try:
            sysinfo = row["sysinfo_json"] if row else None
            if isinstance(sysinfo, dict):
                gpu_list = sysinfo.get("gpus") or []
                if gpu_list:
                    gpus = ", ".join(str(g.get("name", "GPU")) for g in gpu_list)
                else:
                    gpus = "none detected"
        except (KeyError, TypeError):
            pass

        bar = "─" * 64
        for line in (
            bar,
            f"  homelabhealth API ready  ·  version={version}",
            f"  tier={tier}  setup_complete={setup}  chat={chat_alias}  gpu={gpus}",
            f"  bundled_models: {states}   (seeded {seeded}, reset {orphaned} orphaned)",
            f"  /models: {n_gguf} gguf, {gb:.1f} GB   active chat → {active}",
            bar,
        ):
            logger.info(line)
    except Exception:  # noqa: BLE001 — a banner must never break startup
        logger.warning("startup banner failed to render", exc_info=True)
