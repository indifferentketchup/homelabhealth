"""Terminals: CRUD over terminal_sessions + /ws/terminals/:id PTY bridge.

Auth: Authelia forward_auth on the vhost gates every request. Owner is the
only principal in Phase 5. TODO(auth): add a require_owner dependency once
member-tier lands — do it once here, not per-route.

Concurrency: each WS runs its own pty.fork() + ``tmux attach``, joining
the existing tmux session as an additional client. tmux fans I/O at the
session layer (N browsers = N tmux clients sharing one tmux session).
Python only tracks device_count.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import signal
import struct
import termios
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from auth_deps import get_principal
from db import get_pool
from routers.chats import _openai_short_chat_title
from services import tmux_session
from services.terminal_sweep import lru_evict_if_needed


logger = logging.getLogger(__name__)

router = APIRouter()
ws_router = APIRouter()

DEFAULT_COLS = 80
DEFAULT_ROWS = 24
MAX_UNPINNED_ACTIVE = 10
MAX_PINNED_ACTIVE = 5


# ── pydantic models ──────────────────────────────────────────────────────────


class MachineOut(BaseModel):
    id: str
    name: str
    host: str
    ssh_user: str | None
    default_cwd: str | None
    enabled: bool


class SessionOut(BaseModel):
    id: str
    daw_id: str | None
    machine_id: str
    machine_name: str
    tmux_name: str
    label: str | None
    starting_cmd: str | None
    pinned: bool
    created_at: str
    last_detached_at: str | None
    closed_at: str | None
    device_count: int


class CreateSessionBody(BaseModel):
    machine_id: uuid.UUID
    daw_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=120)
    starting_cmd: str | None = Field(default=None, max_length=4096)
    cwd: str | None = Field(default=None, max_length=512)


def _validate_cwd(cwd: str | None) -> str | None:
    """Light sanity check on a caller-supplied tmux cwd. Owner-only auth
    already gates the route; this is defense-in-depth against a stray
    `..` or embedded null that would confuse tmux."""
    if cwd is None:
        return None
    trimmed = cwd.strip()
    if not trimmed:
        return None
    if "\x00" in trimmed:
        raise HTTPException(status_code=400, detail="cwd contains null byte")
    if not trimmed.startswith("/"):
        raise HTTPException(status_code=400, detail="cwd must be absolute")
    if ".." in trimmed.split("/"):
        raise HTTPException(status_code=400, detail="cwd contains '..'")
    return trimmed


class PatchSessionBody(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class PasteBody(BaseModel):
    text: str
    append_newline: bool = False


# ── helpers ──────────────────────────────────────────────────────────────────


def _row_to_session(row: Any) -> SessionOut:
    return SessionOut(
        id=str(row["id"]),
        daw_id=str(row["daw_id"]) if row["daw_id"] else None,
        machine_id=str(row["machine_id"]),
        machine_name=row["machine_name"],
        tmux_name=row["tmux_name"],
        label=row["label"],
        starting_cmd=row["starting_cmd"],
        pinned=bool(row["pinned"]),
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        last_detached_at=(
            row["last_detached_at"].isoformat() if row["last_detached_at"] else None
        ),
        closed_at=row["closed_at"].isoformat() if row["closed_at"] else None,
        device_count=tmux_session.device_count(str(row["id"])),
    )


async def _audit(
    conn: Any,
    session_id: uuid.UUID | str | None,
    event: str,
    *,
    client_ip: str | None = None,
    ua: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO terminal_audit (session_id, event, client_ip, ua, extra)
            VALUES ($1, $2, $3, $4, $5)
            """,
            uuid.UUID(str(session_id)) if session_id else None,
            event,
            client_ip,
            ua,
            json.dumps(extra) if extra else None,
        )
    except Exception as e:
        logger.warning("terminal_audit insert failed event=%s err=%s", event, e)


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    xf = request.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    return request.client.host if request.client else None


def _ua(request: Request | None) -> str | None:
    if request is None:
        return None
    return request.headers.get("user-agent")


def _ws_client_ip(ws: WebSocket) -> str | None:
    xf = ws.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    return ws.client.host if ws.client else None


def _ws_ua(ws: WebSocket) -> str | None:
    return ws.headers.get("user-agent")


# ── REST endpoints ───────────────────────────────────────────────────────────


@router.get("/machines", response_model=list[MachineOut])
# TODO(auth): add require_owner once member-tier lands.
async def list_machines() -> list[MachineOut]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, host, ssh_user, default_cwd, enabled
            FROM terminal_machines
            WHERE enabled = TRUE
            ORDER BY name
            """
        )
    return [
        MachineOut(
            id=str(r["id"]),
            name=r["name"],
            host=r["host"],
            ssh_user=r["ssh_user"],
            default_cwd=r["default_cwd"],
            enabled=bool(r["enabled"]),
        )
        for r in rows
    ]


@router.get("")
# TODO(auth): add require_owner once member-tier lands.
async def list_sessions(
    daw_id: uuid.UUID | None = Query(None),
) -> dict[str, list[SessionOut]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Active sessions, scoped to a DAW if provided (or daw_id IS NULL when
        # caller omits it — "unscoped" sessions).
        if daw_id is not None:
            active_rows = await conn.fetch(
                """
                SELECT ts.*, tm.name AS machine_name
                FROM terminal_sessions ts
                JOIN terminal_machines tm ON tm.id = ts.machine_id
                WHERE ts.closed_at IS NULL AND ts.daw_id = $1::uuid
                ORDER BY ts.created_at ASC
                """,
                daw_id,
            )
            recent_rows = await conn.fetch(
                """
                SELECT ts.*, tm.name AS machine_name
                FROM terminal_sessions ts
                JOIN terminal_machines tm ON tm.id = ts.machine_id
                WHERE ts.closed_at IS NOT NULL
                  AND ts.closed_at > NOW() - INTERVAL '48 hours'
                  AND ts.daw_id = $1::uuid
                ORDER BY ts.closed_at DESC
                LIMIT 20
                """,
                daw_id,
            )
        else:
            active_rows = await conn.fetch(
                """
                SELECT ts.*, tm.name AS machine_name
                FROM terminal_sessions ts
                JOIN terminal_machines tm ON tm.id = ts.machine_id
                WHERE ts.closed_at IS NULL
                ORDER BY ts.created_at ASC
                """
            )
            recent_rows = await conn.fetch(
                """
                SELECT ts.*, tm.name AS machine_name
                FROM terminal_sessions ts
                JOIN terminal_machines tm ON tm.id = ts.machine_id
                WHERE ts.closed_at IS NOT NULL
                  AND ts.closed_at > NOW() - INTERVAL '48 hours'
                ORDER BY ts.closed_at DESC
                LIMIT 20
                """
            )
    return {
        "active": [_row_to_session(r) for r in active_rows],
        "recent": [_row_to_session(r) for r in recent_rows],
    }


@router.post("", response_model=SessionOut)
# TODO(auth): add require_owner once member-tier lands.
async def create_session(body: CreateSessionBody, request: Request) -> SessionOut:
    pool = await get_pool()
    async with pool.acquire() as conn:
        machine = await conn.fetchrow(
            """
            SELECT id, name, host, ssh_user, default_cwd, enabled
            FROM terminal_machines
            WHERE id = $1::uuid
            """,
            body.machine_id,
        )
        if machine is None:
            raise HTTPException(status_code=404, detail="machine not found")
        if not machine["enabled"]:
            raise HTTPException(status_code=400, detail="machine is disabled")

        # Cap enforcement: LRU-evict the oldest detached unpinned session if
        # we're at the unpinned cap; 409 if nothing is evictable (everything
        # is pinned or still has attached clients).
        if not await lru_evict_if_needed(conn):
            raise HTTPException(status_code=409, detail="unpinned cap reached")
        active_pinned = await conn.fetchval(
            "SELECT COUNT(*) FROM terminal_sessions WHERE closed_at IS NULL AND pinned = TRUE",
        )
        if active_pinned and active_pinned > MAX_PINNED_ACTIVE:
            # Defensive; PATCH enforces the same cap on pin transitions.
            raise HTTPException(status_code=409, detail="pinned cap reached")

        sid = uuid.uuid4()
        tmux_name = tmux_session.tmux_name_for(sid)

        try:
            target_cmd = tmux_session.target_cmd_for(dict(machine))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Optional starting command prefix (strip newlines to avoid
        # accidentally firing before the shell is ready).
        starting_cmd = (body.starting_cmd or "").strip() or None

        cwd = _validate_cwd(body.cwd) or machine["default_cwd"]
        try:
            await tmux_session.spawn(tmux_name, target_cmd, cwd)
        except tmux_session.TmuxCommandError as e:
            raise HTTPException(status_code=500, detail=f"tmux spawn failed: {e}")

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO terminal_sessions (
                    id, daw_id, machine_id, tmux_name, label, starting_cmd
                )
                VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6)
                RETURNING id, daw_id, machine_id, tmux_name, label, starting_cmd,
                          pinned, created_at, last_detached_at, closed_at
                """,
                sid,
                body.daw_id,
                body.machine_id,
                tmux_name,
                body.label,
                starting_cmd,
            )
        except Exception:
            # Roll back the tmux session if the DB insert fails so we don't
            # leave an orphan on the agent.
            await tmux_session.kill(tmux_name)
            raise

        if starting_cmd:
            try:
                await tmux_session.send_keys(tmux_name, starting_cmd, True)
            except Exception as e:
                logger.warning("starting_cmd send failed sid=%s err=%s", sid, e)

        await _audit(
            conn,
            sid,
            "open",
            client_ip=_client_ip(request),
            ua=_ua(request),
            extra={"machine": machine["name"], "label": body.label},
        )

    row_d = dict(row)
    row_d["machine_name"] = machine["name"]
    return _row_to_session(row_d)


@router.patch("/{sid}", response_model=SessionOut)
# TODO(auth): add require_owner once member-tier lands.
async def patch_session(
    sid: uuid.UUID,
    body: PatchSessionBody,
    request: Request,
) -> SessionOut:
    data = body.model_dump(exclude_unset=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            """
            SELECT ts.*, tm.name AS machine_name
            FROM terminal_sessions ts
            JOIN terminal_machines tm ON tm.id = ts.machine_id
            WHERE ts.id = $1::uuid
            """,
            sid,
        )
        if current is None or current["closed_at"] is not None:
            raise HTTPException(status_code=404, detail="session not found")

        new_label = data.get("label", current["label"])
        new_pinned = data.get("pinned", current["pinned"])

        if new_pinned and not current["pinned"]:
            # Pin-cap check: reject if pinning this would push count over 5.
            pinned_count = await conn.fetchval(
                "SELECT COUNT(*) FROM terminal_sessions WHERE closed_at IS NULL AND pinned = TRUE",
            )
            if pinned_count and pinned_count >= MAX_PINNED_ACTIVE:
                raise HTTPException(status_code=409, detail="pinned cap reached")

        row = await conn.fetchrow(
            """
            UPDATE terminal_sessions
            SET label = $2, pinned = $3
            WHERE id = $1::uuid
            RETURNING id, daw_id, machine_id, tmux_name, label, starting_cmd,
                      pinned, created_at, last_detached_at, closed_at
            """,
            sid,
            new_label,
            new_pinned,
        )
        events = []
        if new_label != current["label"]:
            events.append(("rename", {"label": new_label}))
        if new_pinned != current["pinned"]:
            events.append(("pin", {"pinned": bool(new_pinned)}))
        for event, extra in events:
            await _audit(
                conn, sid, event,
                client_ip=_client_ip(request), ua=_ua(request), extra=extra,
            )

    row_d = dict(row)
    row_d["machine_name"] = current["machine_name"]
    return _row_to_session(row_d)


@router.delete("/{sid}")
# TODO(auth): add require_owner once member-tier lands.
async def delete_session(sid: uuid.UUID, request: Request) -> dict[str, bool]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, tmux_name, closed_at FROM terminal_sessions WHERE id = $1::uuid",
            sid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if row["closed_at"] is not None:
            return {"ok": True}

        await tmux_session.kill(row["tmux_name"])
        await conn.execute(
            "UPDATE terminal_sessions SET closed_at = NOW() WHERE id = $1::uuid",
            sid,
        )
        await _audit(
            conn, sid, "close",
            client_ip=_client_ip(request), ua=_ua(request),
        )
    tmux_session.reset_paste_rate(str(sid))
    return {"ok": True}


@router.post("/{sid}/paste")
# TODO(auth): add require_owner once member-tier lands.
async def paste(sid: uuid.UUID, body: PasteBody, request: Request) -> dict[str, Any]:
    if not tmux_session.check_paste_rate(str(sid)):
        raise HTTPException(status_code=429, detail="paste rate limit")

    text = body.text or ""
    if len(text.encode("utf-8", errors="replace")) > tmux_session.PASTE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="paste too large")

    # Strip literal newlines when the caller did not opt into firing commands.
    # The outer Enter (append_newline=True) is what actually fires; stripping
    # here prevents a rogue inline \n from firing mid-payload.
    if not body.append_newline:
        text = text.replace("\n", "").replace("\r", "")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tmux_name, closed_at FROM terminal_sessions WHERE id = $1::uuid",
            sid,
        )
        if row is None or row["closed_at"] is not None:
            raise HTTPException(status_code=404, detail="session not found")

        try:
            await tmux_session.send_keys(row["tmux_name"], text, body.append_newline)
        except Exception as e:
            logger.warning("paste send_keys failed sid=%s err=%s", sid, e)
            raise HTTPException(status_code=500, detail="paste failed")

        await _audit(
            conn, sid, "paste",
            client_ip=_client_ip(request),
            ua=_ua(request),
            extra={
                "len": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                "append_newline": bool(body.append_newline),
            },
        )
    return {"ok": True, "len": len(text)}


@router.post("/{sid}/export")
async def export_terminal(
    sid: uuid.UUID,
    request: Request,
    principal: dict[str, Any] = Depends(get_principal),
) -> dict:
    """Capture tmux pane output and write to /data/history/terminals/<daw-slug>/<file>.txt.

    Requires the session to have a daw_id and must not be closed (closed sessions
    have no tmux pane to capture).
    """
    from services.history import daw_dir, slugify
    from services.history_writer import render_terminal_plaintext, timestamp_slug

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, daw_id, tmux_name, label, machine_id, closed_at
            FROM terminal_sessions
            WHERE id=$1::uuid
            """,
            sid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if row["closed_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail="session is closed and cannot be captured",
            )
        if row["daw_id"] is None:
            raise HTTPException(status_code=400, detail="terminal must be in a DAW to export")

        daw_row = await conn.fetchrow(
            "SELECT name FROM daws WHERE id=$1::uuid",
            row["daw_id"],
        )
        if daw_row is None:
            raise HTTPException(status_code=400, detail="DAW not found")

        machine_row = await conn.fetchrow(
            "SELECT name FROM terminal_machines WHERE id=$1::uuid",
            row["machine_id"],
        )

    daw_name: str = daw_row["name"]
    machine_name: str = machine_row["name"] if machine_row else "unknown"
    label: str = row["label"] or str(sid)
    tmux_name: str = row["tmux_name"]

    raw = await tmux_session.capture_pane(tmux_name, lines=10000)
    if not raw:
        logger.warning(
            "export_terminal empty capture sid=%s tmux_name=%s", str(sid), tmux_name
        )
        raise HTTPException(
            status_code=400,
            detail="Cannot capture a closed or missing tmux session.",
        )

    content = render_terminal_plaintext(label, machine_name, raw)

    ts = timestamp_slug()
    initial_filename = f"{ts}.txt"
    target_dir = daw_dir("terminals", daw_name)
    file_path = target_dir / initial_filename
    file_path.write_text(content, encoding="utf-8")

    # AI rename: use the tail of the captured text as a prompt.
    ai_renamed = False
    stripped_text = content  # already stripped by render_terminal_plaintext
    tail = stripped_text[-500:].strip() if len(stripped_text) > 500 else stripped_text.strip()
    default_model = os.environ.get("DEFAULT_MODEL", "llama-gpu/qwen3.5-9b-exl3")
    if tail:
        try:
            ai_title = await _openai_short_chat_title(
                model=default_model,
                user_message_text=tail,
            )
            if ai_title:
                slug = slugify(ai_title, max_len=60)
                candidate = f"{slug}-{ts}.txt"
                candidate_path = target_dir / candidate
                nonce = 1
                while candidate_path.exists():
                    if nonce > 50:
                        raise HTTPException(status_code=500, detail="export collision loop")
                    candidate = f"{slug}-{ts}-{nonce:03d}.txt"
                    candidate_path = target_dir / candidate
                    nonce += 1
                file_path.rename(candidate_path)
                file_path = candidate_path
                ai_renamed = True
        except Exception as exc:
            logger.warning(
                "export_terminal ai_rename failed sid=%s err=%s", str(sid), exc
            )

    logger.info(
        "export_terminal sid=%s daw=%s file=%s ai_renamed=%s",
        str(sid), daw_name, file_path.name, ai_renamed,
    )
    return {
        "filename": file_path.name,
        "daw_slug": slugify(daw_name),
        "path": str(file_path),
        "ai_renamed": ai_renamed,
    }


# ── WebSocket ────────────────────────────────────────────────────────────────


def _spawn_pty_tmux_client(
    tmux_name: str,
    cols: int = DEFAULT_COLS,
    rows: int = DEFAULT_ROWS,
) -> tuple[int, int]:
    """openpty + fork + exec tmux attach. Returns (pid, master_fd).

    Why not ``pty.fork()``: pty.fork() returns with the slave already
    wired to the child but the winsize is kernel-default (0x0 on Linux).
    The parent can't ``TIOCSWINSZ`` in time — tmux attach reads winsize
    before the ioctl lands and exits with EIO. Doing the openpty +
    ioctl on the slave *before* fork avoids the race entirely.

    TERM must be set in the child: tmux refuses to attach on a `dumb`
    or unset TERM. Inherited env from boolab_api has no TERM.
    """
    master_fd, slave_fd = os.openpty()
    _set_winsize(slave_fd, cols, rows)

    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.close(master_fd)
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", [
                "tmux", "-S", tmux_session.SHARED_TMUX_SOCKET,
                "attach", "-t", tmux_name,
            ])
        except OSError:
            os._exit(127)
    os.close(slave_fd)
    return pid, master_fd


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    size = struct.pack("HHHH", int(rows), int(cols), 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except OSError as e:
        logger.warning("TIOCSWINSZ failed rows=%s cols=%s err=%s", rows, cols, e)


async def _reap_child(pid: int) -> None:
    """Best-effort child reap; we don't want zombie processes hanging around."""
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    loop = asyncio.get_running_loop()
    for _ in range(40):  # ~2s total
        try:
            p, _ = await loop.run_in_executor(None, lambda: os.waitpid(pid, os.WNOHANG))
        except ChildProcessError:
            return
        if p != 0:
            return
        await asyncio.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await loop.run_in_executor(None, lambda: os.waitpid(pid, 0))
    except ChildProcessError:
        pass


@ws_router.websocket("/ws/terminals/{sid}")
# TODO(auth): add require_owner once member-tier lands.
async def ws_terminal(ws: WebSocket, sid: uuid.UUID) -> None:
    await ws.accept()

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, tmux_name, closed_at FROM terminal_sessions WHERE id = $1::uuid",
            sid,
        )
    if row is None or row["closed_at"] is not None:
        await ws.close(code=4004, reason="session not found")
        return
    tmux_name = row["tmux_name"]

    try:
        pid, master_fd = _spawn_pty_tmux_client(tmux_name)
    except OSError as e:
        logger.warning("pty.fork failed sid=%s err=%s", sid, e)
        await ws.close(code=1011, reason="pty fork failed")
        return

    _set_nonblocking(master_fd)
    _set_winsize(master_fd, DEFAULT_COLS, DEFAULT_ROWS)

    # Queue drains PTY reads. Nothing consumes it during steps 1-3 of the
    # ordering contract, so live bytes accumulate until we explicitly flush
    # them after the init + capture frames are on the wire.
    pty_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _pty_ready() -> None:
        try:
            data = os.read(master_fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            pty_queue.put_nowait(None)
            return
        if not data:
            pty_queue.put_nowait(None)
            return
        pty_queue.put_nowait(data)

    loop.add_reader(master_fd, _pty_ready)

    conn_id = uuid.uuid4()
    tmux_session.attach(str(sid), conn_id)

    async with pool.acquire() as c:
        await c.execute(
            "UPDATE terminal_sessions SET last_detached_at = NULL WHERE id = $1::uuid",
            sid,
        )
        await _audit(
            c, sid, "device_connect",
            client_ip=_ws_client_ip(ws), ua=_ws_ua(ws),
        )

    try:
        # Step 3.a: init control frame.
        await ws.send_text(json.dumps({
            "type": "init",
            "cols": DEFAULT_COLS,
            "rows": DEFAULT_ROWS,
            "tmux_name": tmux_name,
        }))

        # Step 2: capture-pane (separate subprocess, not on the PTY).
        capture_bytes = await tmux_session.capture_pane(tmux_name)

        # Step 3.b: capture bytes as a single binary frame.
        if capture_bytes:
            await ws.send_bytes(capture_bytes)

        # Step 3.c: flush everything buffered in the queue so far.
        # Use a non-blocking drain so we don't stall for live bytes.
        while True:
            try:
                item = pty_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is None:
                return
            await ws.send_bytes(item)

        # Step 4: live forward + receive user input, concurrently.
        async def forward_pty() -> None:
            while True:
                item = await pty_queue.get()
                if item is None:
                    return
                try:
                    await ws.send_bytes(item)
                except Exception:
                    return

        async def receive_user() -> None:
            while True:
                try:
                    msg = await ws.receive()
                except WebSocketDisconnect:
                    return
                if msg["type"] == "websocket.disconnect":
                    return
                if "bytes" in msg and msg["bytes"] is not None:
                    data = msg["bytes"]
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        return
                    continue
                if "text" in msg and msg["text"] is not None:
                    try:
                        obj = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "resize":
                        _set_winsize(
                            master_fd,
                            int(obj.get("cols") or DEFAULT_COLS),
                            int(obj.get("rows") or DEFAULT_ROWS),
                        )

        fwd_task = asyncio.create_task(forward_pty())
        recv_task = asyncio.create_task(receive_user())
        done, pending = await asyncio.wait(
            [fwd_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("ws_terminal error sid=%s err=%s", sid, e)
    finally:
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        await _reap_child(pid)

        tmux_session.detach(str(sid), conn_id)
        async with pool.acquire() as c:
            await _audit(
                c, sid, "device_disconnect",
                client_ip=_ws_client_ip(ws), ua=_ws_ua(ws),
            )
            if tmux_session.device_count(str(sid)) == 0:
                await c.execute(
                    "UPDATE terminal_sessions SET last_detached_at = NOW() WHERE id = $1::uuid",
                    sid,
                )

        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
