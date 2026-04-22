"""Background idle sweep + LRU eviction for tmux-backed terminal sessions.

Every 15 minutes the loop:
  1. Asks tmux for the live set of session names.
  2. Reconciles DB → tmux: any row with closed_at NULL but no matching
     tmux session is marked closed (catches agent container restarts or
     out-of-band kills).
  3. Idle sweep: kill + close any row past the 24h detach TTL that
     currently has zero attached WS clients.

Also exposes ``lru_evict_if_needed`` for the router's POST handler: when
the unpinned cap is reached, kill the oldest detached unpinned session
with no attached clients; raise 409 if nothing is eligible.

device_count lives in-memory in ``tmux_session._pty_subscribers``. SQL
cannot filter on it, so we pull candidates in SQL and filter in Python.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from db import get_pool
from services import tmux_session


logger = logging.getLogger(__name__)


SWEEP_INTERVAL_SECONDS = 15 * 60
DETACH_TTL_SECONDS = 24 * 60 * 60
UNPINNED_ACTIVE_CAP = 10


@dataclass
class SweepResult:
    reconciled: int
    idle_killed: int


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _reconcile(conn, active: set[str]) -> int:
    """Mark DB-live rows whose tmux session is gone as closed."""
    if active:
        result = await conn.execute(
            """
            UPDATE terminal_sessions
            SET closed_at = NOW()
            WHERE closed_at IS NULL AND NOT (tmux_name = ANY($1::text[]))
            """,
            list(active),
        )
    else:
        result = await conn.execute(
            """
            UPDATE terminal_sessions
            SET closed_at = NOW()
            WHERE closed_at IS NULL
            """
        )
    # "UPDATE N" → count
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def _idle_kill_candidates(
    conn,
    active: set[str],
    *,
    now: datetime,
    ttl_seconds: int = DETACH_TTL_SECONDS,
) -> list[dict]:
    """Pull DB rows eligible for idle eviction; filter device_count in Python."""
    if not active:
        return []
    cutoff = now - timedelta(seconds=ttl_seconds)
    rows = await conn.fetch(
        """
        SELECT id, tmux_name
        FROM terminal_sessions
        WHERE closed_at IS NULL
          AND pinned = FALSE
          AND last_detached_at IS NOT NULL
          AND last_detached_at < $1
          AND tmux_name = ANY($2::text[])
        """,
        cutoff,
        list(active),
    )
    return [
        {"id": r["id"], "tmux_name": r["tmux_name"]}
        for r in rows
        if tmux_session.device_count(str(r["id"])) == 0
    ]


async def sweep_once(
    *,
    now: datetime | None = None,
    list_active: Callable[[], Awaitable[set[str]]] | None = None,
    kill_session: Callable[[str], Awaitable[None]] | None = None,
    ttl_seconds: int = DETACH_TTL_SECONDS,
) -> SweepResult:
    """One sweep cycle. All time + tmux dependencies are injectable for tests.

    Call with ``now`` set (and optionally overridden ``list_active`` /
    ``kill_session``) from unit tests; production call passes no args.
    """
    ts = now if now is not None else _now_utc()
    lister = list_active if list_active is not None else tmux_session.list_active
    killer = kill_session if kill_session is not None else tmux_session.kill

    active = await lister()
    pool = await get_pool()
    async with pool.acquire() as conn:
        reconciled = await _reconcile(conn, active)
        candidates = await _idle_kill_candidates(
            conn, active, now=ts, ttl_seconds=ttl_seconds
        )
        idle_killed = 0
        for cand in candidates:
            try:
                await killer(cand["tmux_name"])
            except Exception as e:
                logger.warning(
                    "idle-kill tmux failed tmux_name=%s err=%s", cand["tmux_name"], e
                )
                continue
            await conn.execute(
                "UPDATE terminal_sessions SET closed_at = NOW() WHERE id = $1::uuid",
                cand["id"],
            )
            idle_killed += 1
    return SweepResult(reconciled=reconciled, idle_killed=idle_killed)


async def lru_evict_if_needed(
    conn,
    *,
    active: set[str] | None = None,
    kill_session: Callable[[str], Awaitable[None]] | None = None,
) -> bool:
    """Evict the oldest detached unpinned session if we're at the cap.

    Returns True if an eviction happened (or wasn't needed), False if
    the cap is hit with nothing eligible — caller should raise 409.
    """
    killer = kill_session if kill_session is not None else tmux_session.kill
    live = active if active is not None else await tmux_session.list_active()

    active_unpinned = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM terminal_sessions
        WHERE closed_at IS NULL AND pinned = FALSE
        """,
    )
    if not active_unpinned or active_unpinned < UNPINNED_ACTIVE_CAP:
        return True

    rows = await conn.fetch(
        """
        SELECT id, tmux_name
        FROM terminal_sessions
        WHERE closed_at IS NULL
          AND pinned = FALSE
          AND last_detached_at IS NOT NULL
          AND tmux_name = ANY($1::text[])
        ORDER BY last_detached_at ASC
        """,
        list(live) if live else [],
    )
    target = next(
        (r for r in rows if tmux_session.device_count(str(r["id"])) == 0),
        None,
    )
    if target is None:
        return False

    try:
        await killer(target["tmux_name"])
    except Exception as e:
        logger.warning(
            "lru-evict tmux failed tmux_name=%s err=%s", target["tmux_name"], e
        )
        return False
    await conn.execute(
        "UPDATE terminal_sessions SET closed_at = NOW() WHERE id = $1::uuid",
        target["id"],
    )
    return True


async def sweep_loop(*, interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    """Run forever; caller is responsible for cancelling on shutdown."""
    logger.info("terminal_sweep started interval=%ss", interval_seconds)
    while True:
        try:
            result = await sweep_once()
            if result.reconciled or result.idle_killed:
                logger.info(
                    "terminal_sweep reconciled=%d idle_killed=%d",
                    result.reconciled,
                    result.idle_killed,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("terminal_sweep tick failed: %s", e)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise
