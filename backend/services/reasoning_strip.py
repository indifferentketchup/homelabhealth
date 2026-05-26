"""Strip MedGemma / Gemma-3 ``thought`` planning blocks from model output.

llama.cpp ``--reasoning-format deepseek`` does not yet split peg-native
``thought`` blocks for MedGemma 1.5 on server-b9282; thinking still arrives
in ``delta.content``. Homelabhealth filters at the API layer before SSE and
before persisting assistant rows.
"""
from __future__ import annotations

import re
from typing import Iterator

_ANSWER_START_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\n\nHere are\b",
        r"\n\nHello[!,\s]",
        r"\n\nHi[!,\s]",
        r"\n\n\*\*Comprehensive\b",
        r"\n\n\*\*CBC\b",
        r"\n\n\*\*TSH\b",
        r"\n\n\[CRISIS\]",
    )
)

_GLUED_ANSWER = re.compile(
    r"(?<=[.!?:\"])(Hi!|Hello!|Hey!|Hi there!|Hello there!|Hi,|Hello,)\s*$",
    re.I,
)

_THOUGHT_PREFIX = re.compile(r"^thought\b\s*", re.I)


def _answer_start_index(text: str) -> int | None:
    best: int | None = None
    for pat in _ANSWER_START_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        pos = m.start() + 2
        if best is None or pos < best:
            best = pos
    return best


def strip_thinking_text(text: str) -> str:
    """Return user-visible text, dropping a leading ``thought`` block if present."""
    if not text:
        return text
    if not _THOUGHT_PREFIX.match(text.lstrip()):
        return text

    start = _answer_start_index(text)
    if start is not None:
        return text[start:].lstrip()

    m = _GLUED_ANSWER.search(text)
    if m:
        return text[m.start() :].lstrip()

    return ""


class ThinkingStreamFilter:
    """Incremental filter for SSE ``content`` chunks that may include thinking."""

    _DETECT_MAX = 48

    def __init__(self) -> None:
        self._mode = "detect"
        self._buf = ""

    def feed(self, piece: str) -> list[str]:
        if not piece:
            return []
        if self._mode == "pass":
            return [piece]

        self._buf += piece
        if self._mode == "detect":
            ls = self._buf.lstrip()
            if len(ls) >= len("thought") and ls.lower().startswith("thought"):
                self._mode = "suppress"
                return []
            if len(self._buf) >= self._DETECT_MAX:
                self._mode = "pass"
                out, self._buf = self._buf, ""
                return [out] if out else []
            return []

        # suppress
        start = _answer_start_index(self._buf)
        if start is not None:
            out = self._buf[start:].lstrip()
            self._buf = ""
            self._mode = "pass"
            return [out] if out else []
        return []

    def flush(self) -> list[str]:
        if self._mode == "pass":
            if not self._buf:
                return []
            out, self._buf = self._buf, ""
            return [out]

        if not self._buf:
            return []
        out = strip_thinking_text(self._buf)
        self._buf = ""
        self._mode = "pass"
        return [out] if out else []


def stream_visible_content(pieces: Iterator[str]) -> Iterator[str]:
    """Filter an iterator of content chunks, yielding visible answer text only."""
    filt = ThinkingStreamFilter()
    for piece in pieces:
        yield from filt.feed(piece)
    yield from filt.flush()
