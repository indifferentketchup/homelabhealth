"""Verify backend/services/model_puller.py.

Runs INSIDE the hlh_api container so asyncpg + httpx + the homelabhealth
backend modules are all importable:

    docker exec hlh_api python /app/scripts/verify_model_puller.py

Three checks:
  1. MODEL_REGISTRY shape  -  every role/tier key maps to ModelSpec | None.
  2. seed_registry() idempotency  -  second call doesn't add rows.
  3. End-to-end streaming download of a tiny public HF file (no gated repo,
     no HF_TOKEN required). Verifies status=ready, file lands at the
     expected on-disk path with non-zero bytes.

Exits 0 on success, non-zero on any failed assertion.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# /app is the container WORKDIR; ensure imports resolve.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# Use a writable tmp dir for the test download to avoid touching /models.
os.environ["HLH_MODELS_DIR"] = "/tmp/verify_model_puller"

from db import close_pool, get_pool, init_pool  # noqa: E402
from services import model_puller  # noqa: E402
from services.model_puller import (  # noqa: E402
    ALL_ROLES,
    ALL_TIERS,
    MODEL_REGISTRY,
    ModelSpec,
    pull_model,
    seed_registry,
)

# Override the on-disk root post-import so all code paths use /tmp.
model_puller.MODELS_BASE_DIR = Path("/tmp/verify_model_puller")
model_puller.MODELS_BASE_DIR.mkdir(parents=True, exist_ok=True)


GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  {GREEN}PASS{RESET}  {label}")
    else:
        msg = f"  {RED}FAIL{RESET}  {label}"
        if detail:
            msg += f"  -  {detail}"
        print(msg)
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n -  {title}  - ")


async def shape_check() -> None:
    section("MODEL_REGISTRY shape")
    check("MODEL_REGISTRY has all 7 roles", set(MODEL_REGISTRY.keys()) == set(ALL_ROLES),
          f"got {sorted(MODEL_REGISTRY.keys())}")
    for role in ALL_ROLES:
        check(f"role={role} has all 7 tiers",
              set(MODEL_REGISTRY[role].keys()) == set(ALL_TIERS),
              f"got {sorted(MODEL_REGISTRY[role].keys())}")
        for tier, spec in MODEL_REGISTRY[role].items():
            ok = spec is None or isinstance(spec, ModelSpec)
            check(f"  {role}/{tier} is ModelSpec|None", ok, f"got {type(spec).__name__}")
    chat = MODEL_REGISTRY["chat"]
    check("chat/cpu-min has a real spec", isinstance(chat["cpu-min"], ModelSpec))
    check("chat/external is None (operator picks external)", chat["external"] is None)
    check("chat/apple-mlx is None (Phase 6)", chat["apple-mlx"] is None)
    # Non-chat roles are all None in Phase 1.
    for role in ALL_ROLES:
        if role == "chat":
            continue
        for tier, spec in MODEL_REGISTRY[role].items():
            check(f"Phase 1 placeholder: {role}/{tier} is None", spec is None,
                  f"got {type(spec).__name__}")


async def idempotency_check(pool) -> None:
    section("seed_registry() idempotency")
    async with pool.acquire() as conn:
        # Count expected Phase-1 rows: chat with 5 specs (cpu-min, cpu-std, gpu-8gb, gpu-16gb, gpu-24gb+).
        expected_rows = sum(
            1 for by_tier in MODEL_REGISTRY.values()
            for spec in by_tier.values()
            if spec is not None
        )
        n1 = await seed_registry(conn)
        total1 = await conn.fetchval("SELECT COUNT(*) FROM bundled_models")
        n2 = await seed_registry(conn)
        total2 = await conn.fetchval("SELECT COUNT(*) FROM bundled_models")
    check(f"first seed touched {expected_rows} rows", n1 == expected_rows, f"got {n1}")
    check(f"row count = expected after first seed", total1 == expected_rows, f"got {total1}")
    check("second seed touches same count", n2 == n1)
    check("row count unchanged after re-seed", total1 == total2, f"{total1} vs {total2}")


async def download_check(pool) -> None:
    section("streaming download of a tiny public HF file")
    # hf-internal-testing/tiny-random-bert/config.json is ~700 bytes,
    # public (no token required), stable content. We insert a synthetic
    # row pointing at it, run pull_model, and assert it lands at the
    # expected on-disk path with status=ready.
    role = "chat"
    tier = "verify-test"  # NOT a real tier  -  won't collide with seeded rows
    test_id = str(uuid.uuid4())
    spec_repo = "hf-internal-testing/tiny-random-bert"
    spec_filename = "config.json"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bundled_models (id, role, tier, model_id, quant, repo, filename, status) "
            "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, 'pending')",
            test_id, role, tier, f"{spec_repo}@{spec_filename}", "test",
            spec_repo, spec_filename,
        )

    try:
        result = await pull_model(pool, test_id)
        check("pull_model returned a row", isinstance(result, dict))
        check("status flipped to 'ready'", result.get("status") == "ready",
              f"got {result.get('status')!r}, error={result.get('error_message')!r}")
        check("pulled_bytes > 0", int(result.get("pulled_bytes") or 0) > 0,
              f"got {result.get('pulled_bytes')}")
        expected_path = model_puller.MODELS_BASE_DIR / role / tier / spec_filename
        check(f"file landed at {expected_path}", expected_path.exists())
        if expected_path.exists():
            check("file is non-empty", expected_path.stat().st_size > 0,
                  f"size={expected_path.stat().st_size}")
            # Cleanup so re-runs start clean.
            try:
                expected_path.unlink()
            except OSError:
                pass
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bundled_models WHERE id = $1::uuid", test_id)


async def main() -> int:
    await init_pool()
    pool = await get_pool()
    try:
        await shape_check()
        await idempotency_check(pool)
        await download_check(pool)
    finally:
        await close_pool()

    print()
    if _failures:
        print(f"{RED}{len(_failures)} failure(s){RESET}:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}All checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
