"""tmux session wrappers + in-memory client registry.

All tmux invocations run as sync ``subprocess.run([...])`` wrapped via
``loop.run_in_executor``. This is the pattern documented in CLAUDE.md —
asyncio's subprocess-exec constructor is refused by the Claude-Code
security hook, and list-arg ``subprocess.run`` is the documented
workaround. List form is shell-safe so there's no injection surface.

The client registry is a counter, not a fanout queue: each WS handler
runs its own ``pty.fork()`` + ``tmux attach``, so tmux fans I/O at the
session layer (N browsers = N tmux clients sharing one tmux session).
Python tracks which connections are attached so we can report
``device_count`` to the UI and flip ``last_detached_at`` when the last
one leaves.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import uuid
from collections import defaultdict, deque
from typing import Iterable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


SHARED_TMUX_SOCKET = "/shared/tmux/default"
TMUX_SESSION_PREFIX = "boo-"
CAPTURE_PANE_LINES = 2000
PASTE_RATE_LIMIT_PER_MINUTE = 30
PASTE_MAX_BYTES = 64 * 1024


class TmuxCommandError(RuntimeError):
    """Raised when a tmux subprocess call fails and the caller cares."""


def _tmux(args: list[str]) -> list[str]:
    return ["tmux", "-S", SHARED_TMUX_SOCKET, *args]


def _run_sync(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        timeout=15,
    )


async def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run_sync(cmd, check=check))


def tmux_name_for(session_id: uuid.UUID | str) -> str:
    return f"{TMUX_SESSION_PREFIX}{session_id}"


async def spawn(
    tmux_name: str,
    target_cmd: list[str],
    cwd: str | None = None,
) -> None:
    """``tmux new-session -A -d -s NAME [-c CWD] -- <target_cmd...>``.

    ``-A`` attaches to an existing session with the same name instead of
    erroring — harmless for us because ``tmux_name`` is keyed off the
    session UUID and already unique. ``-d`` keeps it detached (we
    don't attach as part of spawn; WS clients will attach separately).
    """
    if not target_cmd:
        raise ValueError("target_cmd must be non-empty")
    args = ["new-session", "-A", "-d", "-s", tmux_name]
    if cwd:
        args += ["-c", cwd]
    args += target_cmd
    try:
        await _run(_tmux(args))
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        logger.warning("tmux spawn failed name=%s stderr=%s", tmux_name, stderr[:500])
        raise TmuxCommandError(f"tmux spawn failed: {stderr[:500]}") from e


async def kill(tmux_name: str) -> None:
    """``tmux kill-session -t NAME`` — swallows "no such session"."""
    try:
        await _run(_tmux(["kill-session", "-t", tmux_name]), check=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        if "can't find session" in stderr.lower() or "no server running" in stderr.lower():
            return
        logger.warning("tmux kill failed name=%s stderr=%s", tmux_name, stderr[:200])


async def list_active() -> set[str]:
    """Set of ``boo-…`` session names currently alive on the shared socket."""
    try:
        proc = await _run(_tmux(["list-sessions", "-F", "#{session_name}"]), check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("tmux list_active failed: %s", e)
        return set()
    if proc.returncode != 0:
        # Empty server ("no server running") is normal on a fresh agent start.
        return set()
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    names = {line.strip() for line in out.splitlines() if line.strip()}
    return {n for n in names if n.startswith(TMUX_SESSION_PREFIX)}


async def send_keys(tmux_name: str, text: str, append_newline: bool) -> None:
    """Bracketed paste via tmux's paste buffer, then optional Enter.

    Sequence:
      1. ``load-buffer -b <buf> -`` reads text from stdin into a named buffer
      2. ``paste-buffer -t NAME -b <buf> -d -p`` pastes with bracketed markers
         (``-p``) and deletes the buffer afterward (``-d``)
      3. optional ``send-keys ... Enter`` to fire

    Why bracketed: agent TUIs (claude, opencode) honor bracketed paste — the
    TUI recognizes the wrapper and treats the payload as a single atomic
    pre-submit input. send-keys -l sends bytes "as if typed", so embedded
    \\n bytes fire mid-paste as submits, fragmenting multi-line snippets.
    Bash ignores the markers; behavior unchanged for bash sessions.

    The buffer name is per-session so concurrent pastes from different
    terminals never share a buffer. If paste-buffer fails (e.g., the
    target session died between load and paste), we explicitly delete the
    leaked buffer because ``-d`` only runs on a successful paste.
    """
    if text:
        loop = asyncio.get_running_loop()
        text_bytes = text.encode("utf-8")
        buf_name = f"boo-paste-{tmux_name}"
        # Step 1: load-buffer reads from stdin. _run can't pipe stdin, so
        # call subprocess.run directly through run_in_executor.
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                _tmux(["load-buffer", "-b", buf_name, "-"]),
                input=text_bytes,
                check=True,
                capture_output=True,
                timeout=15,
            ),
        )
        # Step 2: paste with bracketed markers (-p), delete buffer after (-d).
        # On failure (e.g., target session vanished) `-d` does NOT fire and
        # the buffer leaks on the shared socket; explicitly clean it up.
        try:
            await _run(_tmux([
                "paste-buffer", "-t", tmux_name, "-b", buf_name, "-d", "-p",
            ]))
        except Exception:
            try:
                await _run(_tmux(["delete-buffer", "-b", buf_name]), check=False)
            except Exception:
                logger.warning(
                    "send_keys paste failed and buffer cleanup also failed name=%s",
                    buf_name,
                )
            raise
    if append_newline:
        await _run(_tmux(["send-keys", "-t", tmux_name, "Enter"]))


async def capture_pane(tmux_name: str, lines: int = CAPTURE_PANE_LINES) -> bytes:
    """``capture-pane -p -e -S -<lines>`` — ``-e`` preserves escape sequences
    so terminal colors/position survive the replay.

    Returns an empty ``bytes`` on failure (missing session, agent down); the
    WS handler still sends an init frame and live stream, so an empty
    replay is non-fatal.
    """
    try:
        proc = await _run(
            _tmux(["capture-pane", "-t", tmux_name, "-p", "-e", "-S", f"-{int(lines)}"]),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("tmux capture_pane failed name=%s err=%s", tmux_name, e)
        return b""
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        logger.warning("tmux capture_pane rc=%d name=%s stderr=%s", proc.returncode, tmux_name, stderr[:200])
        return b""
    return proc.stdout or b""


# In-memory client registry — connection IDs per session.
_pty_subscribers: dict[str, set[uuid.UUID]] = defaultdict(set)

# Sliding-window paste rate limiter — per-session monotonic timestamps.
_paste_window: dict[str, deque[float]] = defaultdict(deque)


def attach(session_id: str, conn_id: uuid.UUID) -> None:
    _pty_subscribers[session_id].add(conn_id)


def detach(session_id: str, conn_id: uuid.UUID) -> None:
    conns = _pty_subscribers.get(session_id)
    if conns is not None:
        conns.discard(conn_id)
        if not conns:
            _pty_subscribers.pop(session_id, None)


def device_count(session_id: str) -> int:
    return len(_pty_subscribers.get(session_id, ()))


def device_counts_for(session_ids: Iterable[str]) -> dict[str, int]:
    return {sid: device_count(sid) for sid in session_ids}


def check_paste_rate(session_id: str, *, now: float | None = None) -> bool:
    """Return True if paste is allowed, False if rate-limited.

    Sliding window of ``PASTE_RATE_LIMIT_PER_MINUTE`` pastes per session
    per 60s. Drops stale stamps on every call so the deque can't grow
    unbounded.
    """
    stamp = time.monotonic() if now is None else now
    dq = _paste_window[session_id]
    cutoff = stamp - 60.0
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= PASTE_RATE_LIMIT_PER_MINUTE:
        return False
    dq.append(stamp)
    return True


def reset_paste_rate(session_id: str) -> None:
    _paste_window.pop(session_id, None)


def target_cmd_for(
    machine: dict,
    session_type: str,
    cwd: str,
) -> list[str]:
    """Build the shell argv tmux will exec for (machine, session_type, cwd).

    INVARIANT: cwd is a HOST path. It is passed verbatim to the remote shell
    via SSH. Do NOT translate, normalize, or map it through any container-
    side filesystem view. ubuntu-homelab is the host; /HomeLabRepos already
    resolves there.

    INVARIANT: bash -lc is load-bearing. -l forces a login shell on the
    host so ~/.profile is sourced, extending PATH to include ~/.local/bin
    where claude and opencode live. Do NOT drop -l.

    INVARIANT: ssh -t is required. claude and opencode are full-screen TUIs
    that refuse to start without a remote tty — `-t` forces remote pty
    allocation. Without it, the TUI exits immediately with "stdin not a tty".

    INVARIANT: StrictHostKeyChecking=yes is intentional. The agent's
    ~/.ssh is bind-mounted read-only (only id_ed25519 + known_hosts), so
    TOFU writes would silently fail. known_hosts must be pre-populated on
    the host for each Tailscale peer (currently just ubuntu-homelab).
    """
    import shlex

    if not cwd:
        raise HTTPException(status_code=400, detail="cwd is required")
    if session_type not in ("bash", "claude", "opencode"):
        raise HTTPException(
            status_code=400, detail=f"unknown session_type: {session_type}",
        )

    name = (machine.get("name") or "").strip()
    host = (machine.get("host") or "").strip()
    ssh_user = (machine.get("ssh_user") or "").strip()

    # `local` (legacy): bash inside the agent container. Non-default
    # fallback for sidecar shell access. Agents not allowed here.
    if name == "local" or not host or host == "localhost":
        if session_type != "bash":
            raise HTTPException(
                status_code=400,
                detail="claude/opencode require ubuntu-homelab (they run on the host)",
            )
        return ["bash", "-lc", f"cd {shlex.quote(cwd)} && exec bash -l"]

    # Remote via SSH (ubuntu-homelab is one such target).
    if not ssh_user:
        raise HTTPException(
            status_code=400, detail=f"machine {name!r} needs ssh_user before use",
        )
    ssh = [
        "ssh", "-t",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        f"{ssh_user}@{host}",
    ]
    if session_type == "bash":
        remote = f"cd {shlex.quote(cwd)} && exec bash -l"
    else:  # claude | opencode
        remote = f"cd {shlex.quote(cwd)} && exec {session_type}"
    return ssh + ["bash", "-lc", remote]
