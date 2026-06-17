"""Daily tier  -  Markdown-file-based daily memory records with lazy creation.

Maintains human-readable daily logs at ``{data_dir}/YYYY-MM-DD.md``. Files are
created on first write of the day and appended to thereafter. Supports
user-scoped subdirectories.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_HEADER_MAP = {
    "overflow": "Context Overflow Recovery",
    "trim": "Trimmed Context",
    "daily_summary": "Daily Summary",
    "flush": "Conversation Flush",
    "dream": "Consolidation",
    "manual": "Manual Entry",
}


class DailyTier:
    """Manages daily Markdown memory files.

    File layout::

        {data_dir}/memory/YYYY-MM-DD.md          (shared daily records)
        {data_dir}/memory/users/{uid}/YYYY-MM-DD.md  (user-scoped)
    """

    def __init__(self, data_dir: str = "data/memory"):
        self.root = Path(data_dir)
        self.memory_dir = self.root
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _daily_path(self, date_str: str, user_id: Optional[str] = None) -> Path:
        """Get the path for a given date, optionally user-scoped."""
        if user_id:
            user_dir = self.memory_dir / "users" / user_id
            return user_dir / f"{date_str}.md"
        return self.memory_dir / f"{date_str}.md"

    def get_today_file(self, user_id: Optional[str] = None) -> Path:
        """Get today's daily memory file path (lazy creation)."""
        today = datetime.now().strftime("%Y-%m-%d")
        path = self._daily_path(today, user_id)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Daily Memory: {today}\n\n")
        return path

    def append(
        self,
        entry_text: str,
        reason: str = "flush",
        user_id: Optional[str] = None,
    ):
        """Append an entry to today's daily file.

        Args:
            entry_text: The text content to append.
            reason: Category label for the section header. One of
                ``overflow``, ``trim``, ``daily_summary``, ``flush``,
                ``dream``, ``manual``.
            user_id: Optional user scope.
        """
        daily_file = self.get_today_file(user_id)
        now = datetime.now().strftime("%H:%M")
        header = _HEADER_MAP.get(reason, "Session Notes")
        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {header} ({now})\n\n{entry_text}\n")
        logger.info("DailyTier: appended to %s (reason=%s)", daily_file.name, reason)

    def read_recent(
        self,
        lookback_days: int = 1,
        user_id: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Read recent daily files combined into a single string.

        Args:
            lookback_days: How many days to read (including today).
            user_id: Optional user scope.

        Returns:
            ``(combined_text, has_content)``.
        """
        parts: list[str] = []
        has_content = False
        today = datetime.now().date()
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            date_str = day.strftime("%Y-%m-%d")
            path = self._daily_path(date_str, user_id)
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"### {date_str}\n\n{content}")
                    has_content = True
            else:
                parts.append(f"### {date_str}\n\n_(no records)_")
        return "\n\n".join(parts), has_content

    def list_days(self, limit: int = 30, user_id: Optional[str] = None) -> list[str]:
        """List available daily file dates, most recent first."""
        search_dir = (
            self.memory_dir / "users" / user_id if user_id else self.memory_dir
        )
        if not search_dir.exists():
            return []
        files = sorted(search_dir.glob("*.md"), reverse=True)
        return [f.stem for f in files if f.stem.count("-") == 2][:limit]


__all__ = ["DailyTier"]
