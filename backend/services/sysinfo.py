"""Hardware detection for tier recommendation (Phase 0).

Design: docs/hlh_phase0_design.md §Sysinfo collection + §Tier recommendation.

All detection is best-effort. Subprocess calls have a 2s timeout, log on
failure, and return null for that field. Detection failure must never raise  - 
the operator falls back to the manual picker if detect can't reach the
hardware. `recommend_tier()` is a pure function over the dict shape produced
by `collect()`.
"""

from __future__ import annotations

import glob
import logging
import os
import platform
import shutil
import subprocess
from typing import Any

import psutil

logger = logging.getLogger(__name__)


ALL_TIERS: frozenset[str] = frozenset(
    {"cpu-min", "cpu-std", "gpu-4gb", "gpu-8gb", "gpu-16gb", "gpu-24gb+", "apple-mlx", "external"}
)

# Per-tier llama.cpp --ctx-size defaults (tokens). HLH_CHAT_CTX env overrides when set.
TIER_CHAT_CTX: dict[str, int] = {
    "cpu-min": 8192,
    "cpu-std": 8192,
    "gpu-4gb": 32768,
    "gpu-8gb": 32768,
    "gpu-16gb": 32768,
    "gpu-24gb+": 65536,
}


def chat_ctx_for_tier(tier: str | None) -> int:
    """Context window (tokens) for a tier. Env HLH_CHAT_CTX wins when set."""
    import os

    raw = os.environ.get("HLH_CHAT_CTX")
    if raw is not None and str(raw).strip():
        return int(raw)
    if tier and tier in TIER_CHAT_CTX:
        return TIER_CHAT_CTX[tier]
    return 32768

_CPU_STD_MIN_RAM_GB = 16
_APPLE_MIN_UNIFIED_RAM_GB = 16
_GPU_4_MIN_VRAM_GB = 4
_GPU_8_MIN_VRAM_GB = 6
_GPU_16_MIN_VRAM_GB = 12
_GPU_24_MIN_VRAM_GB = 24


def _run(cmd: list[str], timeout: float = 2.0) -> str | None:
    """Run a subprocess, return stdout (stripped) or None on any failure.

    Catches: FileNotFoundError (binary missing), TimeoutExpired, OSError,
    non-zero exit. Detection failure never raises.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.info("sysinfo: %s failed: %s", cmd[0], e)
        return None
    if r.returncode != 0:
        logger.info(
            "sysinfo: %s exited %d (stderr: %s)",
            cmd[0],
            r.returncode,
            (r.stderr or "").strip()[:200],
        )
        return None
    return r.stdout.strip()


def _detect_cpu_model() -> str | None:
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError as e:
            logger.info("sysinfo: /proc/cpuinfo: %s", e)
        return None
    if system == "Darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    return None  # Windows/other: not supported in Phase 0


def _nvidia_driver_present() -> bool:
    """Cheap pre-check before invoking nvidia-smi (design §Risks)."""
    if os.path.exists("/proc/driver/nvidia/version"):
        return True
    try:
        if glob.glob("/dev/nvidia[0-9]*"):
            return True
    except OSError:
        pass
    return False


def _detect_gpus() -> list[dict[str, Any]]:
    """Return list of GPU dicts, empty if none. Best-effort.

    Order per design §Risks: check /proc/driver/nvidia/version and /dev/nvidia*
    first; fall back to nvidia-smi only if available. If neither yields a GPU,
    return [].
    """
    # nvidia-smi can succeed even when /proc/driver isn't readable from a
    # container (e.g. host nvidia-smi shimmed in), so we try nvidia-smi
    # regardless of the pre-check  -  the pre-check just helps logging.
    if not _nvidia_driver_present():
        logger.info("sysinfo: no /proc/driver/nvidia/version or /dev/nvidia*; trying nvidia-smi anyway")
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    gpus: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0] or None
        try:
            memory_total_mb = int(parts[1])
        except ValueError:
            continue
        gpus.append({"name": name, "memory_total_mb": memory_total_mb})
    return gpus


def _detect_disk_free_gb(path: str = "/") -> int | None:
    """Disk free at `path`, rounded to GB. Used for the model-cache volume hint."""
    try:
        return round(shutil.disk_usage(path).free / (1024 ** 3))
    except OSError as e:
        logger.info("sysinfo: disk_usage(%r): %s", path, e)
        return None


def _max_vram_gb(gpus: list[dict[str, Any]]) -> int:
    """Max VRAM across GPUs in GB (floor). 0 if no usable entry."""
    mems: list[int] = []
    for g in gpus:
        if not isinstance(g, dict):
            continue
        m = g.get("memory_total_mb")
        if isinstance(m, bool):
            # bool is a subclass of int; reject explicitly.
            continue
        if isinstance(m, (int, float)):
            mems.append(int(m))
    if not mems:
        return 0
    return max(mems) // 1024


def collect() -> dict[str, Any]:
    """Best-effort hardware inventory. Never raises."""
    system_name = platform.system().lower()       # 'linux' / 'darwin' / 'windows'
    arch = platform.machine().lower()             # 'x86_64' / 'arm64' / 'aarch64' / ...
    apple_silicon = (arch == "arm64") and (system_name == "darwin")

    ram_total_gb: int | None
    try:
        ram_total_gb = round(psutil.virtual_memory().total / (1024 ** 3))
    except Exception as e:
        logger.info("sysinfo: psutil.virtual_memory: %s", e)
        ram_total_gb = None

    cpu_cores: int | None
    try:
        cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    except Exception as e:
        logger.info("sysinfo: psutil.cpu_count: %s", e)
        cpu_cores = None

    return {
        "os": system_name,
        "arch": arch,
        "cpu_model": _detect_cpu_model(),
        "cpu_cores": cpu_cores,
        "ram_total_gb": ram_total_gb,
        "disk_free_gb": _detect_disk_free_gb("/"),
        "gpus": _detect_gpus(),
        "apple_silicon": apple_silicon,
    }


def recommend_tier(sysinfo: Any) -> str:
    """Pure-function tier recommendation per design §Tier recommendation.

    Picks the most capable tier the hardware can sustain. Floor is `cpu-min`.
    `external` is never auto-recommended  -  it's only ever a manual choice.

    Bands (max VRAM across GPUs; falls through to CPU/Apple branches when no
    usable GPU):
        >= 24 GB VRAM → gpu-24gb+
        >= 12 GB VRAM → gpu-16gb
        >=  6 GB VRAM → gpu-8gb
        >=  4 GB VRAM → gpu-4gb
        Apple Silicon + >= 16 GB unified RAM → apple-mlx
        >= 16 GB RAM (no usable GPU) → cpu-std
        otherwise → cpu-min
    """
    if not isinstance(sysinfo, dict):
        return "cpu-min"

    raw_gpus = sysinfo.get("gpus")
    gpus = raw_gpus if isinstance(raw_gpus, list) else []
    max_vram_gb = _max_vram_gb(gpus)

    if max_vram_gb >= _GPU_24_MIN_VRAM_GB:
        return "gpu-24gb+"
    if max_vram_gb >= _GPU_16_MIN_VRAM_GB:
        return "gpu-16gb"
    if max_vram_gb >= _GPU_8_MIN_VRAM_GB:
        return "gpu-8gb"
    if max_vram_gb >= _GPU_4_MIN_VRAM_GB:
        return "gpu-4gb"

    ram_raw = sysinfo.get("ram_total_gb")
    ram_total_gb = ram_raw if isinstance(ram_raw, (int, float)) and not isinstance(ram_raw, bool) else 0

    if bool(sysinfo.get("apple_silicon")) and ram_total_gb >= _APPLE_MIN_UNIFIED_RAM_GB:
        return "apple-mlx"
    if ram_total_gb >= _CPU_STD_MIN_RAM_GB:
        return "cpu-std"
    return "cpu-min"
