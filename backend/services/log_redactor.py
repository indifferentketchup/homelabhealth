"""PHI-pattern redactor for Python logging.

Wraps the root logger's handlers so that any log record passing through
has its message scrubbed of common PHI patterns before reaching stdout.
Patterns are conservative (regex-only, no NLP) — some PHI will slip
through. The goal is defense-in-depth, not perfection.

Known gaps (v0.12.0):
- Name scrubbing is intentionally omitted — regex-only name matching
  produces too many false positives against medical terminology and
  common English words.
- The audit log's payload_hash is computed from the raw (pre-scrub) body
  in services/audit.py. Hashing the redacted body instead is deferred to
  a follow-up; for now the hash remains forensically accurate but the
  chain of custody means the raw body is never logged — only hashed.
- Non-US date formats (ISO 8601, DD.MM.YYYY) are not covered.
"""
import logging
import re
from typing import ClassVar

_REDACTED = "[REDACTED]"


class PHIRedactorFilter(logging.Filter):
    """Scrubs common PHI patterns from log record messages."""

    PATTERNS: ClassVar[list[tuple[str, re.Pattern]]] = [
        ("ssn",         re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        ("us_phone",    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
        ("email",       re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
        ("mrn",         re.compile(r"\bMRN[:\s#]*\d{4,12}\b", re.IGNORECASE)),
        ("dob",         re.compile(r"(?i)(?:DOB|date\s*of\s*birth|birth\s*date|born)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b")),
        ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Modify record.msg in-place. Always returns True (never drops records)."""
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._scrub(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._scrub(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True

    def _scrub(self, text: str) -> str:
        for _name, pattern in self.PATTERNS:
            text = pattern.sub(_REDACTED, text)
        return text


def install_redactor() -> None:
    """Install the PHI redactor on all root-logger handlers (current + future).

    Python's logging.Filter on a Logger only fires for records the logger
    itself emits — propagated records from child loggers bypass it. The
    filter must be on the *handler* to intercept every record regardless
    of which logger produced it.

    Strategy:
    - Attach the filter to every existing root handler.
    - Install a no-op filter subclass on the root logger as a sentinel so
      re-calling is a no-op (idempotent).
    - Also install on the root logger itself as a belt-and-suspenders for
      any code that calls root.info() directly.

    Call once at app startup (lifespan or module-level in main.py).
    Idempotent — re-calling is a no-op.
    """
    root = logging.getLogger()
    # Sentinel: if any PHIRedactorFilter already on the root logger, bail.
    for f in root.filters:
        if isinstance(f, PHIRedactorFilter):
            return  # already installed
    phi_filter = PHIRedactorFilter()
    # Belt-and-suspenders on the root logger itself.
    root.addFilter(phi_filter)
    # Add to every existing handler on the root logger.
    for handler in root.handlers:
        # Avoid double-installing on a handler that already has one.
        if not any(isinstance(f, PHIRedactorFilter) for f in handler.filters):
            handler.addFilter(phi_filter)
