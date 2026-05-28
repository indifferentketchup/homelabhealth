"""hlh_orchestra — minimal Docker container manager for vision lifecycle.

SCOPE: Can ONLY start/stop hlh_vision_embed. Hardcoded allowlist —
adding containers requires a code change + image rebuild.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import docker
from docker.errors import APIError, NotFound
from fastapi import FastAPI, Header, HTTPException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("orchestra")

ALLOWED_CONTAINERS = frozenset({"hlh_vision_embed"})
ORCHESTRA_TOKEN = os.environ.get("ORCHESTRA_TOKEN", "")
if not ORCHESTRA_TOKEN:
    raise SystemExit("ORCHESTRA_TOKEN env var is required")

client = docker.from_env()
app = FastAPI(title="hlh_orchestra", docs_url=None, redoc_url=None)


def _auth(token: str | None) -> None:
    if not token or token != ORCHESTRA_TOKEN:
        raise HTTPException(status_code=403, detail="unauthorized")


def _check_allowed(name: str) -> None:
    if name not in ALLOWED_CONTAINERS:
        logger.warning("refused operation on unauthorized container: %s", name)
        raise HTTPException(status_code=403, detail="container not allowed")


def _container_info(name: str) -> dict[str, Any]:
    try:
        c = client.containers.get(name)
        return {
            "name": name,
            "status": c.status,
            "started_at": c.attrs.get("State", {}).get("StartedAt"),
            "health": c.attrs.get("State", {}).get("Health", {}).get("Status"),
        }
    except NotFound:
        return {"name": name, "status": "not_found", "started_at": None, "health": None}
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"docker api error: {e}") from e


@app.get("/health")
def health():
    try:
        client.ping()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail="docker socket unreachable") from e


@app.get("/vision/status")
def vision_status(x_orchestra_token: str | None = Header(default=None)):
    _auth(x_orchestra_token)
    return _container_info("hlh_vision_embed")


@app.post("/vision/start")
def vision_start(x_orchestra_token: str | None = Header(default=None)):
    _auth(x_orchestra_token)
    _check_allowed("hlh_vision_embed")
    try:
        c = client.containers.get("hlh_vision_embed")
        if c.status == "running":
            return {"name": "hlh_vision_embed", "action": "noop", "status": "running", "duration_ms": 0}
        t0 = time.monotonic()
        c.start()
        for _ in range(50):
            c.reload()
            if c.status == "running":
                break
            time.sleep(0.1)
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("vision started in %dms", duration_ms)
        return {"name": "hlh_vision_embed", "action": "start", "status": c.status, "duration_ms": duration_ms}
    except NotFound as e:
        raise HTTPException(status_code=404, detail="container not found") from e
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"start failed: {e}") from e


@app.post("/vision/stop")
def vision_stop(x_orchestra_token: str | None = Header(default=None)):
    _auth(x_orchestra_token)
    _check_allowed("hlh_vision_embed")
    try:
        c = client.containers.get("hlh_vision_embed")
        if c.status != "running":
            return {"name": "hlh_vision_embed", "action": "noop", "status": c.status, "duration_ms": 0}
        t0 = time.monotonic()
        c.stop(timeout=15)
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("vision stopped in %dms", duration_ms)
        c.reload()
        return {"name": "hlh_vision_embed", "action": "stop", "status": c.status, "duration_ms": duration_ms}
    except NotFound as e:
        raise HTTPException(status_code=404, detail="container not found") from e
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"stop failed: {e}") from e
