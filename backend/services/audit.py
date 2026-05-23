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


def verify_chain(rows: list[asyncpg.Record]) -> tuple[bool, Optional[int]]:
    """Recompute the hash chain from a list of rows ordered by id ASC.

    Returns (ok, first_bad_row_id). If ok is True, first_bad_row_id is None.
    Used by the verify script and (in Task C) the doctor check.
    """
    expected_prev = b"\x00" * 32
    for row in rows:
        # The genesis row has prev_hash == 32 zero bytes; non-genesis rows
        # have prev_hash == previous row's row_hash.
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
