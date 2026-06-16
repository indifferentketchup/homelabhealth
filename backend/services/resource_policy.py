"""Tier-aware inference resource policy (pure data, no I/O).

llama-swap does the mechanical load/unload of the llama-server and boofinity
child processes (config groups + TTL). This module encodes the ADR-0002 tier
*policy* that llama-swap does not know: which child roles may be VRAM-resident
together per tier, and whether Gemma offloads to CPU (slow) or goes unavailable
with a warning when the GPU is under pressure.

Pure data + functions: no database, no network, no event loop. Consumers:
  - pipeline_status.infer_backend_state reads gemma_under_pressure and
    coresident_roles to label the swapping phase.
  - doctor.py reads swap_group_exclusive to check the shipped static swap config
    matches the tier's expectation.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.image_config import TIER_IMAGE_MAP

# Gemma degradation modes under VRAM pressure.
OFFLOAD_CPU = "offload_cpu"
UNAVAILABLE = "unavailable"

# Child-process roles arbitrated by llama-swap.
_CHAT_ROLES = frozenset({"medgemma", "qwen-chat", "gemma-tasks"})
_EMBED_ROLES = frozenset({"qwen3-embed", "qwen3-reranker", "qwen3-vl-embed", "qwen3-vl-rerank"})
_ALL_ROLES = _CHAT_ROLES | _EMBED_ROLES


@dataclass(frozen=True)
class TierPolicy:
    coresident_roles: frozenset[str]   # roles allowed VRAM-resident together
    gemma_under_pressure: str          # OFFLOAD_CPU | UNAVAILABLE
    swap_group_exclusive: bool         # one exclusive group vs split groups


# On constrained tiers the chat child and the boofinity child cannot share VRAM,
# so coresident_roles is empty (one child at a time, exclusive swap group). On
# gpu-24gb+ both children fit, so every role may be co-resident and the group is
# non-exclusive in principle (v1 still ships the static exclusive config; doctor
# WARNs, not ERRORs, on the gap - see design.md "Deferred (YAGNI)").
_CONSTRAINED = TierPolicy(
    coresident_roles=frozenset(),
    gemma_under_pressure=OFFLOAD_CPU,
    swap_group_exclusive=True,
)

TIER_POLICY: dict[str, TierPolicy] = {
    "cpu-min": _CONSTRAINED,
    "cpu-std": _CONSTRAINED,
    "apple-mlx": _CONSTRAINED,
    "external": _CONSTRAINED,
    # Tight VRAM: one exclusive group. gpu-4gb cannot offload Gemma to CPU on a
    # GPU-only host without thrashing, so Gemma goes unavailable with a warning.
    "gpu-4gb": TierPolicy(
        coresident_roles=frozenset(),
        gemma_under_pressure=UNAVAILABLE,
        swap_group_exclusive=True,
    ),
    "gpu-8gb": TierPolicy(
        coresident_roles=frozenset(),
        gemma_under_pressure=OFFLOAD_CPU,
        swap_group_exclusive=True,
    ),
    "gpu-16gb": TierPolicy(
        coresident_roles=frozenset(),
        gemma_under_pressure=OFFLOAD_CPU,
        swap_group_exclusive=True,
    ),
    # Roomy: the llama.cpp child and the boofinity child may coexist; Gemma stays
    # resident, no degradation needed.
    "gpu-24gb+": TierPolicy(
        coresident_roles=_ALL_ROLES,
        gemma_under_pressure=OFFLOAD_CPU,
        swap_group_exclusive=False,
    ),
}


def policy_for(tier: str) -> TierPolicy:
    """Return the policy for a tier, falling back to the constrained default."""
    return TIER_POLICY.get(tier, _CONSTRAINED)


def gemma_degradation(tier: str) -> str:
    """OFFLOAD_CPU or UNAVAILABLE for Gemma under VRAM pressure on this tier."""
    return policy_for(tier).gemma_under_pressure


def coresident(tier: str) -> frozenset[str]:
    """Roles (child processes) that may be VRAM-resident together on this tier."""
    return policy_for(tier).coresident_roles


# Every tier with an image mapping must have a policy, or coresident/degradation
# would silently fall back. Asserted at import so a new tier can't drift.
_missing = set(TIER_IMAGE_MAP) - set(TIER_POLICY)
if _missing:  # pragma: no cover - guards against a new tier with no policy
    raise RuntimeError(f"resource_policy: tiers without a policy: {sorted(_missing)}")
