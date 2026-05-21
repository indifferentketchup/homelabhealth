"""Verify backend/services/sysinfo.py:

  - `recommend_tier()` covers every tier row in design §Tier definitions,
    plus floor, multi-GPU, and malformed-input edge cases.
  - `collect()` smoke test on the real host — confirms the dict shape, no
    crashes on subprocess failures, types are sensible.

Run from project root. psutil must be importable (sysinfo.py hard-imports it):

    /tmp/pw-venv/bin/python backend/scripts/verify_sysinfo.py   # if host python3 lacks psutil
    python3 backend/scripts/verify_sysinfo.py                    # if host has psutil

Exits 0 on full pass, 1 on any failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make backend/ importable when run from project root.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from services.sysinfo import ALL_TIERS, collect, recommend_tier
except ImportError as e:
    print(f"FATAL: cannot import services.sysinfo ({e}).")
    print("If psutil is missing on the host, try:")
    print("    /tmp/pw-venv/bin/pip install psutil && \\")
    print("    /tmp/pw-venv/bin/python backend/scripts/verify_sysinfo.py")
    sys.exit(2)


GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
_failed: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  {GREEN}PASS{RESET}  {label}")
    else:
        msg = f"  {RED}FAIL{RESET}  {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _failed.append(label)


def section(title: str) -> None:
    print(f"\n— {title} —")


def _t(sysinfo: dict) -> str:
    return recommend_tier(sysinfo)


# ──────────────────────────────────────────────────────────────────────────────
# recommend_tier — every tier row + floor + edge cases.
# ──────────────────────────────────────────────────────────────────────────────

section("recommend_tier — floor and malformed inputs")
check("empty dict → cpu-min", _t({}) == "cpu-min")
check("None → cpu-min (non-dict input)", recommend_tier(None) == "cpu-min")
check("[] → cpu-min (non-dict input)", recommend_tier([]) == "cpu-min")
check("missing ram + missing gpus → cpu-min", _t({"os": "linux"}) == "cpu-min")
check("gpus=str (malformed) → ignored", _t({"ram_total_gb": 32, "gpus": "oops"}) == "cpu-std")
check("gpu dict missing memory_total_mb → skipped", _t({"ram_total_gb": 32, "gpus": [{"name": "x"}]}) == "cpu-std")
check("gpu memory_total_mb=str → skipped", _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": "weird"}]}) == "cpu-std")
check("ram_total_gb=str → treated as 0", _t({"ram_total_gb": "lots"}) == "cpu-min")
check("ram_total_gb=True (bool) → treated as 0", _t({"ram_total_gb": True}) == "cpu-min")

section("recommend_tier — CPU-only tiers (rows: cpu-min, cpu-std)")
check("8 GB RAM, no GPU → cpu-min", _t({"ram_total_gb": 8, "gpus": []}) == "cpu-min")
check("15 GB RAM, no GPU → cpu-min (just under threshold)",
      _t({"ram_total_gb": 15, "gpus": []}) == "cpu-min")
check("16 GB RAM, no GPU → cpu-std (threshold)",
      _t({"ram_total_gb": 16, "gpus": []}) == "cpu-std")
check("32 GB RAM, no GPU → cpu-std", _t({"ram_total_gb": 32, "gpus": []}) == "cpu-std")

section("recommend_tier — GPU tiers (rows: gpu-8gb, gpu-16gb, gpu-24gb+)")
check("6 GB VRAM (low edge) → gpu-8gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 6144}]}) == "gpu-8gb")
check("8 GB VRAM → gpu-8gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 8192}]}) == "gpu-8gb")
check("11 GB VRAM (under 12) → gpu-8gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 11264}]}) == "gpu-8gb")
check("12 GB VRAM (threshold) → gpu-16gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 12288}]}) == "gpu-16gb")
check("16 GB VRAM → gpu-16gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 16384}]}) == "gpu-16gb")
check("23 GB VRAM (under 24) → gpu-16gb",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 23552}]}) == "gpu-16gb")
check("24 GB VRAM (threshold) → gpu-24gb+",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 24576}]}) == "gpu-24gb+")
check("48 GB VRAM → gpu-24gb+",
      _t({"ram_total_gb": 64, "gpus": [{"memory_total_mb": 49152}]}) == "gpu-24gb+")

section("recommend_tier — multi-GPU (max VRAM wins)")
check("2x 16 GB → gpu-16gb",
      _t({"ram_total_gb": 64, "gpus": [
          {"memory_total_mb": 16384}, {"memory_total_mb": 16384}
      ]}) == "gpu-16gb")
check("8 + 24 mixed → gpu-24gb+ (larger card wins)",
      _t({"ram_total_gb": 64, "gpus": [
          {"memory_total_mb": 8192}, {"memory_total_mb": 24576}
      ]}) == "gpu-24gb+")

section("recommend_tier — small GPU below threshold falls back to CPU branch")
check("4 GB VRAM + 32 GB RAM → cpu-std (GPU too small)",
      _t({"ram_total_gb": 32, "gpus": [{"memory_total_mb": 4096}]}) == "cpu-std")
check("2 GB VRAM + 8 GB RAM → cpu-min",
      _t({"ram_total_gb": 8, "gpus": [{"memory_total_mb": 2048}]}) == "cpu-min")

section("recommend_tier — Apple Silicon (row: apple-mlx)")
check("apple_silicon + 16 GB → apple-mlx (threshold)",
      _t({"apple_silicon": True, "ram_total_gb": 16, "gpus": []}) == "apple-mlx")
check("apple_silicon + 64 GB → apple-mlx",
      _t({"apple_silicon": True, "ram_total_gb": 64, "gpus": []}) == "apple-mlx")
check("apple_silicon + 8 GB → cpu-min (below threshold)",
      _t({"apple_silicon": True, "ram_total_gb": 8, "gpus": []}) == "cpu-min")
check("apple_silicon + 12 GB → cpu-min (below threshold)",
      _t({"apple_silicon": True, "ram_total_gb": 12, "gpus": []}) == "cpu-min")
check("apple_silicon=False alone doesn't trigger apple-mlx",
      _t({"apple_silicon": False, "ram_total_gb": 32, "gpus": []}) == "cpu-std")
check("apple_silicon + 24 GB VRAM eGPU → gpu-24gb+ (GPU branch wins)",
      _t({"apple_silicon": True, "ram_total_gb": 16,
          "gpus": [{"memory_total_mb": 24576}]}) == "gpu-24gb+")

section("recommend_tier — never auto-recommends 'external'")
for sysinfo in [
    {}, {"ram_total_gb": 32}, {"ram_total_gb": 64, "gpus": [{"memory_total_mb": 49152}]},
    {"apple_silicon": True, "ram_total_gb": 32},
]:
    result = _t(sysinfo)
    check(f"sysinfo={sysinfo!s:.60} → not 'external'", result != "external")
    check(f"sysinfo={sysinfo!s:.60} → in ALL_TIERS", result in ALL_TIERS)


# ──────────────────────────────────────────────────────────────────────────────
# collect() smoke on the real host — confirm shape + types, no crashes.
# ──────────────────────────────────────────────────────────────────────────────

section("collect() — smoke on real host")
data = collect()

EXPECTED_KEYS = {
    "os", "arch", "cpu_model", "cpu_cores", "ram_total_gb",
    "disk_free_gb", "gpus", "apple_silicon",
}
check("returns dict with exactly the expected keys",
      set(data.keys()) == EXPECTED_KEYS,
      f"got: {sorted(set(data.keys()))}")
check("'os' is a non-empty string", isinstance(data["os"], str) and len(data["os"]) > 0)
check("'arch' is a non-empty string", isinstance(data["arch"], str) and len(data["arch"]) > 0)
check("'cpu_model' is str or None",
      data["cpu_model"] is None or isinstance(data["cpu_model"], str))
check("'cpu_cores' is int or None",
      data["cpu_cores"] is None or isinstance(data["cpu_cores"], int))
check("'ram_total_gb' is int or None",
      data["ram_total_gb"] is None or isinstance(data["ram_total_gb"], int))
check("'disk_free_gb' is int or None",
      data["disk_free_gb"] is None or isinstance(data["disk_free_gb"], int))
check("'gpus' is a list", isinstance(data["gpus"], list))
check("'apple_silicon' is bool", isinstance(data["apple_silicon"], bool))

# Each gpu entry shape (if any).
for i, g in enumerate(data["gpus"]):
    check(f"gpus[{i}] is a dict", isinstance(g, dict))
    if isinstance(g, dict):
        check(f"gpus[{i}] has 'memory_total_mb' int",
              isinstance(g.get("memory_total_mb"), int))

# Recommendation on the real host must be in the allowed set and not 'external'.
host_tier = recommend_tier(data)
check("recommend_tier(host) in ALL_TIERS", host_tier in ALL_TIERS)
check("recommend_tier(host) != 'external'", host_tier != "external")

print()
print(f"host sysinfo: {data}")
print(f"host tier   : {host_tier}")


# ──────────────────────────────────────────────────────────────────────────────
# Result.
# ──────────────────────────────────────────────────────────────────────────────
print()
if _failed:
    print(f"{RED}{len(_failed)} failures{RESET}")
    for f in _failed:
        print(f"  - {f}")
    sys.exit(1)
print(f"{GREEN}All checks passed.{RESET}")
sys.exit(0)
