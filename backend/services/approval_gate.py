"""Human-in-the-loop approval gate for the inference pipeline.

When triggered, pauses inference and sends an approval request to the user
via SSE. The user can accept, reject, or edit the pending action.

Architecture:
  ApprovalGate        -  in-memory gate state, keyed by chat_id
  ApprovalRequest     -  one pending request per chat
  ApprovalResponse    -  the user's decision (accept / reject / edit)

Triggers:
  1. Safeguard engine flags HIGH or CRITICAL guideline matches.
  2. Explicit ``request_approval(reason, options)`` call from anywhere in the
     pipeline (e.g. a tool or an output-guard post-completion check).

Flow:
  1. Pipeline calls request_approval() → stored in-memory.
  2. Pipeline emits SSE ``approval_required`` event to the client.
  3. Pipeline awaits wait_for_result() (blocking the inference job async).
  4. User responds via POST /api/chats/{id}/approval-response → gate resolved.
  5. Pipeline resumes (accept) or stops (reject) or retries (edit).

  If the user does not respond within ``timeout_s`` (default 60), the gate
  auto-continues with action=accept (logged as a warning).

Thread-safety:
  Uses asyncio.Event per chat. Not thread-safe  -  intended for single-event-loop
  use (FastAPI + asyncio). No external dependencies (stdlib only).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S: int = 60


class ApprovalAction(str, Enum):
    """User's decision on an approval request."""

    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"


@dataclass
class ApprovalRequest:
    """A pending approval request for one chat."""

    chat_id: str
    reason: str
    prompt: str
    options: list[str] = field(
        default_factory=lambda: ["accept", "reject", "edit"]
    )
    timeout_s: int = APPROVAL_TIMEOUT_S
    created_at: float = field(default_factory=time.monotonic)

    def to_sse_event(self) -> dict[str, Any]:
        """Build the SSE payload to send to the client."""
        return {
            "type": "approval_required",
            "reason": self.reason,
            "prompt": self.prompt,
            "options": self.options,
            "timeout_s": self.timeout_s,
        }


@dataclass
class ApprovalResponse:
    """The user's response to a pending approval request."""

    action: ApprovalAction
    edited_content: str | None = None



class ApprovalGate:
    """In-memory approval gate, keyed by ``chat_id``.

    One pending approval per chat.  If a new request arrives while one is
    already pending, the old one is replaced (the old waiter gets an ACCEPT
    auto-continue).
    """

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._responses: dict[str, ApprovalResponse] = {}

    # -- Producers -----------------------------------------------------------

    def request_approval(
        self,
        chat_id: str,
        *,
        reason: str,
        prompt: str,
        options: list[str] | None = None,
        timeout_s: int = APPROVAL_TIMEOUT_S,
    ) -> ApprovalRequest:
        """Register a pending approval request for *chat_id*.

        Returns the :class:`ApprovalRequest`  -  the caller should deliver it to
        the client (via SSE or the 202 response body) and then
        ``await wait_for_result()``.

        If the chat already has a pending request, it is replaced: the previous
        waiter's event is set with an ACCEPT auto-continue.
        """
        # Unblock any previous waiter for this chat first
        old_event = self._events.get(chat_id)
        if old_event is not None and not old_event.is_set():
            logger.warning(
                "approval_gate: replacing previous pending request for chat_id=%s",
                chat_id,
            )
            self._responses[chat_id] = ApprovalResponse(
                action=ApprovalAction.ACCEPT,
            )
            old_event.set()

        req = ApprovalRequest(
            chat_id=chat_id,
            reason=reason,
            prompt=prompt,
            options=options or ["accept", "reject", "edit"],
            timeout_s=timeout_s,
        )
        self._pending[chat_id] = req
        self._events[chat_id] = asyncio.Event()
        self._responses.pop(chat_id, None)

        logger.info(
            "approval_gate: request created chat_id=%s reason=%s",
            chat_id, reason,
        )
        return req

    # -- Consumer (blocking) -------------------------------------------------

    async def wait_for_result(
        self,
        chat_id: str,
        *,
        timeout_s: int | None = None,
    ) -> ApprovalResponse:
        """Wait for the user to respond to a pending approval.

        Blocks the caller until:
        * The user submits a response via ``submit_response()``, or
        * The timeout elapses (default 60 s)  -  auto-continue with ACCEPT, or
        * No request is pending  -  returns ACCEPT immediately.

        Returns the :class:`ApprovalResponse`.
        """
        event = self._events.get(chat_id)
        if event is None or event.is_set():
            return ApprovalResponse(action=ApprovalAction.ACCEPT)

        req = self._pending.get(chat_id)
        effective_timeout = timeout_s or (req.timeout_s if req else APPROVAL_TIMEOUT_S)

        try:
            await asyncio.wait_for(event.wait(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "approval_gate: timeout chat_id=%s timeout_s=%s  -  auto-continuing",
                chat_id,
                effective_timeout,
            )
            self._clear(chat_id)
            return ApprovalResponse(action=ApprovalAction.ACCEPT)

        response = self._responses.get(
            chat_id, ApprovalResponse(action=ApprovalAction.ACCEPT),
        )
        self._clear(chat_id)
        return response

    # -- Consumer (non-blocking / external) -----------------------------------

    def submit_response(
        self,
        chat_id: str,
        action: ApprovalAction,
        *,
        edited_content: str | None = None,
    ) -> bool:
        """Submit the user's response to a pending approval.

        Returns True if a pending request existed and the response was accepted.
        Returns False if there was nothing pending (no-op).
        """
        event = self._events.get(chat_id)
        if event is None or event.is_set():
            logger.warning(
                "approval_gate: no pending request for chat_id=%s", chat_id,
            )
            return False

        response = ApprovalResponse(action=action, edited_content=edited_content)
        self._responses[chat_id] = response
        event.set()
        logger.info(
            "approval_gate: response received chat_id=%s action=%s",
            chat_id,
            action.value,
        )
        return True

    # -- Queries -------------------------------------------------------------

    def is_pending(self, chat_id: str) -> bool:
        """Return True if *chat_id* has a pending (unanswered) approval."""
        event = self._events.get(chat_id)
        return event is not None and not event.is_set()

    def get_pending(self, chat_id: str) -> ApprovalRequest | None:
        """Return the pending :class:`ApprovalRequest` for *chat_id*, or None."""
        if self.is_pending(chat_id):
            return self._pending.get(chat_id)
        return None

    # -- Lifecycle -----------------------------------------------------------

    def cancel(self, chat_id: str) -> None:
        """Cancel any pending approval (e.g. on inference stop / disconnect)."""
        if self.is_pending(chat_id):
            logger.info("approval_gate: cancelled pending request chat_id=%s", chat_id)
            self._clear(chat_id)

    def _clear(self, chat_id: str) -> None:
        self._pending.pop(chat_id, None)
        self._events.pop(chat_id, None)
        self._responses.pop(chat_id, None)


_gate: ApprovalGate | None = None


def get_gate() -> ApprovalGate:
    """Return the singleton :class:`ApprovalGate`."""
    global _gate
    if _gate is None:
        _gate = ApprovalGate()
    return _gate


def reset_gate() -> None:
    """For testing  -  reset the singleton gate."""
    global _gate
    _gate = None



def should_request_approval(
    safeguard_matches: list[Any],
) -> tuple[bool, str]:
    """Examine safeguard engine results and decide if approval is needed.

    Returns ``(True, reason_string)`` when any match has HIGH or CRITICAL
    criticality, or ``(False, "")`` otherwise.

    The caller invokes this after the safeguard engine has evaluated the
    user's query and before inference starts.
    """
    # Deferred import to avoid circular dependency at module level
    from .safeguards_engine import Criticality

    for match in safeguard_matches:
        g = match.guideline
        if g.criticality in (Criticality.HIGH, Criticality.CRITICAL):
            return True, (
                f"Safeguard flagged a {g.criticality.value}-criticality match: "
                f"'{g.content.condition}'"
            )

    return False, ""



async def _pre_inference_hook(
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Registered as a ``pre_tool_execution`` hook.

    If the current chat has a pending approval gate request, blocks the
    inference call by returning a ``HookResult(blocked=True)`` payload.

    The hook context must carry ``chat_id`` for this to work.
    """
    if tool_name != "inference":
        return None

    chat_id = getattr(ctx, "chat_id", None) if ctx else None
    if not chat_id:
        return None

    gate = get_gate()
    if gate.is_pending(chat_id):
        logger.info(
            "pre_inference_hook: blocking inference for chat_id=%s "
            "(approval gate is pending)",
            chat_id,
        )
        return {"blocked": True, "reason": "Approval gate is pending for this chat."}

    return None


# Register the pre-inference hook at module import time so it's always active.
from .hooks import register as _register_hook

_register_hook("pre_tool_execution", _pre_inference_hook)
