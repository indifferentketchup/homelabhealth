"""Authentication endpoints."""
import os

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


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=12)


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, role FROM users WHERE username = $1",
            body.username,
        )
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid_credentials")
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
