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

LLAMA_CPP_VERSION = "b9282"
INFINITY_VERSION = "0.0.77"


@dataclass(frozen=True)
class TierImages:
    chat_image: str
    infer_image: str
    compose_profiles: str
    models_max: int


TIER_IMAGE_MAP: dict[str, TierImages] = {
    "cpu-min": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}-cpu",
        compose_profiles="bundled",
        models_max=1,
    ),
    "cpu-std": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}-cpu",
        compose_profiles="bundled",
        models_max=2,
    ),
    "gpu-4gb": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-cuda-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}",
        compose_profiles="bundled-gpu",
        models_max=2,
    ),
    "gpu-8gb": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-cuda-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}",
        compose_profiles="bundled-gpu",
        models_max=3,
    ),
    "gpu-16gb": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-cuda-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}",
        compose_profiles="bundled-gpu",
        models_max=3,
    ),
    "gpu-24gb+": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-cuda-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}",
        compose_profiles="bundled-gpu,vision",
        models_max=4,
    ),
    "apple-mlx": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}-cpu",
        compose_profiles="bundled",
        models_max=2,
    ),
    "external": TierImages(
        chat_image=f"ghcr.io/ggml-org/llama.cpp:server-{LLAMA_CPP_VERSION}",
        infer_image=f"michaelf34/infinity:{INFINITY_VERSION}-cpu",
        compose_profiles="",
        models_max=2,
    ),
}


ENV_PATH = os.environ.get("HLH_ENV_PATH", "/data/.env")

_MANAGED_KEYS = ("HLH_CHAT_IMAGE", "HLH_INFER_IMAGE", "COMPOSE_PROFILES", "HLH_MODELS_MAX")


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
        "HLH_CHAT_IMAGE": images.chat_image,
        "HLH_INFER_IMAGE": images.infer_image,
        "COMPOSE_PROFILES": ",".join(sorted(new_profiles)) if new_profiles else "",
        "HLH_MODELS_MAX": str(images.models_max),
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
        "write_tier_env: tier=%s → HLH_CHAT_IMAGE=%s, HLH_INFER_IMAGE=%s, COMPOSE_PROFILES=%s",
        tier, managed["HLH_CHAT_IMAGE"], managed["HLH_INFER_IMAGE"], managed["COMPOSE_PROFILES"],
    )
    return True
