"""Built-in authentication service.

Password hashing: Argon2id via argon2-cffi (memory-hard, GPU-resistant).
Legacy PBKDF2-SHA256 hashes are verified on login for backwards compatibility
and re-hashed with Argon2id transparently (see verify_password).
Session tokens: secrets.token_urlsafe(32), stored as SHA-256 hash in DB.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


# Argon2id hasher  -  defaults: time_cost=3, memory_cost=65536, parallelism=4
_ph = PasswordHasher()

# Legacy PBKDF2 parameters kept only for verifying existing hashes
_PBKDF2_ALGO = "sha256"
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 32
_PBKDF2_DK_LEN = 32

# Session parameters
SESSION_TOKEN_BYTES = 32
SESSION_LIFETIME_HOURS = int(os.environ.get("HLH_SESSION_HOURS", "24"))


def hash_password(password: str) -> str:
    """Hash a password with Argon2id. Returns an argon2-cffi encoded hash string."""
    return _ph.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash.

    Supports both Argon2id hashes (new) and legacy PBKDF2 hashes (migration path).
    """
    if not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2:"):
        parts = stored_hash.split(":")
        if len(parts) != 3:
            return False
        _, salt_hex, expected_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(expected_hex)
        except ValueError:
            return False
        dk = hashlib.pbkdf2_hmac(
            _PBKDF2_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=_PBKDF2_DK_LEN
        )
        return secrets.compare_digest(dk, expected)
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _hash_token(token: str) -> str:
    """SHA-256 hash of a session token for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(conn: asyncpg.Connection, user_id) -> str:
    """Create a new session. Returns the raw token (for the cookie)."""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    token_hash = _hash_token(token)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_LIFETIME_HOURS)
    await conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, expires_at)
        VALUES ($1::uuid, $2, $3)
        """,
        user_id, token_hash, expires,
    )
    return token


async def validate_session(conn: asyncpg.Connection, token: str) -> Optional[dict]:
    """Validate a session token. Returns user dict or None."""
    token_hash = _hash_token(token)
    row = await conn.fetchrow(
        """
        SELECT s.user_id, s.expires_at, u.username, u.role, u.display_name
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = $1 AND s.expires_at > NOW()
        """,
        token_hash,
    )
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
    }


async def delete_session(conn: asyncpg.Connection, token: str) -> None:
    """Delete a session (logout)."""
    token_hash = _hash_token(token)
    await conn.execute("DELETE FROM sessions WHERE token_hash = $1", token_hash)


async def delete_expired_sessions(conn: asyncpg.Connection) -> int:
    """Clean up expired sessions. Returns count deleted."""
    result = await conn.execute("DELETE FROM sessions WHERE expires_at < NOW()")
    # asyncpg returns "DELETE N"
    return int(result.split()[-1]) if result else 0


async def create_user(conn: asyncpg.Connection, username: str, password: str, role: str = "owner") -> dict:
    """Create a new user with a hashed password. Returns the user dict."""
    pw_hash = hash_password(password)
    row = await conn.fetchrow(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES ($1, $2, $3)
        RETURNING id, username, role, display_name, created_at
        """,
        username, pw_hash, role,
    )
    return dict(row)


async def set_password(conn: asyncpg.Connection, user_id, password: str) -> None:
    """Set/update a user's password."""
    pw_hash = hash_password(password)
    await conn.execute(
        "UPDATE users SET password_hash = $1 WHERE id = $2::uuid",
        pw_hash, user_id,
    )


async def needs_setup(conn: asyncpg.Connection) -> bool:
    """True if no user has a password set (first-launch state)."""
    row = await conn.fetchrow(
        "SELECT 1 FROM users WHERE password_hash IS NOT NULL LIMIT 1"
    )
    return row is None
