"""Tier-to-Docker-image mapping and .env writer.

Keeps version pins in one place. The tier-save endpoint calls
write_tier_env(tier) to update .env with the correct image tags
and COMPOSE_PROFILES for the selected hardware tier.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

LLAMA_CPP_VERSION = "b9660"
LLAMA_SWAP_VERSION = "v226"
BOOFINITY_VERSION = "0.1.0"


_SWAP_IMAGE_CPU    = f"ghcr.io/indifferentketchup/hlh-swap:{BOOFINITY_VERSION}-cpu"
_SWAP_IMAGE_CUDA   = f"ghcr.io/indifferentketchup/hlh-swap:{BOOFINITY_VERSION}-cuda"
# ROCm: llama-server uses ROCm/HIP GPU; boofinity uses PyTorch ROCm (--device cuda
# works because ROCm mirrors the CUDA API surface). Requires /dev/kfd + /dev/dri.
_SWAP_IMAGE_ROCM   = f"ghcr.io/indifferentketchup/hlh-swap:{BOOFINITY_VERSION}-rocm"
# Vulkan: llama-server uses Vulkan GPU; boofinity uses the cpu base image (PyTorch
# has no desktop Vulkan compute backend). llama-server child gets HLH_INFER_DEVICE=vulkan.
_SWAP_IMAGE_VULKAN = f"ghcr.io/indifferentketchup/hlh-swap:{BOOFINITY_VERSION}-vulkan"

# Pascal-safe boofinity dtype default. Ampere+ operators override to bfloat16 in
# .env to halve VRAM. The compose `--dtype ${HLH_INFER_DTYPE:-float32}` default
# makes the env optional; we still seed it so the default is documented.
INFER_DTYPE_DEFAULT = "float32"


@dataclass(frozen=True)
class TierImages:
    swap_image: str          # combined hlh_swap front-door image (cpu | cuda)
    compose_profiles: str
    models_max: int
    infer_mem: str           # tier-scaled mem_limit for hlh_swap (HLH_INFER_MEM)


TIER_IMAGE_MAP: dict[str, TierImages] = {
    "cpu-min": TierImages(
        swap_image=_SWAP_IMAGE_CPU,
        compose_profiles="bundled",
        models_max=1,
        infer_mem="2g",
    ),
    "cpu-std": TierImages(
        swap_image=_SWAP_IMAGE_CPU,
        compose_profiles="bundled",
        models_max=2,
        infer_mem="4g",
    ),
    "gpu-4gb": TierImages(
        swap_image=_SWAP_IMAGE_CUDA,
        compose_profiles="bundled-gpu",
        models_max=2,
        infer_mem="4g",
    ),
    "gpu-8gb": TierImages(
        swap_image=_SWAP_IMAGE_CUDA,
        compose_profiles="bundled-gpu",
        models_max=3,
        infer_mem="6g",
    ),
    "gpu-16gb": TierImages(
        swap_image=_SWAP_IMAGE_CUDA,
        compose_profiles="bundled-gpu",
        models_max=3,
        infer_mem="6g",
    ),
    "gpu-24gb+": TierImages(
        swap_image=_SWAP_IMAGE_CUDA,
        compose_profiles="bundled-gpu",
        models_max=4,
        infer_mem="8g",
    ),
    # AMD GPU tiers (ROCm). Compose profile bundled-amd starts hlh_swap_rocm which
    # passes /dev/kfd + /dev/dri and sets HLH_INFER_DEVICE=cuda (ROCm mirrors
    # the CUDA API surface so both llama-server and boofinity children work).
    "amd-4gb": TierImages(
        swap_image=_SWAP_IMAGE_ROCM,
        compose_profiles="bundled-amd",
        models_max=2,
        infer_mem="4g",
    ),
    "amd-8gb": TierImages(
        swap_image=_SWAP_IMAGE_ROCM,
        compose_profiles="bundled-amd",
        models_max=3,
        infer_mem="6g",
    ),
    "amd-16gb": TierImages(
        swap_image=_SWAP_IMAGE_ROCM,
        compose_profiles="bundled-amd",
        models_max=3,
        infer_mem="6g",
    ),
    "amd-24gb+": TierImages(
        swap_image=_SWAP_IMAGE_ROCM,
        compose_profiles="bundled-amd",
        models_max=4,
        infer_mem="8g",
    ),
    # Vulkan GPU tiers (cross-platform: Intel Arc, AMD without ROCm stack, etc.).
    # Compose profile bundled-vulkan starts hlh_swap_vulkan which passes /dev/dri
    # and sets HLH_INFER_DEVICE=vulkan (for the llama-server child). The boofinity
    # child runs on CPU (PyTorch has no desktop Vulkan compute backend)  -  embed and
    # rerank are slower than on ROCm/CUDA but functional.
    "vulkan-4gb": TierImages(
        swap_image=_SWAP_IMAGE_VULKAN,
        compose_profiles="bundled-vulkan",
        models_max=2,
        infer_mem="4g",
    ),
    "vulkan-8gb": TierImages(
        swap_image=_SWAP_IMAGE_VULKAN,
        compose_profiles="bundled-vulkan",
        models_max=3,
        infer_mem="6g",
    ),
    "vulkan-16gb": TierImages(
        swap_image=_SWAP_IMAGE_VULKAN,
        compose_profiles="bundled-vulkan",
        models_max=3,
        infer_mem="6g",
    ),
    "vulkan-24gb+": TierImages(
        swap_image=_SWAP_IMAGE_VULKAN,
        compose_profiles="bundled-vulkan",
        models_max=4,
        infer_mem="8g",
    ),
    "apple-mlx": TierImages(
        swap_image=_SWAP_IMAGE_CPU,
        compose_profiles="bundled",
        models_max=2,
        infer_mem="4g",
    ),
    "external": TierImages(
        swap_image=_SWAP_IMAGE_CPU,
        compose_profiles="",
        models_max=2,
        infer_mem="4g",
    ),
}


ENV_PATH = os.environ.get("HLH_ENV_PATH", "/data/.env")

_MANAGED_KEYS = (
    "HLH_SWAP_IMAGE",
    "COMPOSE_PROFILES",
    "HLH_MODELS_MAX",
    "HLH_INFER_MEM",
    "HLH_INFER_DTYPE",
)


def write_tier_env(tier: str) -> bool:
    """Write image tags and COMPOSE_PROFILES to .env based on tier.

    Preserves operator-added 'vision' profile across tier changes.
    Returns True if .env was written, False if tier not in map.
    """
    images = TIER_IMAGE_MAP.get(tier)
    if not images:
        logger.warning("write_tier_env: unknown tier %r, skipping", tier)
        return False

    if os.path.exists(ENV_PATH):
        backup_dir = os.environ.get("TMPDIR", "/tmp")
        backup = os.path.join(backup_dir, f"env.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(ENV_PATH, backup)
            logger.info("write_tier_env: backed up .env to %s", backup)
        except OSError as exc:
            logger.warning("write_tier_env: backup failed (%s), proceeding anyway", exc)

    lines: list[str] = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            lines = f.readlines()

    existing_profiles: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("COMPOSE_PROFILES="):
            existing_profiles = {
                p.strip() for p in stripped.split("=", 1)[1].split(",") if p.strip()
            }

    new_profiles = {
        p.strip() for p in images.compose_profiles.split(",") if p.strip()
    }
    if "vision" in existing_profiles:
        new_profiles.add("vision")

    managed = {
        "HLH_SWAP_IMAGE": images.swap_image,
        "COMPOSE_PROFILES": ",".join(sorted(new_profiles)) if new_profiles else "",
        "HLH_MODELS_MAX": str(images.models_max),
        "HLH_INFER_MEM": images.infer_mem,
        "HLH_INFER_DTYPE": INFER_DTYPE_DEFAULT,
    }

    found: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in managed:
            new_lines.append(f"{key}={managed[key]}\n")
            found.add(key)
        else:
            new_lines.append(line)

    for key, val in managed.items():
        if key not in found:
            new_lines.append(f"{key}={val}\n")

    try:
        with open(ENV_PATH, "w") as f:
            f.writelines(new_lines)
    except OSError as exc:
        # Expected in bootstrap deployments: hlh_api runs read_only and .env is
        # not mounted (it's a compose-only file). The tier choice still lands in
        # the DB; only the compose .env sync is skipped. Never 500 setup for this.
        logger.warning(
            "write_tier_env: could not write %s (%s); skipping .env sync "
            "(normal for bootstrap/read-only deployments)",
            ENV_PATH, exc,
        )
        return False

    logger.info(
        "write_tier_env: tier=%s → HLH_SWAP_IMAGE=%s, COMPOSE_PROFILES=%s, "
        "HLH_INFER_MEM=%s, HLH_INFER_DTYPE=%s",
        tier, managed["HLH_SWAP_IMAGE"], managed["COMPOSE_PROFILES"],
        managed["HLH_INFER_MEM"], managed["HLH_INFER_DTYPE"],
    )
    return True
