"""3-tier memory system — Context, Daily, and Core.

Replaces the flat ``mode_memory`` singleton with a tiered architecture:

* **ContextTier** — in-memory conversation summarization with token budget
* **DailyTier** — human-readable Markdown daily records (``YYYY-MM-DD.md``)
* **CoreTier** — SQLite with WAL mode, FTS5 full-text search, and vector BLOBs
* **HybridSearch** — weighted ``0.7 * vector_cosine + 0.3 * bm25`` with temporal decay
* **MemoryEngine** — unified public API: ``manage()``, ``search()``, ``flush()``, ``dream()``
"""

from __future__ import annotations

from services.memory.context_tier import ContextTier, RunningSummary
from services.memory.core_tier import CoreTier, MemoryStore
from services.memory.daily_tier import DailyTier
from services.memory.engine import MemoryEngine, get_engine, reset_engine
from services.memory.hybrid_search import HybridSearchEngine
from services.memory.schemas import (
    ConversationTurn,
    ExtractedMemory,
    MemoryChunk,
    SearchResult,
)

__all__ = [
    # Tiers
    "ContextTier",
    "DailyTier",
    "CoreTier",
    "MemoryStore",
    # Search
    "HybridSearchEngine",
    # Engine
    "MemoryEngine",
    "get_engine",
    "reset_engine",
    # Schemas
    "MemoryChunk",
    "SearchResult",
    "ExtractedMemory",
    "ConversationTurn",
    "RunningSummary",
]
