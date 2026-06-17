"""Core data schemas — shared types across the memory tiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryChunk:
    """A single chunk of text with metadata and optional embedding."""

    id: str
    user_id: Optional[str] = None
    scope: str = "shared"
    source: str = "memory"
    path: str = ""
    start_line: int = 0
    end_line: int = 0
    text: str = ""
    embedding: Optional[List[float]] = None
    hash: str = ""
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    """A search result with relevance score and snippet."""

    path: str = ""
    start_line: int = 0
    end_line: int = 0
    score: float = 0.0
    snippet: str = ""
    source: str = "memory"
    user_id: Optional[str] = None


@dataclass
class RunningSummary:
    """Tracks conversation summarization state with token budget."""

    summary: str = ""
    summarized_message_ids: set = field(default_factory=set)
    last_summarized_message_id: Optional[str] = None
    token_count: int = 0


@dataclass
class ExtractedMemory:
    """Result of memory extraction — a fact with metadata."""

    id: str = ""
    content: str = ""
    category: str = "context"
    confidence: float = 0.5
    source: str = "manual"
    created_at: str = ""


@dataclass
class ConversationTurn:
    """A single conversation turn for flush processing."""

    role: str = "user"
    content: str = ""
    message_id: Optional[str] = None
    timestamp: Optional[str] = None


SCOPE_SHARED = "shared"
SCOPE_USER = "user"
SCOPE_WORKSPACE = "workspace"

VALID_SCOPES = {SCOPE_SHARED, SCOPE_USER, SCOPE_WORKSPACE}


__all__ = [
    "MemoryChunk",
    "SearchResult",
    "RunningSummary",
    "ExtractedMemory",
    "ConversationTurn",
    "SCOPE_SHARED",
    "SCOPE_USER",
    "SCOPE_WORKSPACE",
    "VALID_SCOPES",
]
