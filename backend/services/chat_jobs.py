"""In-process inference job registry  -  one active job per chat.

Mirrors BooCode turn.ts:385-444: each registration holds the asyncio.Task,
a cancel Event, and a completed Future so callers can await graceful shutdown
before retrying (prevents stop→retry race).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class InferenceRegistration:
    chat_id: UUID
    assistant_id: UUID
    task: asyncio.Task
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())


class ChatJobRegistry:
    def __init__(self) -> None:
        self._registry: dict[UUID, InferenceRegistration] = {}

    def register(self, chat_id: UUID, assistant_id: UUID, task: asyncio.Task) -> InferenceRegistration:
        reg = InferenceRegistration(
            chat_id=chat_id,
            assistant_id=assistant_id,
            task=task,
        )
        self._registry[chat_id] = reg
        return reg

    def has_active(self, chat_id: UUID) -> bool:
        reg = self._registry.get(chat_id)
        return reg is not None and not reg.completed.done()

    def get(self, chat_id: UUID) -> InferenceRegistration | None:
        return self._registry.get(chat_id)

    async def cancel(self, chat_id: UUID, timeout: float = 5.0) -> bool:
        reg = self._registry.get(chat_id)
        if reg is None:
            return False
        reg.cancel_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(reg.completed), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("cancel timed out for chat_id=%s, force-cancelling task", chat_id)
            reg.task.cancel()
        return True

    def mark_completed(self, chat_id: UUID, registration: InferenceRegistration) -> None:
        if self._registry.get(chat_id) is registration and not registration.completed.done():
            registration.completed.set_result(True)

    def remove_if_current(self, chat_id: UUID, registration: InferenceRegistration) -> None:
        if self._registry.get(chat_id) is registration:
            del self._registry[chat_id]

    def active_chat_ids(self) -> list[UUID]:
        return [cid for cid, reg in self._registry.items() if not reg.completed.done()]


job_registry = ChatJobRegistry()
