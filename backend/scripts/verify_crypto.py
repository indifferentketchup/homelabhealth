"""Verify backend/services/crypto.py behavior per spec §2 + hardening (§0 #7).

Self-contained: manipulates PROVIDER_KEY_ENCRYPTION_KEY in-process, exits 0
on success, non-zero on any failed assertion. No DB, no FastAPI, no network.

Run from project root:
    python backend/scripts/verify_crypto.py
"""

from __future__ import annotations

import base64
import os
import sys

# Make backend/ importable when run from project root.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Import after sys.path mutation.
from services.crypto import ENC_PREFIX, decrypt_secret, encrypt_secret  # noqa: E402


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures: list[str] = []


def _set_key(b64_key: str | None) -> None:
    if b64_key is None:
        os.environ.pop("PROVIDER_KEY_ENCRYPTION_KEY", None)
    else:
        os.environ["PROVIDER_KEY_ENCRYPTION_KEY"] = b64_key


def _gen_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}{(' — ' + detail) if detail else ''}")
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n— {title} —")


# ──────────────────────────────────────────────────────────────────────────────
# 1. No key: passthrough.
# ──────────────────────────────────────────────────────────────────────────────
section("No key configured (passthrough)")
_set_key(None)

check("encrypt_secret(None) -> None", encrypt_secret(None) is None)
check("decrypt_secret(None) -> None", decrypt_secret(None) is None)

plain = "sk-test-plain-roundtrip"
enc = encrypt_secret(plain)
check(
    "encrypt_secret returns plaintext unchanged when no key",
    enc == plain,
    f"got {enc!r}",
)
check(
    "decrypt_secret returns plaintext unchanged when no key",
    decrypt_secret(plain) == plain,
)

# ──────────────────────────────────────────────────────────────────────────────
# 2. Key configured: real AES-GCM roundtrip.
# ──────────────────────────────────────────────────────────────────────────────
section("Key configured (AES-256-GCM roundtrip)")
key_b64 = _gen_key_b64()
_set_key(key_b64)

plain2 = "sk-real-secret-abc123-ZZZ"
enc2 = encrypt_secret(plain2)
assert enc2 is not None
check("encrypt_secret produces enc:v1: prefix", enc2.startswith(ENC_PREFIX), f"got {enc2[:20]!r}")
check("ciphertext differs from plaintext", enc2 != plain2)
check("decrypt_secret recovers original", decrypt_secret(enc2) == plain2)

# Nonce randomization: two encrypts of same plaintext should differ.
enc2b = encrypt_secret(plain2)
check("two encrypts of same plaintext differ (nonce randomization)", enc2 != enc2b)
check("both decrypt back to the same plaintext", decrypt_secret(enc2b) == plain2)

# ──────────────────────────────────────────────────────────────────────────────
# 3. Mixed rollout: plaintext rows + enc:v1: rows decrypt correctly.
# ──────────────────────────────────────────────────────────────────────────────
section("Mixed rollout (plaintext + encrypted rows decrypt correctly)")
plain_row = "legacy-plaintext-value"
enc_row = encrypt_secret("freshly-encrypted-value")
check("legacy plaintext passes through decrypt unchanged", decrypt_secret(plain_row) == plain_row)
check("encrypted row decrypts to original", decrypt_secret(enc_row) == "freshly-encrypted-value")

# ──────────────────────────────────────────────────────────────────────────────
# 4. Hardening: prefix-but-not-base64 → passthrough (no raise).
# ──────────────────────────────────────────────────────────────────────────────
section("Hardened decrypt — prefix without valid base64")
weird1 = "enc:v1:notbase64!!"
check(
    "decrypt_secret('enc:v1:notbase64!!') returns input unchanged",
    decrypt_secret(weird1) == weird1,
)

# ──────────────────────────────────────────────────────────────────────────────
# 5. Hardening: prefix + base64 but too short → passthrough (no raise).
# ──────────────────────────────────────────────────────────────────────────────
section("Hardened decrypt — prefix with valid base64 but too short")
weird2 = ENC_PREFIX + base64.b64encode(b"\x00" * 10).decode("ascii")
check(
    "decrypt_secret(short blob) returns input unchanged",
    decrypt_secret(weird2) == weird2,
)

# Edge case at the boundary: exactly 12 bytes (nonce only, no ct) → too short.
weird3 = ENC_PREFIX + base64.b64encode(b"\x00" * 12).decode("ascii")
check(
    "decrypt_secret(12-byte blob, no ciphertext) returns input unchanged",
    decrypt_secret(weird3) == weird3,
)

# ──────────────────────────────────────────────────────────────────────────────
# 6. Encrypted secret found, but key unset → RuntimeError.
# ──────────────────────────────────────────────────────────────────────────────
section("Encrypted secret with key now unset")
ciphertext_from_real_key = enc2  # encrypted with key_b64 above
_set_key(None)
raised = False
err_msg = ""
try:
    decrypt_secret(ciphertext_from_real_key)
except RuntimeError as e:
    raised = True
    err_msg = str(e)
check(
    "decrypt_secret raises RuntimeError when prefix present and key unset",
    raised,
)
check(
    "RuntimeError message mentions PROVIDER_KEY_ENCRYPTION_KEY",
    "PROVIDER_KEY_ENCRYPTION_KEY" in err_msg,
    f"got: {err_msg!r}",
)

# ──────────────────────────────────────────────────────────────────────────────
# 7. Wrong key → InvalidTag → RuntimeError("...invalid tag...").
# ──────────────────────────────────────────────────────────────────────────────
section("Wrong key for stored ciphertext")
wrong_key_b64 = _gen_key_b64()
_set_key(wrong_key_b64)
raised = False
err_msg = ""
try:
    decrypt_secret(ciphertext_from_real_key)
except RuntimeError as e:
    raised = True
    err_msg = str(e)
check("decrypt_secret raises RuntimeError on wrong key", raised)
check(
    "RuntimeError message contains 'invalid tag'",
    "invalid tag" in err_msg,
    f"got: {err_msg!r}",
)

# ──────────────────────────────────────────────────────────────────────────────
# 8. Invalid base64 in PROVIDER_KEY_ENCRYPTION_KEY → RuntimeError on _key().
# ──────────────────────────────────────────────────────────────────────────────
section("Invalid PROVIDER_KEY_ENCRYPTION_KEY")
_set_key("not-valid-base64!!")
raised = False
err_msg = ""
try:
    encrypt_secret("anything")
except RuntimeError as e:
    raised = True
    err_msg = str(e)
check("invalid base64 key raises RuntimeError", raised)
check(
    "error message mentions valid base64",
    "base64" in err_msg.lower(),
    f"got: {err_msg!r}",
)

# Short key (wrong length after b64decode) → RuntimeError.
_set_key(base64.b64encode(b"\x00" * 16).decode("ascii"))  # 16 bytes, not 32
raised = False
err_msg = ""
try:
    encrypt_secret("anything")
except RuntimeError as e:
    raised = True
    err_msg = str(e)
check("16-byte key raises RuntimeError (must be 32 bytes)", raised)
check(
    "error message mentions 32 bytes",
    "32 bytes" in err_msg,
    f"got: {err_msg!r}",
)

# ──────────────────────────────────────────────────────────────────────────────
# Result.
# ──────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[31m{len(_failures)} failure(s)\033[0m: {_failures}")
    sys.exit(1)
print(f"\033[32mAll checks passed.\033[0m")
sys.exit(0)
