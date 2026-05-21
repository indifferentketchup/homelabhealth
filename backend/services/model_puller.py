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

ALL_ROLES = ("chat", "embed", "rerank", "vision", "medsiglip", "stt", "ocr")
ALL_TIERS = ("cpu-min", "cpu-std", "gpu-8gb", "gpu-16gb", "gpu-24gb+", "apple-mlx", "external")

PULL_CHUNK_BYTES = 5 * 1024 * 1024
PULL_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=10.0)


@dataclass(frozen=True)
class ModelSpec:
    """A model's pull spec: repo + filename + integrity + license metadata.

    `expected_bytes` and `sha256` are optional. `license` and `license_url`
    are surfaced to the operator for gated repos.
    """
    repo: str
    filename: str
    quant: str | None = None
    expected_bytes: int | None = None
    sha256: str | None = None
    license: str | None = None
    license_url: str | None = None

    @property
    def model_id(self) -> str:
        """Identifier embedded in the bundled_models UNIQUE constraint."""
        return f"{self.repo}@{self.filename}"


_GEMMA_LICENSE = "gemma"

# Phase 1 supplies chat specs only; all other roles get None placeholders so
# the schema is exercised but no pulls happen. Subsequent phases extend each
# role's tier map.
MODEL_REGISTRY: dict[str, dict[str, ModelSpec | None]] = {
    "chat": {
        "cpu-min": ModelSpec(
            repo="Qwen/Qwen3-1.7B-GGUF",
            filename="Qwen3-1.7B-Q4_K_M.gguf",
            quant="Q4_K_M",
            license="apache-2.0",
            license_url="https://huggingface.co/Qwen/Qwen3-1.7B-GGUF",
        ),
        "cpu-std": ModelSpec(
            repo="google/medgemma-4b-it",
            filename="medgemma-4b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
        ),
        "gpu-8gb": ModelSpec(
            repo="google/medgemma-4b-it",
            filename="medgemma-4b-it-Q8_0.gguf",
            quant="Q8_0",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-4b-it",
        ),
        "gpu-16gb": ModelSpec(
            repo="google/medgemma-27b-text-it",
            filename="medgemma-27b-text-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-27b-text-it",
        ),
        "gpu-24gb+": ModelSpec(
            repo="google/medgemma-27b-it",
            filename="medgemma-27b-it-Q4_K_M.gguf",
            quant="Q4_K_M",
            license=_GEMMA_LICENSE,
            license_url="https://huggingface.co/google/medgemma-27b-it",
        ),
        "apple-mlx": None,  # Phase 6
        "external": None,
    },
    "embed":     {tier: None for tier in ALL_TIERS},  # Phase 2
    "rerank":    {tier: None for tier in ALL_TIERS},  # Phase 2
    "vision":    {tier: None for tier in ALL_TIERS},  # Phase 3
    "medsiglip": {tier: None for tier in ALL_TIERS},  # Phase 3
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


# ──────────────────────────────────────────────────────────────────────────────
# Registry seeding.
# ──────────────────────────────────────────────────────────────────────────────


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
                                             status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
                ON CONFLICT (role, tier, model_id, quant) DO UPDATE
                SET repo = EXCLUDED.repo,
                    filename = EXCLUDED.filename,
                    expected_bytes = COALESCE(EXCLUDED.expected_bytes, bundled_models.expected_bytes),
                    sha256 = COALESCE(EXCLUDED.sha256, bundled_models.sha256),
                    license = EXCLUDED.license,
                    license_url = EXCLUDED.license_url,
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
            )
            count += 1
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Pull mechanics.
# ──────────────────────────────────────────────────────────────────────────────


def _hf_url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


def _hf_headers() -> dict[str, str]:
    """Authorization header for gated repos if HF_TOKEN is set."""
    token = (os.environ.get("HF_TOKEN") or "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _dest_path(role: str, tier: str, filename: str) -> Path:
    """Where the file lands on disk."""
    return MODELS_BASE_DIR / role / tier / filename


class _Cancelled(Exception):
    """Pull was cancelled via request_cancel()."""


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
            "expected_bytes, sha256, license, license_url, status, pulled_bytes, "
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


async def pull_model(pool_or_conn, model_uuid: str) -> dict[str, Any]:
    """Stream-download one bundled_models row.

    Holds the module-level _PULL_LOCK so only one pull runs at a time.
    Writes to <dest>.partial, fsyncs, then renames on success. sha256 is
    verified if the spec set it. Returns the final row as a dict.
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

    cancel_event = asyncio.Event()
    _CANCEL_EVENTS[str(model_uuid)] = cancel_event

    try:
        async with _PULL_LOCK:
            await _mark_pulling(pool_or_conn, model_uuid)

            dest = _dest_path(role, tier, filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_suffix(dest.suffix + ".partial")
            url = _hf_url(repo, filename)
            headers = _hf_headers()

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
                    except OSError:
                        pass
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
                return dict(await _read_row(pool_or_conn, model_uuid))

            except _Cancelled:
                try:
                    partial.unlink()
                except OSError:
                    pass
                await _mark_finished(pool_or_conn, model_uuid, status="failed", error_message="cancelled")
                return dict(await _read_row(pool_or_conn, model_uuid))
            except Exception as e:
                try:
                    if partial.exists():
                        partial.unlink()
                except OSError:
                    pass
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
