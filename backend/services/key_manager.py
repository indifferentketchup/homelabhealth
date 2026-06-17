"""Auto-generate encryption keys on first launch.

Keys persist to /data/.hlh_keys (a volume mount that survives container
rebuilds). Env vars always take precedence  -  if an operator sets
HLH_MASTER_KEY or PROVIDER_KEY_ENCRYPTION_KEY in their .env, the file
values are ignored.

Called once from main.py lifespan, before init_pool().
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

KEYS_FILE = Path(os.environ.get("HLH_KEYS_FILE", "/data/keys/.hlh_keys"))

# The two keys this module manages
_MANAGED_KEYS = {
    "HLH_MASTER_KEY": 48,           # 48 random bytes → 64 base64 chars
    "PROVIDER_KEY_ENCRYPTION_KEY": 32,  # Fernet-compatible: 32 bytes → 44 base64 chars
}


def _generate_key(nbytes: int) -> str:
    """Generate a standard base64-encoded random key.

    Uses standard (not URL-safe) base64 so the value is compatible with
    services/crypto.py's base64.b64decode() calls.
    """
    return base64.b64encode(secrets.token_bytes(nbytes)).decode("ascii")


def _read_keys_file() -> dict[str, str]:
    """Read key=value pairs from the keys file. Returns empty dict if missing."""
    if not KEYS_FILE.exists():
        return {}
    result = {}
    for line in KEYS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result


def _write_keys_file(keys: dict[str, str]) -> None:
    """Write keys to the file. Creates parent dirs if needed."""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Auto-generated encryption keys for homelabhealth.",
        "# Do not edit manually unless you know what you are doing.",
        "# Changing these keys makes existing encrypted data unreadable.",
        "",
    ]
    for k, v in sorted(keys.items()):
        lines.append(f"{k}={v}")
    KEYS_FILE.write_text("\n".join(lines) + "\n")
    # Restrict permissions
    KEYS_FILE.chmod(0o600)
    logger.info("key_manager: wrote keys to %s", KEYS_FILE)


def ensure_keys() -> None:
    """Ensure encryption keys are available in os.environ.

    Priority: env var > keys file > auto-generate.
    On first launch (no env, no file): generate both keys, write to file,
    set in env.
    On subsequent launches: read from file, set in env (unless env already set).
    """
    file_keys = _read_keys_file()
    generated_any = False

    for key_name, nbytes in _MANAGED_KEYS.items():
        env_val = os.environ.get(key_name, "").strip()
        if env_val:
            logger.info("key_manager: %s set via env (operator override)", key_name)
            continue

        file_val = file_keys.get(key_name, "").strip()
        if file_val:
            os.environ[key_name] = file_val
            logger.info("key_manager: %s loaded from %s", key_name, KEYS_FILE)
            continue

        # Neither env nor file  -  generate
        new_val = _generate_key(nbytes)
        os.environ[key_name] = new_val
        file_keys[key_name] = new_val
        generated_any = True
        logger.info("key_manager: %s auto-generated (first launch)", key_name)

    if generated_any:
        _write_keys_file(file_keys)


ENV_PATH = Path(os.environ.get("HLH_ENV_PATH", "/data/.env"))


def ensure_orchestra_token() -> None:
    """Generate ORCHESTRA_TOKEN in .env if absent.

    Shared secret between hlh_api and hlh_orchestra. Both read it from
    the compose environment, which sources .env. If absent on first
    boot, generate a 32-byte hex token and write it. hlh_orchestra
    picks it up on its next start.
    """
    if not ENV_PATH.exists():
        return

    lines: list[str] = []
    try:
        lines = ENV_PATH.read_text().splitlines(keepends=True)
    except OSError:
        return

    for line in lines:
        if line.startswith("ORCHESTRA_TOKEN="):
            val = line.split("=", 1)[1].strip()
            if val:
                os.environ.setdefault("ORCHESTRA_TOKEN", val)
                return

    token = secrets.token_hex(32)
    new_lines = []
    replaced = False
    for line in lines:
        if line.startswith("ORCHESTRA_TOKEN="):
            new_lines.append(f"ORCHESTRA_TOKEN={token}\n")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"ORCHESTRA_TOKEN={token}\n")

    tmp = str(ENV_PATH) + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(new_lines)
    os.replace(tmp, str(ENV_PATH))
    os.environ["ORCHESTRA_TOKEN"] = token
    logger.info(
        "key_manager: ORCHESTRA_TOKEN auto-generated. "
        "Restart hlh_orchestra to enable vision: docker compose restart hlh_orchestra"
    )
