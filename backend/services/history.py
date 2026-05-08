"""Slug + path helpers for exported chat history files.

Host path: /data/history/  (bind-mounted from docker-compose.yml)
Container path: /data/history/    (default, overridable via HLH_HISTORY_DIR env)

Layout:
    /data/history/
        chats/
            <workspace-slug>/
                <file-slug>.md

The <workspace-slug> snapshots the workspace's name at export time. If a
workspace gets renamed later, existing files keep their old directory
(don't silently move).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

HISTORY_ENV = "HLH_HISTORY_DIR"
DEFAULT_HISTORY_DIR = "/data/history"

VALID_KINDS = ("chats",)

# Permissive, non-empty after strip; at most 120 chars for FS sanity.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.md$")


def history_root() -> Path:
    base = os.environ.get(HISTORY_ENV) or DEFAULT_HISTORY_DIR
    return Path(base)


def slugify(text: str, *, fallback: str = "untitled", max_len: int = 80) -> str:
    if not text:
        return fallback
    lowered = text.strip().lower()
    slugged = _SLUG_STRIP.sub("-", lowered).strip("-")
    if not slugged:
        return fallback
    return slugged[:max_len].rstrip("-") or fallback


def kind_dir(kind: str) -> Path:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}")
    return history_root() / kind


def workspace_dir(kind: str, workspace_name: str) -> Path:
    """Ensures the workspace-slug subdir exists under the kind dir; returns its Path."""
    d = kind_dir(kind) / slugify(workspace_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_filename(name: str) -> str:
    """Reject path traversal + enforce extension.

    Returns the cleaned basename. Raises ValueError on anything shady.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("filename must be non-empty")
    cleaned = os.path.basename(name.strip())
    if cleaned != name.strip():
        raise ValueError("filename must not contain path separators")
    if not _FILENAME_RE.match(cleaned):
        raise ValueError("filename must match [A-Za-z0-9_-]+.md")
    return cleaned


def safe_path(kind: str, workspace_name: str, filename: str) -> Path:
    """Resolves kind/workspace/filename and guarantees it stays inside history_root()."""
    filename = validate_filename(filename)
    workspace_slug = slugify(workspace_name)
    root = history_root().resolve()
    target = (root / kind / workspace_slug / filename).resolve()
    # Defense in depth: even though slugify + validate_filename block
    # traversal, assert the final path is inside root.
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("resolved path escapes history root")
    return target
