"""Audit log retention CLI.

Prune audit_log rows older than HLH_AUDIT_LOG_RETENTION_DAYS days.

Default behaviour (env var unset): print a no-op message and exit 0.
Deletion uses the `hlh` DB owner role, NOT `hlh_audit_writer`. The
`hlh_audit_writer` role only has INSERT/SELECT; DELETE belongs to `hlh`.

Run:
    python -m hlh.audit_retention              # deletes rows (if any) outside window
    python -m hlh.audit_retention --dry-run    # shows count, touches nothing

Exit code: 0 on success or no-op; 1 on hard errors (DB connection failure, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone


async def _run(dry_run: bool) -> int:
    raw = os.environ.get("HLH_AUDIT_LOG_RETENTION_DAYS", "").strip()
    if not raw:
        print("HLH_AUDIT_LOG_RETENTION_DAYS unset — no audit rows pruned")
        return 0
    try:
        days = int(raw)
    except ValueError:
        print(
            f"HLH_AUDIT_LOG_RETENTION_DAYS invalid value (got {raw!r},"
            " want positive integer) — no audit rows pruned"
        )
        return 0
    if days <= 0:
        print(
            f"HLH_AUDIT_LOG_RETENTION_DAYS must be a positive integer"
            f" (got {days}) — no audit rows pruned"
        )
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    from db import init_pool, close_pool, get_pool
    await init_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM audit_log WHERE ts < $1",
                cutoff,
            )
            if count == 0:
                print(f"No audit rows older than {cutoff.isoformat()} — nothing to prune")
                return 0
            if dry_run:
                print(
                    f"[dry-run] Would prune {count} audit rows older than {cutoff.isoformat()}."
                    " Re-run without --dry-run to delete."
                )
                return 0
            # Atomically DELETE the old rows and advance the chain anchor so
            # doctor's audit_log_chain check still validates the remaining
            # rows. Without this anchor advance, the post-prune oldest row's
            # prev_hash would no longer match the 32-zero-byte genesis,
            # producing a permanent false-positive ERROR.
            async with conn.transaction():
                deleted = await conn.fetch(
                    "DELETE FROM audit_log WHERE ts < $1 RETURNING id",
                    cutoff,
                )
                new_oldest = await conn.fetchrow(
                    "SELECT prev_hash FROM audit_log ORDER BY id ASC LIMIT 1"
                )
                if new_oldest is None:
                    # Pruned everything — reset anchor to genesis zeros.
                    new_anchor = b"\x00" * 32
                else:
                    new_anchor = bytes(new_oldest["prev_hash"])
                await conn.execute(
                    "UPDATE audit_log_chain_head SET first_anchor_hash = $1 WHERE id = 1",
                    new_anchor,
                )
        ids = [r["id"] for r in deleted]
        print(
            f"Pruned {len(ids)} audit rows older than {cutoff.isoformat()}."
            f" ids range: {min(ids)}..{max(ids)}. Chain anchor advanced."
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await close_pool()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune audit_log rows older than HLH_AUDIT_LOG_RETENTION_DAYS days."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show how many rows would be deleted; do not delete anything.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(_main())
