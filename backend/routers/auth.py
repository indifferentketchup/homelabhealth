"""Authentication endpoints."""
import os
import time

from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel, Field
from db import get_pool
from services.auth import (
    create_session, create_user, delete_session,
    needs_setup, set_password, validate_session, verify_password,
)

router = APIRouter()

SESSION_COOKIE = "hlh_session"
COOKIE_MAX_AGE = 60 * 60 * 24  # 24 hours (matches SESSION_LIFETIME_HOURS default)
_SECURE_COOKIES = os.environ.get("HLH_SECURE_COOKIES", "false").lower() == "true"

# Brute-force throttle (SEC8): track failed login attempts per submitted username,
# whether or not that user exists, so the lockout behaves identically on both paths
# (no user-enumeration oracle). Process-local; a restart clears the lockout, an
# availability-favoring tradeoff acceptable for the single-user deployment. Under
# uvicorn --workers > 1 the budget multiplies; the stack runs a single worker.
_MAX_LOGIN_FAILURES = 5
_LOGIN_WINDOW_S = 15 * 60
_login_failures: dict[str, list[float]] = {}


def _recent_login_failures(username: str) -> list[float]:
    cutoff = time.monotonic() - _LOGIN_WINDOW_S
    recent = [t for t in _login_failures.get(username, []) if t >= cutoff]
    if recent:
        _login_failures[username] = recent
    else:
        _login_failures.pop(username, None)
    return recent


def _login_locked_out(username: str) -> bool:
    return len(_recent_login_failures(username)) >= _MAX_LOGIN_FAILURES


def _record_login_failure(username: str) -> None:
    _login_failures.setdefault(username, []).append(time.monotonic())


def _clear_login_failures(username: str) -> None:
    _login_failures.pop(username, None)


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=12)


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    username = body.username
    # Throttle check runs identically whether or not the username exists (SEC8).
    if _login_locked_out(username):
        raise HTTPException(status_code=429, detail="too_many_attempts")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, role FROM users WHERE username = $1",
            username,
        )
    if row is None or not verify_password(body.password, row["password_hash"]):
        _record_login_failure(username)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    _clear_login_failures(username)
    async with pool.acquire() as conn:
        token = await create_session(conn, row["id"])
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=_SECURE_COOKIES,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return {"ok": True, "username": body.username, "role": row["role"]}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await delete_session(conn, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not_authenticated")
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await validate_session(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="session_expired")
    return user


@router.get("/needs-setup")
async def check_needs_setup():
    """Returns whether the app needs first-time account creation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {"needs_setup": await needs_setup(conn)}


@router.post("/setup")
async def setup(body: SetupRequest):
    """First-time account creation. Only works if no user has a password."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # FOR UPDATE serializes concurrent setup requests  -  prevents TOCTOU race
            # where two simultaneous POSTs both pass the password_hash IS NULL check.
            row = await conn.fetchrow(
                "SELECT id, password_hash FROM users LIMIT 1 FOR UPDATE"
            )
            if row and row["password_hash"] is not None:
                raise HTTPException(status_code=409, detail="setup_already_complete")
            if row:
                await set_password(conn, row["id"], body.password)
                await conn.execute(
                    "UPDATE users SET username = $1 WHERE id = $2::uuid",
                    body.username, row["id"],
                )
                return {"ok": True, "username": body.username}
            user = await create_user(conn, body.username, body.password)
            return {"ok": True, "username": user["username"]}
