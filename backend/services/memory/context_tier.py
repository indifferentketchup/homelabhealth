"""Context tier — short-term conversation context with token-budget summarization.

In-memory only (no persistence needed). Tracks a running summary of conversation
turns and triggers summarization when the token budget is exceeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Optional

from services.memory.schemas import RunningSummary

logger = logging.getLogger(__name__)

# Rough estimate: ~4 characters per token
_CHARS_PER_TOKEN = 4
_DEFAULT_BUDGET = 2000  # tokens before summarization triggers
_DEFAULT_MAX_SUMMARY_TOKENS = 256


def approx_token_count(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // _CHARS_PER_TOKEN


def count_tokens_messages(messages: Iterable[Any]) -> int:
    """Count approximate tokens across a sequence of messages."""
    total = 0
    for m in messages:
        if hasattr(m, "content"):
            total += approx_token_count(str(m.content))
        elif isinstance(m, dict):
            total += approx_token_count(str(m.get("content", "")))
        else:
            total += approx_token_count(str(m))
    return total


TokenCounter = Callable[[Iterable[Any]], int]


_INITIAL_SUMMARY_PROMPT = (
    "Create a concise summary of the conversation above that captures key facts, "
    "preferences, and decisions:\n\n{messages}"
)

_EXISTING_SUMMARY_PROMPT = (
    "Existing summary:\n{existing_summary}\n\nNew messages:\n{messages}\n\n"
    "Extend the existing summary by incorporating the new information. "
    "Keep it concise."
)

_FINAL_SUMMARY_PROMPT = (
    "Summary of the conversation so far:\n{summary}\n\n{messages}"
)


@dataclass
class PreprocessedMessages:
    """Result of preprocessing messages for summarization."""

    messages_to_summarize: List[Any]
    n_tokens_to_summarize: int
    max_tokens: int
    total_summarized_messages: int


@dataclass
class SummarizationResult:
    """Result of a summarization pass."""

    messages: List[Any]
    running_summary: Optional[RunningSummary] = None


class ContextTier:
    """In-memory conversation summarization with configurable token budget.

    Maintains a RunningSummary that tracks which messages have been summarized.
    When the accumulated token count exceeds the budget, a summarization callback
    is triggered.
    """

    def __init__(
        self,
        budget: int = _DEFAULT_BUDGET,
        max_summary_tokens: int = _DEFAULT_MAX_SUMMARY_TOKENS,
        token_counter: TokenCounter = count_tokens_messages,
    ):
        self.budget = budget
        self.max_summary_tokens = max_summary_tokens
        self.token_counter = token_counter
        self.summary: RunningSummary = RunningSummary()
        self._messages: List[Any] = []  # rolling buffer of recent messages

    def append(self, message: Any) -> bool:
        """Append a message. Returns True if the budget is exceeded and summarization is needed."""
        self._messages.append(message)
        total = self.token_counter(self._messages)
        self.summary.token_count = total
        return total >= self.budget

    def should_summarize(self) -> bool:
        """Check if the running total exceeds the configured budget."""
        return self.summary.token_count >= self.budget

    def summarize(
        self,
        summarizer_fn: Optional[Callable[[str], str]] = None,
        messages: Optional[List[Any]] = None,
    ) -> SummarizationResult:
        """Run summarization using the provided callable.

        Args:
            summarizer_fn: A callable that accepts a prompt string and returns
                a summary string. If None, returns a dry-run result without
                invoking an LLM.
            messages: The full message list. Defaults to the internal buffer.

        Returns:
            SummarizationResult with processed messages and updated RunningSummary.
        """
        msgs = messages if messages is not None else self._messages
        if not msgs:
            return SummarizationResult([], self.summary)

        # Determine which messages are new (not yet summarized)
        summarized_ids = self.summary.summarized_message_ids
        already_summarized = 0
        if self.summary.last_summarized_message_id:
            for i, m in enumerate(msgs):
                mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
                if mid == self.summary.last_summarized_message_id:
                    already_summarized = i + 1
                    break

        new_msgs = msgs[already_summarized:]

        # Check if we're over budget
        new_tokens = self.token_counter(new_msgs)
        if not summarizer_fn and new_tokens < self.budget:
            return SummarizationResult(msgs, self.summary)

        # Build the prompt
        existing = self.summary.summary
        if existing:
            formatted = _format_messages(new_msgs)
            prompt = _EXISTING_SUMMARY_PROMPT.format(
                existing_summary=existing, messages=formatted
            )
        else:
            formatted = _format_messages(new_msgs)
            prompt = _INITIAL_SUMMARY_PROMPT.format(messages=formatted)

        if summarizer_fn:
            summary_text = summarizer_fn(prompt)
        else:
            # Dry run — estimate summary from first N chars
            summary_text = formatted[:500] + "…" if len(formatted) > 500 else formatted

        # Update running summary
        for m in new_msgs:
            mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
            if mid:
                summarized_ids.add(mid)

        last_id = None
        if new_msgs:
            last = new_msgs[-1]
            last_id = getattr(last, "id", None) or (last.get("id") if isinstance(last, dict) else None)

        self.summary = RunningSummary(
            summary=summary_text,
            summarized_message_ids=summarized_ids,
            last_summarized_message_id=last_id,
            token_count=approx_token_count(summary_text),
        )

        remaining = msgs[already_summarized + len(new_msgs):]
        out_text = _FINAL_SUMMARY_PROMPT.format(
            summary=self.summary.summary,
            messages=_format_messages(remaining),
        )
        return SummarizationResult(
            messages=[_SystemMessage(content=out_text)],
            running_summary=self.summary,
        )

    def get_summary(self) -> str:
        """Get the current running summary text."""
        return self.summary.summary

    def clear(self):
        """Reset the context tier (e.g., for a new conversation)."""
        self.summary = RunningSummary()
        self._messages = []


class _SystemMessage:
    """Minimal system message shim for summarization output."""

    def __init__(self, content: str):
        self.role = "system"
        self.type = "system"
        self.content = content


def _format_messages(messages: List[Any]) -> str:
    """Format a list of messages into a prompt-friendly string."""
    lines = []
    for m in messages:
        role = (
            getattr(m, "role", None)
            or getattr(m, "type", "unknown")
        )
        content = getattr(m, "content", str(m))
        if isinstance(content, list):
            content = " ".join(str(p) for p in content)
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


__all__ = [
    "ContextTier",
    "RunningSummary",
    "SummarizationResult",
    "approx_token_count",
    "count_tokens_messages",
]
