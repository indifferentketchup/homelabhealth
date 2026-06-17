"""Handle MedGemma / Gemma-3 ``thought`` planning blocks in model output.

llama.cpp ``--reasoning-format deepseek`` does not yet split peg-native
``thought`` blocks for MedGemma 1.5 on server-b9282; thinking still arrives
in ``delta.content``. Homelabhealth separates thinking from the answer at the
API layer before SSE and before persisting assistant rows.

Thinking blocks are preserved with ``<THINKING>…</THINKING>`` markers so the
frontend can render them in a collapsible UI.
"""
from __future__ import annotations

import re
from typing import Iterator

_THOUGHT_PREFIX = re.compile(r"^thought\b\s*", re.I)

THINKING_OPEN = "<THINKING>"
THINKING_CLOSE = "</THINKING>"

# After the thinking checklist, the model addresses the user with a
# sentence-style paragraph. We split on the first double-newline paragraph
# that starts as a normal sentence (capital letter, not a bullet/checklist).
_PARAGRAPH_SPLIT = re.compile(
    r"\n\n(?=[A-Z][a-z])"
)

# Checklist / reasoning indicators  -  paragraphs starting with these stay
# in the thinking block.
_REASONING_LINE = re.compile(
    r"^(?:\*\s|[-•]\s|(?:\d+\.\s)|(?:\w+[\?:])\s|The plan\b|Okay[,.]|Let me\b|I (?:need|should|will|want|think)\b)",
    re.I,
)


def _find_answer_start(text_after_prefix: str) -> int | None:
    """Find where thinking ends and the user-facing answer begins."""
    for m in _PARAGRAPH_SPLIT.finditer(text_after_prefix):
        candidate_start = m.start() + 2  # skip the \n\n
        paragraph = text_after_prefix[candidate_start:candidate_start + 120]
        first_line = paragraph.split("\n")[0]
        if not _REASONING_LINE.match(first_line):
            return candidate_start
    return None


def strip_thinking_text(text: str) -> str:
    """Separate thinking from the answer, wrapping thinking in markers."""
    if not text:
        return text
    if not _THOUGHT_PREFIX.match(text.lstrip()):
        return text

    without_prefix = _THOUGHT_PREFIX.sub("", text.lstrip(), count=1)

    split = _find_answer_start(without_prefix)
    if split is not None:
        thinking = without_prefix[:split].strip()
        answer = without_prefix[split:].strip()
        if thinking and answer:
            return f"{THINKING_OPEN}{thinking}{THINKING_CLOSE}\n\n{answer}"
        if answer:
            return answer

    # Could not split  -  return without thinking wrapper so the response
    # is never hidden from the user.
    return without_prefix.strip()


class ThinkingStreamFilter:
    """Incremental filter that streams thinking content live.

    Instead of buffering all thinking silently, emits ``<THINKING>`` as soon
    as a ``thought`` prefix is detected, then streams thinking content through
    in real time. When the answer-start is detected, emits ``</THINKING>``
    and switches to pass-through for the answer.
    """

    _DETECT_MAX = 48

    def __init__(self) -> None:
        self._mode = "detect"
        self._buf = ""
        self._emitted_open = False
        self._prefix_stripped = False

    def feed(self, piece: str) -> list[str]:
        if not piece:
            return []
        if self._mode == "pass":
            return [piece]

        self._buf += piece

        if self._mode == "detect":
            ls = self._buf.lstrip()
            if len(ls) >= len("thought") and ls.lower().startswith("thought"):
                self._mode = "thinking"
                # Strip the "thought" prefix and emit the open tag + content so far
                content = _THOUGHT_PREFIX.sub("", ls, count=1)
                self._buf = ""
                self._prefix_stripped = True
                self._emitted_open = True
                return [THINKING_OPEN + content] if content else [THINKING_OPEN]
            if len(self._buf) >= self._DETECT_MAX:
                self._mode = "pass"
                out, self._buf = self._buf, ""
                return [out] if out else []
            return []

        # thinking  -  stream content live, watch for answer start
        # Check the full accumulated thinking for an answer transition.
        # We need to buffer a bit to detect paragraph boundaries.
        split = _find_answer_start(self._buf)
        if split is not None:
            thinking_tail = self._buf[:split].rstrip()
            answer = self._buf[split:].strip()
            self._buf = ""
            self._mode = "pass"
            out = []
            if thinking_tail:
                out.append(thinking_tail)
            out.append(THINKING_CLOSE + "\n\n")
            if answer:
                out.append(answer)
            return out

        # No answer start yet  -  flush everything except the last paragraph
        # (which might be the start of the answer).
        last_para = self._buf.rfind("\n\n")
        if last_para > 0:
            safe = self._buf[:last_para]
            self._buf = self._buf[last_para:]
            return [safe]
        return []

    def flush(self) -> list[str]:
        if self._mode == "pass":
            if not self._buf:
                return []
            out, self._buf = self._buf, ""
            return [out]

        if not self._buf and not self._emitted_open:
            return []

        # Still in thinking/detect mode at end of stream
        out = []
        if self._emitted_open:
            # We already emitted <THINKING>, flush remaining + close
            remaining = self._buf.strip()
            if remaining:
                out.append(remaining)
            out.append(THINKING_CLOSE)
        else:
            # Never got to thinking mode, just flush buffer
            result = strip_thinking_text(self._buf)
            if result:
                out.append(result)

        self._buf = ""
        self._mode = "pass"
        return out


def stream_visible_content(pieces: Iterator[str]) -> Iterator[str]:
    """Filter an iterator of content chunks, yielding visible answer text only."""
    filt = ThinkingStreamFilter()
    for piece in pieces:
        yield from filt.feed(piece)
    yield from filt.flush()
