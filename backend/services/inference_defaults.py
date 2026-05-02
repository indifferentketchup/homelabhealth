"""Inference defaults: model name from env, raises if unset."""
from __future__ import annotations

import os


def required_default_model() -> str:
    """Read DEFAULT_MODEL env var. Raises RuntimeError if unset/empty."""
    v = (os.environ.get("DEFAULT_MODEL") or "").strip()
    if not v:
        raise RuntimeError("DEFAULT_MODEL env var is required")
    return v
