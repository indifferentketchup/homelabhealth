"""Audit log insert primitive + chain hash logic.

Spec: docs/superpowers/specs/2026-05-23-v0.11.0-c4-audit-logging-design.md

Hash chain: row_hash = sha256(prev_hash || canonicalized_fields).
Canonicalization joins fields by \\x1F (ASCII unit separator) for
reproducibility (no JSON ordering issues).

Inserts are serialized by SELECT ... FOR UPDATE on the audit_log_chain_head
singleton. The actual INSERT runs as role `hlh_audit_writer` (SET LOCAL ROLE)
so that the surrounding `hlh` connection cannot accidentally DELETE.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import asyncpg

_SEP = b"\x1f"


@dataclass
class AuditRecord:
    request_id: uuid.UUID
    actor: str
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    status_code: Optional[int]
    payload_hash: bytes   # 32 bytes
    ts: Optional[datetime] = None  # defaults to NOW() in DB when None

    def __post_init__(self) -> None:
        # Reject naive datetimes — TIMESTAMPTZ normalizes on store, so an
        # inserted-with-naive-ts row would re-read with a tz-aware datetime
        # whose isoformat() differs from what was hashed at insert time,
        # silently breaking the chain on later verify.
        if self.ts is not None and self.ts.tzinfo is None:
            raise ValueError("ts must be timezone-aware")


def _canonicalize(rec: AuditRecord, ts_iso: str) -> bytes:
    """Reproducible byte representation. Fields joined by \\x1F.

    Rejects any text field containing a literal \\x1F byte — otherwise two
    distinct field tuples can produce the same canonical byte string
    (e.g. actor='a\\x1Fb', action='' collides with actor='a', action='b').
    """
    for fname, fval in (
        ("actor", rec.actor),
        ("action", rec.action),
        ("target_type", rec.target_type),
        ("target_id", rec.target_id),
    ):
        if fval is not None and "\x1f" in fval:
            raise ValueError(f"field {fname} contains forbidden \\x1F byte")
    parts = [
        ts_iso.encode("utf-8"),
        rec.request_id.hex.encode("ascii"),
        rec.actor.encode("utf-8"),
        rec.action.encode("utf-8"),
        (rec.target_type or "").encode("utf-8"),
        (rec.target_id or "").encode("utf-8"),
        (str(rec.status_code) if rec.status_code is not None else "").encode("ascii"),
        rec.payload_hash,
    ]
    return _SEP.join(parts)


def _compute_row_hash(prev_hash: bytes, rec: AuditRecord, ts_iso: str) -> bytes:
    if len(prev_hash) != 32:
        raise ValueError(f"prev_hash must be 32 bytes, got {len(prev_hash)}")
    if len(rec.payload_hash) != 32:
        raise ValueError(f"payload_hash must be 32 bytes, got {len(rec.payload_hash)}")
    if rec.ts is not None and rec.ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    h = hashlib.sha256()
    h.update(prev_hash)
    h.update(_canonicalize(rec, ts_iso))
    return h.digest()


async def insert_audit_event(conn: asyncpg.Connection, rec: AuditRecord) -> int:
    """Insert one audit row inside a transaction.

    Holds SELECT ... FOR UPDATE on audit_log_chain_head for the duration.
    Returns the inserted row id. Caller controls the transaction boundary.
    """
    async with conn.transaction():
        # SET LOCAL ROLE: restrict to insert-only for this transaction.
        await conn.execute("SET LOCAL ROLE hlh_audit_writer")
        head = await conn.fetchrow(
            "SELECT last_hash FROM audit_log_chain_head WHERE id = 1 FOR UPDATE"
        )
        if head is None:
            raise RuntimeError("audit_log_chain_head singleton row missing — schema not applied")
        prev_hash = head["last_hash"]
        ts = rec.ts or datetime.now(timezone.utc)
        ts_iso = ts.isoformat()
        row_hash = _compute_row_hash(prev_hash, rec, ts_iso)
        row = await conn.fetchrow(
            """
            INSERT INTO audit_log
              (ts, request_id, actor, action, target_type, target_id,
               status_code, payload_hash, prev_hash, row_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            ts, rec.request_id, rec.actor, rec.action, rec.target_type,
            rec.target_id, rec.status_code, rec.payload_hash, prev_hash, row_hash,
        )
        await conn.execute(
            "UPDATE audit_log_chain_head SET last_hash = $1 WHERE id = 1",
            row_hash,
        )
        return row["id"]


def verify_chain(
    rows: list[asyncpg.Record],
    expected_first_prev: bytes = b"\x00" * 32,
) -> tuple[bool, Optional[int]]:
    """Recompute the hash chain from a list of rows ordered by id ASC.

    `expected_first_prev` is what the FIRST row's prev_hash should be.
    Default (32 zero bytes) is the genesis state. After a retention prune,
    pass the new anchor value (the prev_hash recorded for the new oldest
    row at prune time, stored in audit_log_chain_head.first_anchor_hash).

    Returns (ok, first_bad_row_id). If ok is True, first_bad_row_id is None.
    Used by the verify script and (in Task C) the doctor check.
    """
    expected_prev = expected_first_prev
    for row in rows:
        # The genesis row has prev_hash == 32 zero bytes; non-genesis rows
        # have prev_hash == previous row's row_hash. After a prune, the first
        # remaining row's prev_hash is the row_hash of the deleted predecessor
        # — supplied to this function as expected_first_prev.
        if bytes(row["prev_hash"]) != expected_prev:
            return False, row["id"]
        ts_iso = row["ts"].isoformat()
        rec = AuditRecord(
            request_id=row["request_id"],
            actor=row["actor"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            status_code=row["status_code"],
            payload_hash=bytes(row["payload_hash"]),
            ts=row["ts"],
        )
        recomputed = _compute_row_hash(bytes(row["prev_hash"]), rec, ts_iso)
        if recomputed != bytes(row["row_hash"]):
            return False, row["id"]
        expected_prev = bytes(row["row_hash"])
    return True, None


import contextlib
import os
from typing import AsyncIterator

from fastapi import Request

from db import get_pool

# Per-request principal placeholder until real auth lands.
# For now: actor is always "owner" (matches deps.py stub).
_DEFAULT_ACTOR = "owner"


class AuditEventHandle:
    """Captures request_id, action, target during endpoint handling.
    Inserted on async-context exit with the final status_code."""

    def __init__(self, request: Request):
        self._request = request
        self._target_type: Optional[str] = None
        self._target_id: Optional[str] = None
        self._committed = False

    @property
    def request_id(self):
        return self._request.state.request_id

    @contextlib.asynccontextmanager
    async def targeting(self, target_type: str, target_id) -> AsyncIterator[None]:
        """Inside the endpoint: set the target before doing work."""
        self._target_type = target_type
        self._target_id = str(target_id) if target_id is not None else None
        yield

    async def commit(self, status_code: int, body_bytes: bytes) -> None:
        """Insert one audit row. Called by the dependency teardown."""
        if self._committed:
            return
        self._committed = True
        actor = _DEFAULT_ACTOR  # owner UUID default; session username not yet passed into audit handle
        route = self._request.scope.get("route")
        if route is not None:
            action = f"{self._request.method} {route.path}"
        else:
            action = f"{self._request.method} {self._request.url.path}"
        payload_hash = hashlib.sha256(body_bytes).digest()
        rec = AuditRecord(
            request_id=self._request.state.request_id,
            actor=actor,
            action=action,
            target_type=self._target_type,
            target_id=self._target_id,
            status_code=status_code,
            payload_hash=payload_hash,
        )
        pool = await get_pool()
        async with pool.acquire() as conn:
            await insert_audit_event(conn, rec)


async def audit_event(request: Request) -> AsyncIterator[AuditEventHandle]:
    """FastAPI dependency. Yields a handle; commits the audit row after the
    response is sent.

    Usage:
        @router.post("/api/chats/{chat_id}/messages")
        async def post_msg(..., audit: AuditEventHandle = Depends(audit_event)):
            async with audit.targeting("chat", chat_id):
                ...

    Body capture: raw request body bytes are hashed (no redaction in v0.11.0;
    C3 / v0.12.0 will add the scrubber).
    """
    handle = AuditEventHandle(request)
    # Capture the raw body for payload hashing. For multipart/form-data (file
    # uploads), the stream is already consumed by FastAPI's file parser — fall
    # back to an empty hash rather than crashing the request.
    try:
        body_bytes = await request.body()
    except RuntimeError:
        body_bytes = b""
    yield handle
    # After endpoint returns, we don't have the response status here directly
    # via dependency yield. Use a middleware to set request.state.status_code
    # then commit from middleware on response. See request_id_middleware below.
    # For yield-based deps, post-yield code runs AFTER response is built.
    status_code = getattr(request.state, "response_status_code", 0)
    try:
        await handle.commit(status_code, body_bytes)
    except Exception as e:
        import logging
        logging.getLogger("audit").error("audit insert failed: %s: %s", type(e).__name__, e)


import json as _json

from services.hooks import register as _register_hook


async def _audit_on_tool_execution(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    ctx: "HookContext",
    duration_ms: float,
) -> None:
    """Post-tool-execution callback: write an audit record for the
    tool invocation."""
    if not ctx or not ctx.request_id:
        return
    _pool = await get_pool()
    payload = _json.dumps({
        "tool": tool_name,
        "duration_ms": duration_ms,
        "input_keys": list(tool_input.keys()),
    })
    rec = AuditRecord(
        request_id=uuid.UUID(ctx.request_id) if ctx.request_id else uuid.uuid4(),
        actor=ctx.user_id or "system",
        action=f"tool.{tool_name}",
        target_type="chat",
        target_id=ctx.chat_id,
        status_code=200,
        payload_hash=hashlib.sha256(payload.encode("utf-8")).digest(),
    )
    async with _pool.acquire() as _conn:
        try:
            await insert_audit_event(_conn, rec)
        except Exception:
            import logging as _logging
            _logging.getLogger("audit").exception("hook audit post_tool_execution failed")


async def _audit_on_stop(
    reason: str,
    ctx: "HookContext",
) -> None:
    """On-stop callback: record the stop event in the audit log."""
    if not ctx or not ctx.chat_id:
        return
    _pool = await get_pool()
    payload = _json.dumps({"reason": reason})
    rec = AuditRecord(
        request_id=uuid.uuid4(),
        actor=ctx.user_id or "system",
        action="chat.stop",
        target_type="chat",
        target_id=ctx.chat_id,
        status_code=200,
        payload_hash=hashlib.sha256(payload.encode("utf-8")).digest(),
    )
    async with _pool.acquire() as _conn:
        try:
            await insert_audit_event(_conn, rec)
        except Exception:
            import logging as _logging
            _logging.getLogger("audit").exception("hook audit on_stop failed")


# Register the callbacks at module import time.
_register_hook("post_tool_execution", _audit_on_tool_execution)
_register_hook("on_stop", _audit_on_stop)
