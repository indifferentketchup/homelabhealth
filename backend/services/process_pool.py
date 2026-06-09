"""Dynamic process pool manager for llama-server sidecars.

Manages per-model sidecar processes with health checks, LRU eviction,
port allocation, and OpenAI-compatible proxy routing.

Adapted from llama-sidecar's Go pool implementation:
    /opt/forks/llama-sidecar/internal/pool/pool.go
    /opt/forks/llama-sidecar/internal/pool/ports.go
    /opt/forks/llama-sidecar/internal/pool/sidecar.go

Public surface:
    PoolManager              — main pool class
    get_pool()               — singleton accessor
    set_pool(pm)             — set the global singleton
    proxy_chat_completion()  — convenience proxy for /v1/chat/completions

Usage:
    pm = PoolManager(max_sidecars=2)
    await pm.start()
    sidecar = await pm.acquire("medgemma", model_path="/models/medgemma.gguf")
    # use sidecar.base_url for inference
    await pm.shutdown()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MAX_SIDECARS = 2
_DEFAULT_PORT_LO = 9000
_DEFAULT_PORT_HI = 9099
_DEFAULT_HEALTH_INTERVAL_S = 30
_DEFAULT_IDLE_TIMEOUT_S = 300
_DEFAULT_HEALTH_TIMEOUT_S = 60
_DEFAULT_LLAMA_SERVER_BIN = "llama-server"

# ---------------------------------------------------------------------------
# Port allocator
# ---------------------------------------------------------------------------


class PortAllocator:
    """Manages a range of ports (lo..hi inclusive) via asyncio.Queue.

    Mirrors the Go channel-based PortAllocator in ports.go.
    """

    def __init__(self, lo: int, hi: int) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        for p in range(lo, hi + 1):
            self._queue.put_nowait(p)

    async def allocate(self) -> int:
        """Acquire the next free port. Blocks until one is available."""
        return await self._queue.get()

    def release(self, port: int) -> None:
        """Return a port to the free pool."""
        self._queue.put_nowait(port)

    @property
    def available(self) -> int:
        return self._queue.qsize()


# ---------------------------------------------------------------------------
# SidecarProcess — state for a single llama-server subprocess
# ---------------------------------------------------------------------------


@dataclass
class SidecarProcess:
    """A running llama-server sidecar process.

    Attributes mirror SidecarInfo from pool.go plus Python-specific
    async process handles.
    """

    hash_key: str
    model_id: str
    model_path: str | None
    flags: tuple[str, ...]
    port: int
    pid: int
    started_at: datetime
    last_used_ns: int  # Unix nanosecond timestamp
    healthy: bool = False
    process: asyncio.subprocess.Process | None = None

    def touch(self) -> None:
        """Update last-used timestamp (LRU ordering)."""
        self.last_used_ns = _now_ns()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def idle_seconds(self) -> float:
        """Seconds since last use."""
        return max(0.0, (_now_ns() - self.last_used_ns) / 1_000_000_000)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_ns() -> int:
    """Current time in Unix nanoseconds (int)."""
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)


def _hash_key(model_id: str, flags: tuple[str, ...]) -> str:
    """Deterministic hash of (model_id, sorted flags).

    The same hash always refers to the same running sidecar config,
    enabling process reuse across callers.
    """
    raw = f"{model_id}:{':'.join(sorted(flags))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _sse(data: str) -> bytes:
    """Format an SSE data frame (matches chats.py's _sse helper)."""
    return f"data: {data}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# PoolManager
# ---------------------------------------------------------------------------


class PoolManager:
    """Dynamic pool of llama-server sidecar processes.

    Thread-safe (asyncio.Lock). Designed as a singleton — use get_pool()
    / set_pool() for module-level access.

    Lifecycle:
        pm = PoolManager(...)
        await pm.start()
        ...
        await pm.shutdown()

    Acquire:
        sidecar = await pm.acquire("medgemma", model_path="/models/medgemma.gguf")
        # Reuses existing healthy sidecar for same (model_id, flags) hash.
        # Evicts LRU idle sidecar when at max capacity.
        # Spawns and waits for health check.

    Eviction:
        - On acquire when at capacity: evicts the LRU idle sidecar.
        - Background health loop every 30s: removes unhealthy sidecars
          and sidecars idle past `idle_timeout_s`.

    Integration:
        - Caller uses sidecar.base_url as the OpenAI-compatible endpoint.
        - proxy_chat_completion() wraps the acquire+route+touch flow.
        - Falls back to static hlh_chat URL when pool is None.
    """

    def __init__(
        self,
        *,
        max_sidecars: int = _DEFAULT_MAX_SIDECARS,
        port_lo: int = _DEFAULT_PORT_LO,
        port_hi: int = _DEFAULT_PORT_HI,
        health_interval_s: int = _DEFAULT_HEALTH_INTERVAL_S,
        idle_timeout_s: int = _DEFAULT_IDLE_TIMEOUT_S,
        health_timeout_s: int = _DEFAULT_HEALTH_TIMEOUT_S,
        llama_server_bin: str = _DEFAULT_LLAMA_SERVER_BIN,
        base_args: list[str] | None = None,
    ) -> None:
        if max_sidecars < 1:
            raise ValueError("max_sidecars must be >= 1")
        if port_lo < 1 or port_hi > 65535 or port_lo > port_hi:
            raise ValueError(f"invalid port range: {port_lo}-{port_hi}")

        self._max_sidecars = max_sidecars
        self._health_interval_s = health_interval_s
        self._idle_timeout_s = idle_timeout_s
        self._health_timeout_s = health_timeout_s
        self._llama_server_bin = llama_server_bin
        self._base_args = list(base_args) if base_args else []

        self._lock = asyncio.Lock()
        self._sidecars: dict[str, SidecarProcess] = {}
        self._lru: OrderedDict[str, SidecarProcess] = OrderedDict()
        self._ports = PortAllocator(port_lo, port_hi)
        self._health_task: asyncio.Task | None = None
        self._started = False

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    async def start(self) -> None:
        """Start background health-monitor loop.

        Idempotent — safe to call multiple times.
        """
        if self._started:
            return
        self._started = True
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info(
            "PoolManager started: max=%d ports=%d-%d health_interval=%ds idle_timeout=%ds",
            self._max_sidecars,
            self._ports.available,
            self._ports.available + self._max_sidecars - 1,  # approximate hi from qsize
            self._health_interval_s,
            self._idle_timeout_s,
        )

    async def shutdown(self) -> None:
        """Kill all sidecar processes and stop background tasks.

        Waits up to 5s per process for graceful shutdown, then SIGKILL.
        Idempotent.
        """
        if not self._started:
            return
        self._started = False

        # Stop health loop
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        # Snapshot hashes under lock, kill outside lock
        async with self._lock:
            hashes = list(self._sidecars.keys())

        tasks = [self._remove(h) for h in hashes]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("PoolManager shutdown: killed %d sidecars", len(hashes))

    # -------------------------------------------------------------------
    # Acquire
    # -------------------------------------------------------------------

    async def acquire(
        self,
        model_id: str,
        model_path: str | None = None,
        flags: tuple[str, ...] | None = None,
    ) -> SidecarProcess:
        """Get or spawn a sidecar for *model_id*.

        Returns an existing healthy sidecar if one exists for the same
        *(model_id, flags)* hash. Otherwise spawns a new one, evicting
        an idle sidecar first if at capacity.

        Args:
            model_id: Model alias (e.g. ``"medgemma"``).
            model_path: Path to the GGUF file on disk. If ``None``,
                uses *model_id* as the ``--model`` argument (router mode).
            flags: Extra CLI flags for llama-server.

        Raises:
            RuntimeError: If spawn fails or health check times out.
        """
        flags = flags or ()
        hkey = _hash_key(model_id, flags)

        async with self._lock:
            # 1. Reuse existing healthy sidecar
            s = self._sidecars.get(hkey)
            if s is not None:
                if s.healthy:
                    self._lru.move_to_end(hkey)
                    s.touch()
                    logger.debug("PoolManager: reuse hash=%s port=%d model=%s", hkey[:8], s.port, model_id)
                    return s
                else:
                    # Unhealthy — remove and re-spawn
                    logger.warning("PoolManager: unhealthy sidecar hash=%s port=%d; re-spawning", hkey[:8], s.port)
                    await self._remove_locked(hkey)
                    s = None

            # 2. Evict LRU if at capacity
            if len(self._sidecars) >= self._max_sidecars:
                victim = self._lru.popitem(last=False) if self._lru else None
                if victim:
                    vhash, _ = victim
                    logger.info("PoolManager: evicting LRU sidecar hash=%s", vhash[:8])
                    await self._remove_locked(vhash)

            # 3. Allocate port (under lock to avoid race with other acquires)
            port = await self._ports.allocate()

        # Port allocated, now spawn *outside* the lock (may take time)
        try:
            s = await self._spawn(model_id, model_path, flags, port, hkey)
        except Exception:
            self._ports.release(port)
            raise

        async with self._lock:
            self._sidecars[hkey] = s
            self._lru[hkey] = s

        logger.info(
            "PoolManager: spawned sidecar hash=%s model=%s port=%d pid=%d",
            hkey[:8], model_id, port, s.pid,
        )
        return s

    async def touch(self, hash_key: str) -> None:
        """Mark a sidecar as recently used (updates LRU order)."""
        async with self._lock:
            s = self._sidecars.get(hash_key)
            if s is not None:
                s.touch()
                if hash_key in self._lru:
                    self._lru.move_to_end(hash_key)

    # -------------------------------------------------------------------
    # Remove / evict
    # -------------------------------------------------------------------

    async def remove(self, hash_key: str) -> None:
        """Explicitly remove and kill a sidecar by hash."""
        async with self._lock:
            await self._remove_locked(hash_key)

    async def _remove(self, hash_key: str) -> None:
        """Unlocked variant — acquires lock internally."""
        async with self._lock:
            await self._remove_locked(hash_key)

    async def _remove_locked(self, hash_key: str) -> None:
        """Remove a sidecar (caller must hold *lock*).

        Releases the port and kills the process (SIGTERM → 5s → SIGKILL).
        """
        s = self._sidecars.pop(hash_key, None)
        if s is None:
            return
        self._lru.pop(hash_key, None)
        self._ports.release(s.port)

        if s.process is not None and s.process.returncode is None:
            try:
                s.process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(s.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    s.process.kill()
                    await s.process.wait()
            except ProcessLookupError:
                pass

        logger.debug("PoolManager: removed sidecar hash=%s port=%d", hash_key[:8], s.port)

    # -------------------------------------------------------------------
    # Spawn (private)
    # -------------------------------------------------------------------

    async def _spawn(
        self,
        model_id: str,
        model_path: str | None,
        flags: tuple[str, ...],
        port: int,
        hkey: str,
    ) -> SidecarProcess:
        """Launch llama-server and wait for health check.

        Raises RuntimeError if the process exits before becoming healthy
        or the health-check timeout elapses.
        """
        # Build command-line args
        args = list(self._base_args)
        if model_path:
            args.extend(["--model", model_path])
        else:
            # Router mode: use model_id as the --model alias; llama-server
            # resolves it from models.ini sections.
            args.extend(["--model", model_id])
        args.extend(["--port", str(port)])
        args.extend(flags)

        args_str = " ".join(str(a) for a in args)
        logger.info(
            "PoolManager: spawn %s hash=%s port=%d args=%s",
            self._llama_server_bin, hkey[:8], port, args_str,
        )

        started_at = datetime.now(timezone.utc)

        try:
            process = await asyncio.create_subprocess_exec(
                self._llama_server_bin,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"llama-server binary not found: {self._llama_server_bin}. "
                "Install llama.cpp or set a different binary path."
            )
        except OSError as exc:
            raise RuntimeError(
                f"Failed to launch {self._llama_server_bin}: {exc}"
            ) from exc

        s = SidecarProcess(
            hash_key=hkey,
            model_id=model_id,
            model_path=model_path,
            flags=flags,
            port=port,
            pid=process.pid,
            started_at=started_at,
            last_used_ns=_now_ns(),
            healthy=False,
            process=process,
        )

        # Wait for /v1/models to return 200
        health_url = f"http://127.0.0.1:{port}/v1/models"
        deadline = _now_ns() + self._health_timeout_s * 1_000_000_000
        last_stderr = ""

        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            while _now_ns() < deadline:
                # Check if process exited early
                if process.returncode is not None:
                    stderr_buf = await process.stderr.read() if process.stderr else b""
                    last_stderr = stderr_buf.decode("utf-8", errors="replace")[-2000:]
                    break

                try:
                    resp = await client.get(health_url)
                    if resp.status_code == 200:
                        s.healthy = True
                        logger.info(
                            "PoolManager: healthy hash=%s port=%d pid=%d elapsed=%ds",
                            hkey[:8], port, process.pid,
                            (_now_ns() - s.last_used_ns) // 1_000_000_000,
                        )
                        return s
                except (httpx.HTTPError, OSError):
                    pass

                await asyncio.sleep(0.5)

        # Health check failed — collect stderr, kill, raise
        stderr_tail = ""
        if process.returncode is None:
            try:
                process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            except ProcessLookupError:
                pass
        else:
            stderr_out = await process.stderr.read() if process.stderr else b""
            stderr_tail = stderr_out.decode("utf-8", errors="replace")[-2000:]

        raise RuntimeError(
            f"Sidecar health check failed for {model_id} on port {port}: "
            f"exit={process.returncode} "
            f"stderr={last_stderr[:500] or stderr_tail[:500]}"
        )

    # -------------------------------------------------------------------
    # Health monitor
    # -------------------------------------------------------------------

    async def _health_loop(self) -> None:
        """Periodic health check + idle eviction loop."""
        while self._started:
            try:
                await asyncio.sleep(self._health_interval_s)
                await self._health_pass()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("PoolManager: health loop error")

    async def _health_pass(self) -> None:
        """Single health check + idle eviction pass."""
        idle_ns = self._idle_timeout_s * 1_000_000_000

        async with self._lock:
            to_remove: list[str] = []

            for hkey, s in list(self._sidecars.items()):
                # 1. Process exited?
                if s.process is not None and s.process.returncode is not None:
                    logger.warning(
                        "PoolManager: sidecar exited hash=%s port=%d rc=%s",
                        hkey[:8], s.port, s.process.returncode,
                    )
                    s.healthy = False
                    to_remove.append(hkey)
                    continue

                # 2. HTTP health check (only if currently healthy)
                if s.healthy:
                    try:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                            resp = await client.get(f"http://127.0.0.1:{s.port}/v1/models")
                            if resp.status_code != 200:
                                logger.warning(
                                    "PoolManager: sidecar unhealthy hash=%s port=%d (status=%d)",
                                    hkey[:8], s.port, resp.status_code,
                                )
                                s.healthy = False
                                to_remove.append(hkey)
                                continue
                    except (httpx.HTTPError, OSError) as exc:
                        logger.warning(
                            "PoolManager: sidecar health check failed hash=%s port=%d: %s",
                            hkey[:8], s.port, exc,
                        )
                        s.healthy = False
                        to_remove.append(hkey)
                        continue

                # 3. Idle timeout
                if (_now_ns() - s.last_used_ns) >= idle_ns:
                    idle_s = (_now_ns() - s.last_used_ns) / 1_000_000_000
                    logger.info(
                        "PoolManager: idle timeout hash=%s port=%d idle=%.0fs",
                        hkey[:8], s.port, idle_s,
                    )
                    to_remove.append(hkey)

            for hkey in to_remove:
                await self._remove_locked(hkey)

    # -------------------------------------------------------------------
    # Introspection
    # -------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Number of currently tracked sidecars (healthy or not)."""
        return len(self._sidecars)

    @property
    def started(self) -> bool:
        return self._started

    def list_sidecars(self) -> list[dict[str, Any]]:
        """Snapshot of all tracked sidecars."""
        now = _now_ns()
        result: list[dict[str, Any]] = []
        for hkey, s in list(self._sidecars.items()):
            result.append({
                "hash": hkey,
                "model_id": s.model_id,
                "port": s.port,
                "pid": s.pid,
                "started_at": s.started_at.isoformat(),
                "last_used_ns": s.last_used_ns,
                "idle_seconds": max(0.0, (now - s.last_used_ns) / 1_000_000_000),
                "healthy": s.healthy,
                "flags": list(s.flags),
            })
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_pool: PoolManager | None = None


def get_pool() -> PoolManager | None:
    """Return the global PoolManager singleton, or *None* if not initialized."""
    return _pool


def set_pool(pm: PoolManager | None) -> None:
    """Set (or clear) the global PoolManager singleton."""
    global _pool
    _pool = pm


# ---------------------------------------------------------------------------
# Proxy helper
# ---------------------------------------------------------------------------


async def proxy_chat_completion(
    provider: object,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[bytes]:
    """Proxy a ``/v1/chat/completions`` request through the pool.

    When the pool is active and *provider* is a bundled provider, acquires
    a sidecar for *model* and routes the request to ``127.0.0.1:<port>``.

    When the pool is *None* or *provider* is external, falls back to the
    provider's configured ``base_url`` (backward compat with static
    ``hlh_chat``).

    Yields SSE-encoded ``bytes`` in the same format as
    ``chats.py:_stream_inference``.

    Usage from ``inference_job.py``::

        stream = proxy_chat_completion(provider, effective_model, api_messages)
        async for chunk in stream:
            line = chunk.decode("utf-8")
            ...
    """
    from services.provider_client import Provider, build_headers

    pm = _pool

    # Decide: pooled vs static
    base_url: str
    headers: dict[str, str]
    provider_is_bundled = bool(getattr(provider, "is_bundled", False))

    if pm is not None and provider_is_bundled:
        try:
            sidecar = await pm.acquire(model)
        except RuntimeError as exc:
            yield _sse(json.dumps({"error": f"Process pool error: {exc}"}))
            return
        base_url = sidecar.base_url
        headers = {"Content-Type": "application/json"}
        sidecar_hash = sidecar.hash_key
    else:
        if not isinstance(provider, Provider):
            yield _sse(json.dumps({"error": "Invalid provider: not a Provider instance"}))
            return
        base_url = provider.base_url
        headers = build_headers(provider)
        sidecar_hash = None

    # Build the OpenAI-compatible payload
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(json.dumps({"error": f"Inference error {resp.status_code}: {err}"}))
                    return

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    yield _sse(line[6:].strip()) if line.startswith("data: ") else (line + "\n").encode("utf-8")

    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    finally:
        if pm is not None and sidecar_hash is not None:
            pm.touch(sidecar_hash)

    yield b"data: [DONE]\n\n"
