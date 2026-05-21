"""Provider API-key encryption.

Optional AES-256-GCM keyed by PROVIDER_KEY_ENCRYPTION_KEY (32 raw bytes,
base64-encoded). If the env var is unset, encrypt/decrypt are passthroughs
so plaintext rows and encrypted rows coexist during rollout.

Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §2
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENC_PREFIX = "enc:v1:"
_NONCE_LEN = 12  # AES-GCM standard nonce length


def _key() -> bytes | None:
    raw = (os.environ.get("PROVIDER_KEY_ENCRYPTION_KEY") or "").strip()
    if not raw:
        return None
    try:
        k = base64.b64decode(raw, validate=True)
    except binascii.Error as e:
        raise RuntimeError("PROVIDER_KEY_ENCRYPTION_KEY must be valid base64") from e
    if len(k) != 32:
        raise RuntimeError(
            f"PROVIDER_KEY_ENCRYPTION_KEY must be 32 bytes base64; got {len(k)} bytes"
        )
    return k


def encrypt_secret(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    k = _key()
    if k is None:
        return plaintext
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(k).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ENC_PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_secret(stored: str | None) -> str | None:
    if stored is None:
        return None
    if not stored.startswith(ENC_PREFIX):
        return stored
    body = stored[len(ENC_PREFIX):]
    try:
        blob = base64.b64decode(body, validate=True)
    except binascii.Error:
        # Invalid base64 after prefix — treat as plaintext that happens to
        # begin with the prefix. Do not raise.
        return stored
    if len(blob) < _NONCE_LEN + 1:
        # Too short to contain a nonce + at least one ciphertext byte.
        return stored
    k = _key()
    if k is None:
        raise RuntimeError(
            "encrypted secret found but PROVIDER_KEY_ENCRYPTION_KEY unset"
        )
    try:
        pt = AESGCM(k).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None)
    except InvalidTag as e:
        raise RuntimeError(
            "provider api_key decrypt failed: invalid tag (wrong key or corruption)"
        ) from e
    return pt.decode("utf-8")
