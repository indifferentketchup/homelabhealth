"""Writers for chat/terminal history exports.

Pure-ish helpers: format content, strip ANSI, optionally rename a file
via the existing _openai_short_chat_title helper.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Match CSI sequences + common SGR/cursor + OSC terminators.
# Covers the subset tmux capture-pane -e emits.
_ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def ansi_strip(text: str) -> str:
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    return text


def timestamp_slug(now: _dt.datetime | None = None) -> str:
    d = now or _dt.datetime.utcnow()
    return d.strftime("%Y%m%d-%H%M%S")


def render_chat_markdown(chat: dict, messages: list[dict]) -> str:
    """chat: dict with at least title/created_at; messages: role+content+created_at."""
    title = (chat.get("title") or "Untitled Chat").strip()
    exported_at = _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    parts = [f"# {title}", "", f"Exported: {exported_at}"]
    if chat.get("model"):
        parts.append(f"Model: {chat['model']}")
    if chat.get("created_at"):
        parts.append(f"Started: {chat['created_at']}")
    parts.append("")
    for m in messages:
        role = (m.get("role") or "user").capitalize()
        ts = m.get("created_at")
        ts_line = f" ({ts})" if ts else ""
        parts.append(f"## {role}{ts_line}")
        parts.append("")
        parts.append((m.get("content") or "").rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_terminal_plaintext(label: str, machine: str, raw_capture: bytes) -> str:
    header = (
        f"# Terminal export\n"
        f"Label: {label}\n"
        f"Machine: {machine}\n"
        f"Exported: {_dt.datetime.utcnow().isoformat(timespec='seconds')}Z\n"
        + "-" * 60 + "\n\n"
    )
    text = raw_capture.decode("utf-8", errors="replace")
    return header + ansi_strip(text)
