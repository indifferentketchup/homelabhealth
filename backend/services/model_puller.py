"""Bundled-AI model puller — Phase 1.

Streams model weights from HuggingFace to a shared `/models` volume,
tracks progress in `bundled_models`, handles gated-repo 401s with a clear
license-acceptance error.

Design: hlh_phase1_design.md §Backend services + §Pull mechanics.

Public surface:
    MODEL_REGISTRY    : dict[role, dict[tier, ModelSpec | None]]
    seed_registry(c)  : idempotent upsert of MODEL_REGISTRY into bundled_models
    pull_model(p, id) : stream-download one row by uuid; updates status + bytes
    pull_for_tier(p)  : returns {role: uuid} for the rows queueable at a tier
    request_cancel()  : flip the per-id cancel flag
    is_pulling()      : whether a pull is currently active
    MODELS_BASE_DIR   : on-disk root (overridable via HLH_MODELS_DIR env)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MODELS_BASE_DIR = Path(os.environ.get("HLH_MODELS_DIR", "/models"))
# HuggingFace hub cache root the boofinity child reads (HF_HOME=/cache). Snapshot
# specs land under INFER_CACHE_DIR/hub/models--<org>--<repo>/ — see _snapshot_pull.
INFER_CACHE_DIR = Path(os.environ.get("HLH_INFER_CACHE_DIR", "/cache"))

ALL_ROLES = ("chat", "tasks", "embed", "rerank", "embed-vl", "rerank-vl", "vision", "stt", "ocr")
ALL_TIERS = (
    "cpu-min", "cpu-std",
    "gpu-4gb", "gpu-8gb", "gpu-16gb", "gpu-24gb+",      # NVIDIA CUDA
    "amd-4gb", "amd-8gb", "amd-16gb", "amd-24gb+",      # AMD ROCm
    "vulkan-4gb", "vulkan-8gb", "vulkan-16gb", "vulkan-24gb+",  # Vulkan (cross-platform)
    "apple-mlx", "external",
)

PULL_CHUNK_BYTES = 5 * 1024 * 1024
PULL_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=10.0)


@dataclass(frozen=True)
class ModelSpec:
    """A model's pull spec: repo + filename + integrity + license metadata.

    `expected_bytes` and `sha256` are optional. `license` and `license_url`
    are surfaced to the operator for gated repos. `revision` pins the
    HuggingFace git ref (branch, tag, or commit SHA); defaults to 'main'.
    """
    repo: str
    filename: str = ""
    kind: str = "file"            # "file" | "snapshot"
    quant: str | None = None
    expected_bytes: int | None = None
    sha256: str | None = None
    license: str | None = None
    license_url: str | None = None
    revision: str | None = None

    @property
    def model_id(self) -> str:
        """Identifier embedded in the bundled_models UNIQUE constraint."""
        if self.kind == "snapshot":
            return f"{self.repo}@snapshot"
        return f"{self.repo}@{self.filename}"


_GEMMA_LICENSE = "gemma"

# Router-served roles (embed / rerank / tasks) are tier-independent: one GGUF
# serves every bundled router tier, landing at a flat /models/<file> path that
# models.ini already references (see _FLAT_DEST_ROLES). External/BYO and
# apple-mlx tiers don't use the bundled router, so they stay None.
_ROUTER_TIERS = (
    "cpu-min", "cpu-std",
    "gpu-4gb", "gpu-8gb", "gpu-16gb", "gpu-24gb+",
    "amd-4gb", "amd-8gb", "amd-16gb", "amd-24gb+",
    "vulkan-4gb", "vulkan-8gb", "vulkan-16gb", "vulkan-24gb+",
)


def _router_role(spec: ModelSpec) -> dict[str, ModelSpec | None]:
    return {tier: (spec if tier in _ROUTER_TIERS else None) for tier in ALL_TIERS}


# Vision projector (mmproj). MedGemma's chat model IS multimodal, so the SAME
# instance serves chat + image-reading once its mmproj is loaded (models.ini's
# [medgemma] preset loads it via the active-mmproj symlink) — no separate vision
# model, no second VRAM load. The projector must MATCH the tier's chat model:
# 4b mmproj for the 4b chat tiers, 27b mmproj for the 27b tiers.
_VISION_MMPROJ_4B = ModelSpec(
    repo="unsloth/medgemma-1.5-4b-it-GGUF",
    filename="mmproj-F16.gguf",
    quant="f16",
    license=_GEMMA_LICENSE,
    license_url="https://huggingface.co/google/medgemma-4b-it",
    revision="main",
)
_VISION_MMPROJ_27B = ModelSpec(
    repo="unsloth/medgemma-27b-it-GGUF",
    filename="mmproj-F16.gguf",
    quant="f16",
    license=_GEMMA_LICENSE,
    license_url="https://huggingface.co/google/medgemma-27b-it",
    revision="main",
)


# Embedder (Qwen3-Embedding-0.6B, Apache) + reranker (Qwen3-Reranker-0.6B,
# Apache) are now full HF safetensors repos served by the boofinity child, not
# flat llama.cpp GGUFs (folder C, 2026-06-16). boofinity loads them from the HF
# hub cache under HF_HOME=/cache, so these are kind="snapshot" specs pulled via
# huggingface_hub.snapshot_download into the hlh_infer_cache volume rather than
# streamed to a flat /models/<file>. tasks model is gemma-3-270m, still a GGUF on
# the llama.cpp child. The GGUF->safetensors switch produces NON-comparable
# vectors: POST /api/sources/reingest-all is auto-fired on cutover (embed_cutover).
_EMBED_SPEC = ModelSpec(
    repo="Qwen/Qwen3-Embedding-0.6B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
    revision="main",
)
_RERANK_SPEC = ModelSpec(
    repo="Qwen/Qwen3-Reranker-0.6B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-Reranker-0.6B",
    revision="main",
)
_TASKS_SPEC = ModelSpec(
    repo="unsloth/gemma-3-270m-it-GGUF",
    filename="gemma-3-270m-it-UD-Q8_K_XL.gguf",
    quant="UD-Q8_K_XL",
    license=_GEMMA_LICENSE,
    license_url="https://huggingface.co/unsloth/gemma-3-270m-it-GGUF",
    revision="main",
)
# Dual-space VL embed/rerank (folder D, 2026-06-16). Native Qwen3-VL image
# embedder + reranker, both ~2B torch models served by the boofinity child behind
# hlh_swap (aliases qwen3-vl-embed / qwen3-vl-rerank). GPU-favoured, so gated to
# gpu-24gb+ ONLY — every other tier is None and never pulls them. kind="snapshot"
# (full HF directory: config + weights + tokenizer) pulled into the HF hub cache,
# NOT a flat /models/<file> GGUF, so these are NOT in _FLAT_DEST_ROLES.
_EMBED_VL_SPEC = ModelSpec(
    repo="Qwen/Qwen3-VL-Embedding-2B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B",
    revision="main",
)
_RERANK_VL_SPEC = ModelSpec(
    repo="Qwen/Qwen3-VL-Reranker-2B",
    kind="snapshot",
    license="apache-2.0",
    license_url="https://huggingface.co/Qwen/Qwen3-VL-Reranker-2B",
    revision="main",
)


def _gpu24_only_role(spec: ModelSpec) -> dict[str, ModelSpec | None]:
    """Tier map with the spec on all 24gb+ GPU tiers (CUDA + ROCm + Vulkan), None elsewhere.

    Vulkan 24gb+ is included: even though the boofinity child runs on CPU for
    Vulkan hosts (no PyTorch desktop Vulkan backend), the weights still need to
    be present in the HF cache for the embed/rerank aliases to start up.
    """
    _gpu24_tiers = {"gpu-24gb+", "amd-24gb+", "vulkan-24gb+"}
    return {tier: (spec if tier in _gpu24_tiers else None) for tier in ALL_TIERS}

# Phase 1 supplies chat specs only; all other roles get None placeholders so
# the schema is exercised but no pulls happen. Subsequent phases extend each
# role's tier map.
MODEL_REGISTRY: dict[str, dict[str, ModelSpec | None]] = {
    "chat": {
        # Design specified Q4_K_M but Qwen/Qwen3-1.7B-GGUF only ships Q8_0
        # (~1.8 GB; still well within the cpu-min 2 GB RAM target).
        # Note for Phase 1.H report: design-vs-reality deviation, picked the
        # available quant; operator can override later.
        "cpu-min": ModelSpec(
            repo="unsloth/Qwen3.5-0.8B-MTP-GGUF",
            filename="Qwen3.5-0.8B-Q8_0.gguf",
            quant="Q8_0",
            license="apache-2.0",
            license_url="https://huggingface.co/unsloth/Qwen3.5-0.8B-MTP-GGUF",
            revision="main",
        ),
        # Google's medgemma repos ship safetensors only; unsloth re-uploads GGUF
        # versions. 4B uses the v1.5 release; 27B stays on original (no v1.5
        # mirror exists yet). license_url points at Google's canonical repo
        # where the operator must click "Agree and access".
        "cpu-std": ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "gpu-4gb": ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "gpu-8gb": ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        # gpu-16gb runs the 4b (Q8_0) — the 27b is reserved for gpu-24gb+ only,
        # so a 16 GB card keeps the chat model + its mmproj comfortably resident.
        "gpu-16gb": ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "gpu-24gb+": ModelSpec(
            repo="unsloth/medgemma-27b-it-GGUF",
            filename="medgemma-27b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-27b-it",
            revision="main",
        ),
        # AMD ROCm GPU tiers — same model bins as the equivalent CUDA tiers.
        # ROCm runs the GGUF via llama-server's HIP backend; same quantisation.
        "amd-4gb":   ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "amd-8gb":   ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "amd-16gb":  ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "amd-24gb+": ModelSpec(
            repo="unsloth/medgemma-27b-it-GGUF",
            filename="medgemma-27b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-27b-it",
            revision="main",
        ),
        # Vulkan GPU tiers — llama-server uses the Vulkan backend; same GGUFs.
        "vulkan-4gb":   ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "vulkan-8gb":   ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "vulkan-16gb":  ModelSpec(
            repo="unsloth/medgemma-1.5-4b-it-GGUF",
            filename="medgemma-1.5-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
            revision="main",
        ),
        "vulkan-24gb+": ModelSpec(
            repo="unsloth/medgemma-27b-it-GGUF",
            filename="medgemma-27b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-27b-it",
            revision="main",
        ),
        "apple-mlx": None,  # Phase 6
        "external": None,
    },
    "tasks":     _router_role(_TASKS_SPEC),   # gemma-3-270m — title generation
    "embed":     _router_role(_EMBED_SPEC),   # Qwen3-Embedding-0.6B — RAG embeddings
    "rerank":    _router_role(_RERANK_SPEC),  # Qwen3-Reranker-0.6B — RAG rerank
    # Dual-space VL (folder D): gpu-24gb+ only, every other tier None.
    "embed-vl":  _gpu24_only_role(_EMBED_VL_SPEC),    # Qwen3-VL-Embedding-2B — image embeddings
    "rerank-vl": _gpu24_only_role(_RERANK_VL_SPEC),   # Qwen3-VL-Reranker-2B — dual-space rerank
    # Vision projector for the tier's chat model (so that model does vision too).
    # mmproj must match the chat model size: 4b tiers → 4b mmproj, 27b tiers →
    # 27b mmproj. cpu-min (Qwen, not multimodal) and apple-mlx/external get none.
    "vision": {
        "cpu-min":      None,
        "cpu-std":      _VISION_MMPROJ_4B,
        "gpu-4gb":      _VISION_MMPROJ_4B,
        "gpu-8gb":      _VISION_MMPROJ_4B,
        "gpu-16gb":     _VISION_MMPROJ_4B,
        "gpu-24gb+":    _VISION_MMPROJ_27B,
        "amd-4gb":      _VISION_MMPROJ_4B,
        "amd-8gb":      _VISION_MMPROJ_4B,
        "amd-16gb":     _VISION_MMPROJ_4B,
        "amd-24gb+":    _VISION_MMPROJ_27B,
        "vulkan-4gb":   _VISION_MMPROJ_4B,
        "vulkan-8gb":   _VISION_MMPROJ_4B,
        "vulkan-16gb":  _VISION_MMPROJ_4B,
        "vulkan-24gb+": _VISION_MMPROJ_27B,
        "apple-mlx":    None,
        "external":     None,
    },
    "stt":       {tier: None for tier in ALL_TIERS},  # Phase 4
    "ocr":       {tier: None for tier in ALL_TIERS},  # Phase 5
}


# Module-level concurrency control: one pull at a time, per-id cancel flag.
_PULL_LOCK = asyncio.Lock()
_CANCEL_EVENTS: dict[str, asyncio.Event] = {}


def is_pulling() -> bool:
    return _PULL_LOCK.locked()


def request_cancel(model_uuid: str) -> bool:
    """Flip the cancel flag for an active pull. Returns True if a pull was active."""
    ev = _CANCEL_EVENTS.get(str(model_uuid))
    if ev is None:
        return False
    ev.set()
    return True



async def seed_registry(conn) -> int:
    """Idempotently upsert MODEL_REGISTRY into bundled_models. Returns count of
    rows touched. Specs that are None are skipped — those roles/tiers don't
    have artifacts yet."""
    count = 0
    for role, by_tier in MODEL_REGISTRY.items():
        for tier, spec in by_tier.items():
            if spec is None:
                continue
            await conn.execute(
                """
                INSERT INTO bundled_models (role, tier, model_id, quant, repo, filename,
                                             expected_bytes, sha256, license, license_url,
                                             revision, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
                ON CONFLICT (role, tier, model_id, quant) DO UPDATE
                SET repo = EXCLUDED.repo,
                    filename = EXCLUDED.filename,
                    expected_bytes = COALESCE(EXCLUDED.expected_bytes, bundled_models.expected_bytes),
                    sha256 = COALESCE(EXCLUDED.sha256, bundled_models.sha256),
                    license = EXCLUDED.license,
                    license_url = EXCLUDED.license_url,
                    revision = EXCLUDED.revision,
                    updated_at = NOW()
                """,
                role,
                tier,
                spec.model_id,
                spec.quant,
                spec.repo,
                spec.filename,
                spec.expected_bytes,
                spec.sha256,
                spec.license,
                spec.license_url,
                spec.revision,
            )
            count += 1

    # Prune rows the registry no longer defines (e.g. a role/tier whose model
    # changed). Without this, a retired spec lingers as a stale "ready"/"pending"
    # row in Settings — e.g. the short-lived 4b `vision_base` role and the 4b
    # mmproj that was briefly mapped to the 27b tiers. Matches on
    # (role, tier, model_id); the on-disk file (if any) is left as harmless
    # orphan data.
    valid = {
        (role, tier, spec.model_id)
        for role, by_tier in MODEL_REGISTRY.items()
        for tier, spec in by_tier.items()
        if spec is not None
    }
    existing = await conn.fetch("SELECT id, role, tier, model_id FROM bundled_models")
    stale = [
        r["id"] for r in existing
        if (r["role"], r["tier"], r["model_id"]) not in valid
    ]
    if stale:
        await conn.execute("DELETE FROM bundled_models WHERE id = ANY($1::uuid[])", stale)
        logger.info("seed_registry: pruned %d orphaned bundled_models rows", len(stale))

    return count


async def reset_orphaned_pulls(conn) -> int:
    """Reset rows wedged in 'pulling' back to 'pending'. Returns rows touched.

    Pull tasks are process-local asyncio tasks tracked only via _PULL_LOCK; a
    restart or crash orphans any in-flight 'pulling' row — the task is gone but
    the status sticks, and the UI then can't re-pull it (pull_one returns 409
    "already pulling", and cancel is a no-op with no live task). Run at boot so
    interrupted pulls become retryable instead of wedged forever.
    """
    result = await conn.execute(
        "UPDATE bundled_models SET status = 'pending', pulled_bytes = 0, "
        "error_message = NULL WHERE status = 'pulling'"
    )
    try:
        return int(str(result).split()[-1])  # asyncpg returns 'UPDATE <n>'
    except (ValueError, IndexError):
        return 0



def _hf_url(repo: str, filename: str, revision: str | None = None) -> str:
    rev = revision or "main"
    return f"https://huggingface.co/{repo}/resolve/{rev}/{filename}"


async def _hf_headers(pool_or_conn) -> dict[str, str]:
    """Authorization header for gated repos.

    Resolution: DB-stored token (services/hf_token.py) > HF_TOKEN env var > none.
    DB lookup failures fall through to env silently — pulling shouldn't break
    just because the token table is briefly unavailable.
    """
    # 1. DB-stored
    try:
        async with await _get_conn(pool_or_conn) as conn:
            from services import hf_token
            db_token = await hf_token.get(conn)
            if db_token:
                return {"Authorization": f"Bearer {db_token}"}
    except Exception:
        logger.warning("hf_token: DB lookup failed; falling back to env", exc_info=True)
    # 2. Env fallback
    env_token = (os.environ.get("HF_TOKEN") or "").strip()
    if env_token:
        return {"Authorization": f"Bearer {env_token}"}
    # 3. None
    return {}


# These roles serve a single tier-independent GGUF from a flat /models/<file>
# path — exactly what models.ini references for [medgemma] / [qwen-chat] /
# [qwen3-embed] / [qwen3-reranker] / [gemma-tasks]. The puller writes here so the
# router's static models.ini works for every tier without rewrites: each tier
# downloads a different file, but always lands at /models/<file>, and only the
# alias the active tier uses (TIER_CHAT_MODELS in bundled_providers) actually
# gets loaded by the router on demand. Vision/mmproj stays under
# /models/vision/<tier>/ because link_active_mmproj symlinks the active one.
# embed/rerank were removed (folder C, 2026-06-16): they are now kind="snapshot"
# safetensors repos written to the HF hub cache by huggingface_hub, not flat
# /models/<file> GGUFs. Only chat + tasks remain flat llama.cpp GGUFs.
_FLAT_DEST_ROLES = {"chat", "tasks"}


def _dest_path(role: str, tier: str, filename: str) -> Path:
    """Where the file lands on disk."""
    if role in _FLAT_DEST_ROLES:
        return MODELS_BASE_DIR / filename
    return MODELS_BASE_DIR / role / tier / filename


def _spec_kind(role: str, tier: str, model_id: str) -> str:
    """Re-derive a row's pull shape from MODEL_REGISTRY (the in-process source of
    truth). bundled_models does not store `kind`, so the puller looks it up by
    (role, tier, model_id). Returns 'file' when no matching spec is found."""
    spec = MODEL_REGISTRY.get(role, {}).get(tier)
    if spec is not None and spec.model_id == model_id:
        return spec.kind
    return "file"


def _snapshot_pull(repo: str, revision: str | None, token: str | None) -> str:
    """Download a full HF repo into the hub cache layout boofinity reads.

    Synchronous (huggingface_hub.snapshot_download); call via asyncio.to_thread
    so it doesn't block the loop while holding _PULL_LOCK. Lands the repo under
    INFER_CACHE_DIR/hub/models--<org>--<repo>/snapshots/<rev>/.
    """
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=repo,
        revision=revision or "main",
        cache_dir=str(INFER_CACHE_DIR / "hub"),
        token=token,
        local_files_only=False,
    )


class _Cancelled(Exception):
    """Pull was cancelled via request_cancel()."""


class InsufficientDiskError(Exception):
    """Pull rejected because of insufficient disk space."""


def _check_disk_space(dest_dir: Path, expected_bytes: int | None) -> None:
    """Refuse pull if free space minus expected_bytes leaves < 5 GB headroom.

    No-op when expected_bytes is None (we can't predict). Logs a warning
    in that case so the operator knows the check was skipped.
    """
    import shutil
    if expected_bytes is None:
        logger.warning("disk pre-flight skipped: expected_bytes unknown")
        return
    free = shutil.disk_usage(dest_dir).free
    headroom = 5 * 1024 ** 3
    needed = expected_bytes + headroom
    if free < needed:
        raise InsufficientDiskError(
            f"need {needed / 1024**3:.1f} GB free ({expected_bytes / 1024**3:.1f} GB "
            f"file + 5 GB headroom); only {free / 1024**3:.1f} GB available at {dest_dir}"
        )


async def _get_conn(pool_or_conn):
    """Async-context-managed connection from either a pool or a bare conn."""
    if hasattr(pool_or_conn, "acquire"):
        return pool_or_conn.acquire()
    # Single-connection passthrough — no-op context.
    class _Passthrough:
        def __init__(self, c): self.c = c
        async def __aenter__(self): return self.c
        async def __aexit__(self, *a): return None
    return _Passthrough(pool_or_conn)


async def _read_row(pool_or_conn, model_uuid: str):
    async with await _get_conn(pool_or_conn) as conn:
        return await conn.fetchrow(
            "SELECT id, role, tier, model_id, quant, repo, filename, "
            "expected_bytes, sha256, license, license_url, revision, status, pulled_bytes, "
            "error_message, pull_started_at, pull_finished_at "
            "FROM bundled_models WHERE id = $1::uuid",
            model_uuid,
        )


async def _mark_pulling(pool_or_conn, model_uuid: str) -> None:
    async with await _get_conn(pool_or_conn) as conn:
        await conn.execute(
            "UPDATE bundled_models "
            "SET status = 'pulling', pulled_bytes = 0, error_message = NULL, "
            "    pull_started_at = NOW(), pull_finished_at = NULL, updated_at = NOW() "
            "WHERE id = $1::uuid",
            model_uuid,
        )


async def _update_bytes(pool_or_conn, model_uuid: str, bytes_written: int, *, expected_bytes: int | None = None) -> None:
    async with await _get_conn(pool_or_conn) as conn:
        if expected_bytes is not None:
            await conn.execute(
                "UPDATE bundled_models SET pulled_bytes = $2, expected_bytes = $3, "
                "    updated_at = NOW() WHERE id = $1::uuid",
                model_uuid, bytes_written, expected_bytes,
            )
        else:
            await conn.execute(
                "UPDATE bundled_models SET pulled_bytes = $2, updated_at = NOW() "
                "WHERE id = $1::uuid",
                model_uuid, bytes_written,
            )


async def _mark_finished(pool_or_conn, model_uuid: str, *, status: str, error_message: str | None) -> None:
    async with await _get_conn(pool_or_conn) as conn:
        await conn.execute(
            "UPDATE bundled_models "
            "SET status = $2, error_message = $3, pull_finished_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = $1::uuid",
            model_uuid, status, error_message,
        )


async def _pull_snapshot(pool_or_conn, model_uuid: str, *, repo: str,
                         revision: str | None, license_url: str | None) -> dict[str, Any]:
    """Pull a kind='snapshot' row via huggingface_hub into the HF hub cache.

    Caller holds _PULL_LOCK and has already marked the row 'pulling'. Disk
    pre-flight and sha256 are skipped (snapshot total is unknown up front and
    per-file hashes are HF's job); pulled_bytes stays 0, expected_bytes NULL.
    Maps a gated/401-equivalent to the same license-acceptance message the file
    path uses, though the Qwen3 repos are ungated Apache-2.0.
    """
    token = (await _hf_headers(pool_or_conn)).get("Authorization", "")
    token = token.removeprefix("Bearer ").strip() or None
    try:
        await asyncio.to_thread(_snapshot_pull, repo, revision, token)
        await _mark_finished(pool_or_conn, model_uuid, status="ready", error_message=None)
        logger.info("model_puller: snapshot pulled %s", repo)
        return dict(await _read_row(pool_or_conn, model_uuid))
    except Exception as e:
        from huggingface_hub.utils import GatedRepoError
        if isinstance(e, GatedRepoError):
            msg = f"License acceptance required. Visit {license_url} and click Agree, then retry."
        else:
            msg = f"{type(e).__name__}: {e}"[:500]
        await _mark_finished(pool_or_conn, model_uuid, status="failed", error_message=msg)
        logger.warning("model_puller: snapshot pull failed (%s)", e)
        return dict(await _read_row(pool_or_conn, model_uuid))


async def pull_model(pool_or_conn, model_uuid: str) -> dict[str, Any]:
    """Stream-download one bundled_models row.

    Holds the module-level _PULL_LOCK so only one pull runs at a time.
    Writes to <dest>.partial, fsyncs, then renames on success. sha256 is
    verified if the spec set it. Returns the final row as a dict. Snapshot-kind
    rows (embed/rerank safetensors) dispatch to _pull_snapshot instead.
    """
    row = await _read_row(pool_or_conn, model_uuid)
    if row is None:
        raise ValueError(f"bundled_models row not found: {model_uuid}")

    role = row["role"]
    tier = row["tier"]
    repo = row["repo"]
    filename = row["filename"]
    expected_sha256 = row["sha256"]
    license_url = row["license_url"]
    revision = row["revision"]

    cancel_event = asyncio.Event()

    try:
        async with _PULL_LOCK:
            _CANCEL_EVENTS[str(model_uuid)] = cancel_event
            current_row = await _read_row(pool_or_conn, model_uuid)
            if current_row and current_row["status"] == "ready":
                logger.info("model_puller: model %s already ready, skipping re-pull", model_uuid)
                return dict(current_row)
            await _mark_pulling(pool_or_conn, model_uuid)

            if _spec_kind(role, tier, row["model_id"]) == "snapshot":
                return await _pull_snapshot(
                    pool_or_conn, model_uuid,
                    repo=repo, revision=revision, license_url=license_url,
                )

            dest = _dest_path(role, tier, filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                _check_disk_space(dest.parent, row["expected_bytes"])
            except InsufficientDiskError as e:
                await _mark_finished(pool_or_conn, model_uuid, status="failed", error_message=f"insufficient disk: {e}")
                return dict(await _read_row(pool_or_conn, model_uuid))
            partial = dest.with_suffix(dest.suffix + ".partial")
            url = _hf_url(repo, filename, revision)
            headers = await _hf_headers(pool_or_conn)

            sha = hashlib.sha256()
            bytes_written = 0

            try:
                async with httpx.AsyncClient(timeout=PULL_TIMEOUT, follow_redirects=True) as client:
                    async with client.stream("GET", url, headers=headers) as resp:
                        if resp.status_code == 401:
                            msg = (
                                "License acceptance required. "
                                f"Visit {license_url} and click Agree, then retry."
                            )
                            await _mark_finished(pool_or_conn, model_uuid, status="failed", error_message=msg)
                            return dict(await _read_row(pool_or_conn, model_uuid))
                        if resp.status_code >= 400:
                            await _mark_finished(
                                pool_or_conn, model_uuid,
                                status="failed",
                                error_message=f"HTTP {resp.status_code} from HuggingFace",
                            )
                            return dict(await _read_row(pool_or_conn, model_uuid))

                        total = int(resp.headers.get("content-length", "0")) or row["expected_bytes"] or None

                        with partial.open("wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=PULL_CHUNK_BYTES):
                                if cancel_event.is_set():
                                    raise _Cancelled()
                                if not chunk:
                                    continue
                                f.write(chunk)
                                sha.update(chunk)
                                bytes_written += len(chunk)
                                await _update_bytes(pool_or_conn, model_uuid, bytes_written, expected_bytes=total)
                            f.flush()
                            os.fsync(f.fileno())

                if expected_sha256 and sha.hexdigest() != expected_sha256:
                    try:
                        partial.unlink()
                    except OSError as _unlink_exc:
                        logger.debug("model_puller: could not remove partial on sha256 mismatch: %s", _unlink_exc)
                    await _mark_finished(
                        pool_or_conn, model_uuid,
                        status="failed",
                        error_message=f"sha256 mismatch (expected {expected_sha256}, got {sha.hexdigest()})",
                    )
                    return dict(await _read_row(pool_or_conn, model_uuid))

                partial.rename(dest)
                await _update_bytes(pool_or_conn, model_uuid, bytes_written)
                await _mark_finished(pool_or_conn, model_uuid, status="ready", error_message=None)
                logger.info("model_puller: pulled %s/%s (%d bytes)", role, tier, bytes_written)
                if role == "vision":
                    from services.bundled_providers import link_active_mmproj
                    link_active_mmproj(tier)
                elif role == "chat":
                    from services.bundled_providers import link_active_chat
                    link_active_chat(tier)
                return dict(await _read_row(pool_or_conn, model_uuid))

            except _Cancelled:
                try:
                    partial.unlink()
                except OSError as _unlink_exc:
                    logger.debug("model_puller: could not remove partial on cancel: %s", _unlink_exc)
                await _mark_finished(pool_or_conn, model_uuid, status="failed", error_message="cancelled")
                return dict(await _read_row(pool_or_conn, model_uuid))
            except Exception as e:
                try:
                    if partial.exists():
                        partial.unlink()
                except OSError as _unlink_exc:
                    logger.debug("model_puller: could not remove partial on error: %s", _unlink_exc)
                await _mark_finished(
                    pool_or_conn, model_uuid,
                    status="failed",
                    error_message=f"{type(e).__name__}: {e}"[:500],
                )
                logger.warning("model_puller: pull failed (%s)", e)
                return dict(await _read_row(pool_or_conn, model_uuid))
    finally:
        _CANCEL_EVENTS.pop(str(model_uuid), None)


async def pull_for_tier(pool, tier: str) -> dict[str, str]:
    """Return {role: model_uuid} for rows queueable at this tier
    (status in pending/failed). Caller schedules each via asyncio.create_task."""
    queued: dict[str, str] = {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, role FROM bundled_models "
            "WHERE tier = $1 AND status IN ('pending', 'failed')",
            tier,
        )
    for r in rows:
        queued[r["role"]] = str(r["id"])
    return queued
