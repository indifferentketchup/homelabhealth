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
        print("HLH_AUDIT_LOG_RETENTION_DAYS unset — no audit rows pruned")
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
            rows = await conn.fetch(
                "DELETE FROM audit_log WHERE ts < $1 RETURNING id",
                cutoff,
            )
        ids = [r["id"] for r in rows]
        print(
            f"Pruned {len(ids)} audit rows older than {cutoff.isoformat()}."
            f" ids range: {min(ids)}..{max(ids)}."
            " Chain integrity is preserved from the new head backward;"
            " old rows are gone permanently (intentional operator action)."
            " TODO: verify_chain --since option to skip pre-cutoff range."
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
