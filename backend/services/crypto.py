"""Provider API-key encryption and column encryption (C6 / v0.17.0).

Provider-key encryption:
  Optional AES-256-GCM keyed by PROVIDER_KEY_ENCRYPTION_KEY (32 raw bytes,
  base64-encoded). If the env var is unset, encrypt/decrypt are passthroughs
  so plaintext rows and encrypted rows coexist during rollout.

  Spec: docs/superpowers/specs/2026-05-21-providers-and-api-keys-design.md §2

Column encryption (C6 / v0.17.0):
  AES-256-GCM keyed by a per-record DEK derived from HLH_MASTER_KEY via HKDF
  (KEK/DEK envelope, no DEK storage). If HLH_MASTER_KEY is unset, column
  encrypt/decrypt are passthroughs for gradual rollout.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

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


# --- Column encryption (C6 / v0.17.0) ---

COL_ENC_PREFIX = "cenc:v1:"  # distinct from provider's "enc:v1:"


def _master_key() -> bytes | None:
    """Read HLH_MASTER_KEY from env. Returns 32 raw bytes or None."""
    raw = (os.environ.get("HLH_MASTER_KEY") or "").strip()
    if not raw:
        return None
    try:
        k = base64.b64decode(raw, validate=True)
    except binascii.Error as e:
        raise RuntimeError("HLH_MASTER_KEY must be valid base64") from e
    if len(k) < 32:
        raise RuntimeError(f"HLH_MASTER_KEY too short ({len(k)} bytes, need ≥32)")
    return k[:32]


def _derive_dek(master: bytes, record_id: str) -> bytes:
    """Derive a per-record DEK from the master key + record UUID via HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,  # HKDF without salt is fine when the IKM is high-entropy
        info=f"hlh-column-v1:{record_id}".encode("utf-8"),
    )
    return hkdf.derive(master)


def encrypt_column(plaintext: str, record_id: str) -> str:
    """Encrypt a column value using HLH_MASTER_KEY + per-record HKDF DEK.

    Returns COL_ENC_PREFIX + base64(nonce + ciphertext).
    If HLH_MASTER_KEY is unset, returns plaintext unchanged (passthrough
    for gradual rollout — same pattern as provider-key encryption).
    """
    master = _master_key()
    if master is None:
        return plaintext
    dek = _derive_dek(master, record_id)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)
    return COL_ENC_PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_column(stored: str, record_id: str) -> str:
    """Decrypt a column value. If not prefixed with COL_ENC_PREFIX, return as-is.

    Raises RuntimeError if HLH_MASTER_KEY is unset but the value is encrypted.
    Raises cryptography.exceptions.InvalidTag on wrong key or tampered data.
    """
    if not stored.startswith(COL_ENC_PREFIX):
        return stored  # plaintext passthrough
    master = _master_key()
    if master is None:
        raise RuntimeError(
            "HLH_MASTER_KEY unset but encrypted column value found — "
            "set the key or restore from backup"
        )
    dek = _derive_dek(master, record_id)
    raw = base64.b64decode(stored[len(COL_ENC_PREFIX):])
    nonce = raw[:_NONCE_LEN]
    ct = raw[_NONCE_LEN:]
    return AESGCM(dek).decrypt(nonce, ct, None).decode("utf-8")


def column_encryption_summary() -> dict[str, str | bool]:
    """Status for the doctor check."""
    try:
        master = _master_key()
    except RuntimeError as e:
        return {"enabled": False, "error": str(e)}
    if master is None:
        return {"enabled": False, "status": "HLH_MASTER_KEY unset — columns stored in plaintext"}
    return {"enabled": True, "status": "HLH_MASTER_KEY configured, AES-256-GCM via HKDF DEK"}
