"""L0-L4 graded context recovery for the hash-chained audit system.

Recovery is READ-ONLY  -  it queries existing audit data and does not modify
the hash chain. The JSONL buffer (``.omo/audit_buffer.jsonl``) provides fast
in-flight capture of tool executions, flushed to the audit trail on stop via
T2 hook callbacks.

Recovery levels:
  L0: Index summary (~200t)  -  session count, timestamps, last 5 events
  L1: Session trail (~500t)  -  last N audit events, optionally by session
  L2: Corrections (~1000t)  -  correction/action-filtered events only
  L3: Full context (~3000t)  -  complete paginated session audit trail
  L4: Cross-day (~5000t+)  -  aggregate stats across sessions

Port patterns from:
  - /opt/forks/audit-harness/lib/audit_context.py  (core audit engine patterns)
  - /opt/forks/boocontext-audit/src/recovery.ts      (graded recovery levels)
  - /opt/forks/boocontext-audit/src/buffer.ts        (JSONL buffer pattern)
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from db import get_pool
from services.audit import AuditRecord, insert_audit_event
from services.hooks import register as _register_hook

logger = logging.getLogger(__name__)

BUFFER_DIR_ENV = "HLH_AUDIT_BUFFER_DIR"
DEFAULT_BUFFER_DIR = ".omo"
BUFFER_FILENAME = "audit_buffer.jsonl"
MAX_SUMMARY_LENGTH = 200
MAX_TOOL_INPUT_LENGTH = 1000


@dataclass
class BufferRecord:
    """One in-flight tool execution record in the JSONL buffer."""

    ts: str
    tool: str
    session: str
    summary: str
    input_keys: list[str]
    duration_ms: float


def _buffer_dir() -> Path:
    """Resolve the buffer directory from env var or fallback to tmp."""
    buf_dir = os.environ.get(BUFFER_DIR_ENV, DEFAULT_BUFFER_DIR)
    p = Path(buf_dir)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback to system temp directory when configured dir is unwritable
        # (e.g. read-only container filesystem).
        import tempfile

        p = Path(tempfile.gettempdir()) / ".omo-audit"
        p.mkdir(parents=True, exist_ok=True)
    return p


def _buffer_path() -> Path:
    """Full path to the audit buffer JSONL file."""
    return _buffer_dir() / BUFFER_FILENAME


def _append_buffer(record: BufferRecord) -> None:
    """Append one record to the JSONL buffer with file-level locking.

    This is intentionally synchronous (fast file I/O) so the hook callback
    does not introduce async scheduling latency.
    """
    path = _buffer_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("audit_recovery: unable to write buffer: %s", exc)


def _read_buffer() -> list[dict[str, Any]]:
    """Read all records from the buffer file."""
    path = _buffer_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return records


def _truncate_buffer() -> None:
    """Truncate the buffer file (empty it in place)."""
    path = _buffer_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.truncate(0)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("audit_recovery: unable to truncate buffer: %s", exc)


async def flush_buffer() -> int:
    """Read the JSONL buffer, batch-insert to audit_log, then truncate.

    Skips records that already have a matching ``audit_log`` row (matched
    by ``request_id`` + ``action``) to avoid duplicates when both the
    immediate audit.py hook and the buffer flush would write the same event.

    Returns the number of new records flushed.
    """
    records = _read_buffer()
    if not records:
        return 0

    pool = await get_pool()
    inserted = 0

    async with pool.acquire() as conn:
        for rec in records:
            tool = rec.get("tool", "unknown")
            session_raw = rec.get("session", "")

            # Build a stable request_id from the session field
            try:
                req_id = uuid.UUID(session_raw)
            except (ValueError, AttributeError):
                req_id = uuid.uuid4()

            # Deduplicate against the existing audit_log
            exists = await conn.fetchval(
                "SELECT 1 FROM audit_log WHERE request_id = $1::uuid AND action = $2 LIMIT 1",
                req_id,
                f"tool.{tool}",
            )
            if exists:
                continue

            payload = json.dumps({
                "tool": tool,
                "duration_ms": rec.get("duration_ms", 0.0),
                "input_keys": rec.get("input_keys", []),
            })
            audit_rec = AuditRecord(
                request_id=req_id,
                actor="system",
                action=f"tool.{tool}",
                target_type="recovery",
                target_id=None,
                status_code=200,
                payload_hash=hashlib.sha256(payload.encode("utf-8")).digest(),
            )
            try:
                await insert_audit_event(conn, audit_rec)
                inserted += 1
            except Exception:
                logger.exception("audit_recovery: buffer flush insert failed")
                continue

    _truncate_buffer()
    return inserted



async def _recover_l0(conn: asyncpg.Connection) -> dict[str, Any]:
    """L0: Index summary  -  total counts, time range, last 5 events."""
    total = await conn.fetchval("SELECT COUNT(*)::int FROM audit_log")
    sessions = await conn.fetchval(
        "SELECT COUNT(DISTINCT request_id)::int FROM audit_log",
    )
    time_row = await conn.fetchrow(
        """SELECT MIN(ts) AT TIME ZONE 'UTC' AS first_ts,
                  MAX(ts) AT TIME ZONE 'UTC' AS last_ts
           FROM audit_log""",
    )
    last_5 = await conn.fetch(
        """SELECT id, ts, request_id, actor, action,
                  target_type, target_id, status_code
           FROM audit_log
           ORDER BY id DESC
           LIMIT 5""",
    )
    return {
        "total_events": total or 0,
        "total_sessions": sessions or 0,
        "first_event": (
            time_row["first_ts"].isoformat()
            if time_row and time_row["first_ts"]
            else None
        ),
        "last_event": (
            time_row["last_ts"].isoformat()
            if time_row and time_row["last_ts"]
            else None
        ),
        "recent": [
            {
                "id": r["id"],
                "ts": r["ts"].isoformat(),
                "request_id": str(r["request_id"]),
                "actor": r["actor"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "status_code": r["status_code"],
            }
            for r in last_5
        ],
    }


async def _recover_l1(
    conn: asyncpg.Connection,
    request_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """L1: Session trail  -  last N audit events, optionally filtered by request."""
    if request_id is not None:
        rows = await conn.fetch(
            """SELECT id, ts, request_id, actor, action,
                      target_type, target_id, status_code
               FROM audit_log
               WHERE request_id = $1::uuid
               ORDER BY id DESC
               LIMIT $2""",
            request_id,
            limit,
        )
    else:
        rows = await conn.fetch(
            """SELECT id, ts, request_id, actor, action,
                      target_type, target_id, status_code
               FROM audit_log
               ORDER BY id DESC
               LIMIT $1""",
            limit,
        )
    return [
        {
            "id": r["id"],
            "ts": r["ts"].isoformat(),
            "request_id": str(r["request_id"]),
            "actor": r["actor"],
            "action": r["action"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "status_code": r["status_code"],
        }
        for r in rows
    ]


async def _recover_l2(
    conn: asyncpg.Connection,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """L2: Corrections  -  events whose action mentions 'correction' or 'edit'."""
    rows = await conn.fetch(
        """SELECT id, ts, request_id, actor, action,
                  target_type, target_id, status_code
           FROM audit_log
           WHERE action ILIKE '%correction%' OR action ILIKE '%edit%'
           ORDER BY id DESC
           LIMIT $1""",
        limit,
    )
    return [
        {
            "id": r["id"],
            "ts": r["ts"].isoformat(),
            "request_id": str(r["request_id"]),
            "actor": r["actor"],
            "action": r["action"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "status_code": r["status_code"],
        }
        for r in rows
    ]


async def _recover_l3(
    conn: asyncpg.Connection,
    request_id: uuid.UUID | None = None,
    page: int = 0,
    page_size: int = 50,
) -> dict[str, Any]:
    """L3: Full context  -  paginated complete audit trail."""
    offset = page * page_size

    if request_id is not None:
        rows = await conn.fetch(
            """SELECT id, ts, request_id, actor, action,
                      target_type, target_id, status_code
               FROM audit_log
               WHERE request_id = $1::uuid
               ORDER BY id DESC
               LIMIT $2 OFFSET $3""",
            request_id,
            page_size,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM audit_log WHERE request_id = $1::uuid",
            request_id,
        )
    else:
        rows = await conn.fetch(
            """SELECT id, ts, request_id, actor, action,
                      target_type, target_id, status_code
               FROM audit_log
               ORDER BY id DESC
               LIMIT $1 OFFSET $2""",
            page_size,
            offset,
        )
        total = await conn.fetchval("SELECT COUNT(*)::int FROM audit_log")

    return {
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "rows": [
            {
                "id": r["id"],
                "ts": r["ts"].isoformat(),
                "request_id": str(r["request_id"]),
                "actor": r["actor"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "status_code": r["status_code"],
            }
            for r in rows
        ],
    }


async def _recover_l4(
    conn: asyncpg.Connection,
) -> dict[str, Any]:
    """L4: Cross-day aggregates  -  event type distribution, daily counts, top actors."""
    type_dist = await conn.fetch(
        """SELECT action, COUNT(*)::int AS cnt
           FROM audit_log
           GROUP BY action
           ORDER BY cnt DESC""",
    )
    daily = await conn.fetch(
        """SELECT DATE(ts) AS day, COUNT(*)::int AS cnt
           FROM audit_log
           GROUP BY day
           ORDER BY day DESC""",
    )
    top_actors = await conn.fetch(
        """SELECT actor, COUNT(*)::int AS cnt
           FROM audit_log
           GROUP BY actor
           ORDER BY cnt DESC""",
    )
    return {
        "event_type_distribution": [
            {"action": r["action"], "count": r["cnt"]} for r in type_dist
        ],
        "daily_counts": [
            {"day": r["day"].isoformat(), "count": r["cnt"]} for r in daily
        ],
        "top_actors": [
            {"actor": r["actor"], "count": r["cnt"]} for r in top_actors
        ],
    }



async def recover(
    level: int = 0,
    session_id: str | None = None,
    limit: int = 20,
    page: int = 0,
    page_size: int = 50,
) -> dict[str, Any]:
    """Graded context recovery from the audit log.

    Parameters
    ----------
    level:
        Recovery level 0-4. Unknown levels degrade gracefully to L0.
    session_id:
        Optional UUID to filter by ``audit_log.request_id``.
    limit:
        Max events to return for L1, L2.
    page:
        Zero-indexed page for L3 pagination.
    page_size:
        Events per page for L3 (clamped 10-200, default 50).

    Returns
    -------
    Level-appropriate dict. Key ``level`` identifies the recovery tier.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Validate session_id UUID up front so internal helpers always
        # receive a valid UUID or None.
        sid: uuid.UUID | None = None
        if session_id:
            try:
                sid = uuid.UUID(session_id)
            except (ValueError, AttributeError):
                pass  # invalid UUID  -  ignore filter and return unfiltered

        if level == 1:
            data = await _recover_l1(conn, sid, min(limit, 100))
            return {"level": 1, "session_id": session_id, "events": data}

        if level == 2:
            data = await _recover_l2(conn, min(limit, 200))
            return {"level": 2, "events": data}

        if level == 3:
            ps = min(max(page_size, 10), 200)
            data = await _recover_l3(conn, sid, page, ps)
            return {"level": 3, "session_id": session_id, **data}

        if level == 4:
            data = await _recover_l4(conn)
            return {"level": 4, **data}

        # Default / level 0
        data = await _recover_l0(conn)
        return {"level": 0, **data}



def _summarize_tool_call(tool_name: str, tool_input: dict) -> str:
    """Produce a short human-readable summary of a tool invocation.

    Mirrors ``boocontext-audit/src/buffer.ts`` ``summarizeToolCall()``.
    """
    if tool_name in ("bash", "execute_command"):
        cmd = str(
            tool_input.get("command", tool_input.get("Command", "")),
        )
        first_line = cmd.split("\n")[0].strip()
        if first_line.startswith("#"):
            rest = [
                l
                for l in cmd.split("\n")[1:]
                if l.strip() and not l.strip().startswith("#")
            ]
            return (rest[0] if rest else first_line)[:MAX_TOOL_INPUT_LENGTH]
        return first_line[:MAX_TOOL_INPUT_LENGTH]
    if tool_name in ("write", "edit", "create_file", "edit_file", "Write", "Edit"):
        return str(
            tool_input.get(
                "filePath",
                tool_input.get("path", tool_input.get("file_path", "")),
            ),
        )[:MAX_TOOL_INPUT_LENGTH]
    return tool_name


async def _recovery_on_tool_execution(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    ctx: Any,
    duration_ms: float,
) -> None:
    """Post-tool-execution hook callback: buffer the invocation.

    Registered at module import time. This is intentionally fast (file
    append) so it does not introduce async scheduling latency.
    """
    if not ctx or not ctx.request_id:
        return
    summary = _summarize_tool_call(tool_name, tool_input)
    rec = BufferRecord(
        ts=datetime.now(timezone.utc).isoformat(),
        tool=tool_name,
        session=ctx.request_id,
        summary=summary[:MAX_SUMMARY_LENGTH],
        input_keys=list(tool_input.keys())[:20],  # cap to prevent bloated records
        duration_ms=duration_ms,
    )
    _append_buffer(rec)


async def _recovery_on_stop(reason: str, ctx: Any) -> None:
    """On-stop hook callback: flush buffered events to the audit trail.

    The flush is best-effort  -  failures are logged but do not propagate.
    """
    if not ctx or not ctx.chat_id:
        return
    try:
        flushed = await flush_buffer()
        if flushed:
            logger.info(
                "audit_recovery: flushed %d buffered records on stop (chat=%s)",
                flushed,
                ctx.chat_id,
            )
    except Exception:
        logger.exception("audit_recovery: flush on stop failed")


_register_hook("post_tool_execution", _recovery_on_tool_execution)
_register_hook("on_stop", _recovery_on_stop)
