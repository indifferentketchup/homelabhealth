"""Extractive context handoff for wave output compression.

Standalone module -- no external imports beyond stdlib. The LLM-abstractive
path is intentionally omitted; it is left as a future task once wave outputs
routinely exceed 8k tokens and a provider_client integration is warranted.

Public surface:
    extractive_summary(outputs, truncate) -> str
    format_as_input(source_id, summary, turn_count) -> str

(lift-durable-orchestration E4, 2026-06-13)
"""

from __future__ import annotations

from dataclasses import dataclass, field

_TRUNCATE_CHARS: int = 500


@dataclass
class HandoffContext:
    """Structured representation of a context handoff payload."""

    source_node_id: str
    summary: str
    key_outputs: list[str] = field(default_factory=list)
    turn_count: int = 0
    total_tokens_used: int = 0


def extractive_summary(outputs: list[str], truncate: int = _TRUNCATE_CHARS) -> str:
    """Return an extractive summary of wave outputs.

    Takes the first and last elements of ``outputs``, truncates each to
    ``truncate`` characters, and joins them with a double newline.
    If ``outputs`` has only one element, returns that element truncated.
    Returns ``"Empty conversation."`` for empty input.
    """
    if not outputs:
        return "Empty conversation."
    first = outputs[0][:truncate]
    if len(outputs) == 1:
        return first
    last = outputs[-1][:truncate]
    return f"{first}\n\n{last}"


def format_as_input(source_id: str, summary: str, turn_count: int) -> str:
    """Render a context handoff header block for injection into the next wave.

    Example output::

        --- CONTEXT FROM wave-1 (3 turns) ---
        <summary text>
        --- END CONTEXT ---
    """
    header = f"--- CONTEXT FROM {source_id} ({turn_count} turns) ---"
    footer = "--- END CONTEXT ---"
    return f"{header}\n{summary}\n{footer}"
