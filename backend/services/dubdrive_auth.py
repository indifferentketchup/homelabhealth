"""DubDrive authentication service — auto-login with token caching."""
from __future__ import annotations
import logging
import os
import asyncio
import httpx

logger = logging.getLogger(__name__)

_token_lock = asyncio.Lock()
_cached_token: str | None = None


def _dubdrive_base_url() -> str:
    raw = (os.environ.get("DUBDRIVE_URL") or "").strip().rstrip("/")
    return raw or "http://100.114.205.53:9200"


def get_cached_token() -> str | None:
    """Return in-memory cached token, falling back to env var."""
    global _cached_token
    if _cached_token:
        return _cached_token
    t = (os.environ.get("DUBDRIVE_TOKEN") or "").strip()
    if t:
        _cached_token = t
    return _cached_token


async def login() -> str:
    """Login to DubDrive using DUBDRIVE_USER + DUBDRIVE_PASS, return token."""
    global _cached_token
    base = _dubdrive_base_url()
    user = (os.environ.get("DUBDRIVE_USER") or "").strip()
    pw = (os.environ.get("DUBDRIVE_PASS") or "").strip()
    if not user or not pw:
        raise RuntimeError("DUBDRIVE_USER and DUBDRIVE_PASS must be set in .env")

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{base}/auth/login",
            json={"username": user, "password": pw},
        )
    if r.status_code != 200:
        raise RuntimeError(f"DubDrive login failed: {r.status_code}")

    # Token is in Set-Cookie header, not response body
    token = None
    for cookie in r.cookies.jar:
        if cookie.name == "dubdrive_token":
            token = cookie.value
            break
    if not token:
        # Fallback: parse Set-Cookie header directly
        sc = r.headers.get("set-cookie", "")
        for part in sc.split(";"):
            part = part.strip()
            if part.startswith("dubdrive_token="):
                token = part[len("dubdrive_token="):]
                break

    if not token:
        raise RuntimeError("DubDrive login succeeded but no token in Set-Cookie")

    _cached_token = token
    os.environ["DUBDRIVE_TOKEN"] = token
    logger.info("DubDrive: re-authenticated successfully")
    return token


async def get_token() -> str:
    """Return valid token, logging in if necessary. Thread-safe."""
    async with _token_lock:
        t = get_cached_token()
        if t:
            return t
        return await login()


async def invalidate_and_relogin() -> str:
    """Clear cached token and force a fresh login."""
    global _cached_token
    async with _token_lock:
        _cached_token = None
        os.environ["DUBDRIVE_TOKEN"] = ""
        return await login()


def get_cookies(token: str) -> dict[str, str]:
    return {"dubdrive_token": token}
