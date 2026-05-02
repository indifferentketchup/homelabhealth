"""Writers for chat history exports."""
from __future__ import annotations

import datetime as _dt


def timestamp_slug(now: _dt.datetime | None = None) -> str:
    d = now or _dt.datetime.now(_dt.timezone.utc)
    return d.strftime("%Y%m%d-%H%M%S")


def render_chat_markdown(chat: dict, messages: list[dict]) -> str:
    """chat: dict with at least title/created_at; messages: role+content+created_at."""
    title = (chat.get("title") or "Untitled Chat").strip()
    exported_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
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
