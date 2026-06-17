"""MemoryEngine — unified public API for the 3-tier memory system.

Manages conversation summarization (ContextTier), daily Markdown records
(DailyTier), and long-term SQLite + FTS5 + vector search (CoreTier).

Usage::

    engine = MemoryEngine()
    await engine.flush(messages, scope="user:abc")
    results = await engine.search("what did I say about allergies?")
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.memory.context_tier import ContextTier
from services.memory.core_tier import CoreTier
from services.memory.daily_tier import DailyTier
from services.memory.schemas import ConversationTurn, SearchResult

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = os.environ.get("HLH_MEMORY_DIR", "data/memory")


class MemoryEngine:
    """Unified memory engine — create, search, flush, and consolidate memories.

    Initializes all three tiers lazily on first use.
    """

    def __init__(
        self,
        data_dir: str = _DEFAULT_DATA_DIR,
        context_budget: int = 2000,
    ):
        self.data_dir = data_dir
        self.context_budget = context_budget

        # Lazy init — tiers created on first access
        self._context_tier: Optional[ContextTier] = None
        self._daily_tier: Optional[DailyTier] = None
        self._core_tier: Optional[CoreTier] = None

    @property
    def context(self) -> ContextTier:
        if self._context_tier is None:
            self._context_tier = ContextTier(budget=self.context_budget)
        return self._context_tier

    @property
    def daily(self) -> DailyTier:
        if self._daily_tier is None:
            self._daily_tier = DailyTier(data_dir=self.data_dir)
        return self._daily_tier

    @property
    def core(self) -> CoreTier:
        if self._core_tier is None:
            store_dir = Path(self.data_dir) / "long-term"
            store_dir.mkdir(parents=True, exist_ok=True)
            self._core_tier = CoreTier(store_path=store_dir / "index.db")
        return self._core_tier

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def manage(
        self,
        content: str,
        action: str = "create",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create, update, or delete memories.

        Args:
            content: The memory content (text).
            action: One of ``"create"``, ``"update"``, ``"delete"``.
            metadata: Optional metadata dict with keys like ``user_id``, ``scope``, ``source``.

        Returns:
            A dict with result status and chunk ID if created.
        """
        user_id = (metadata or {}).get("user_id")
        scope = (metadata or {}).get("scope", "shared")
        source = (metadata or {}).get("source", "manual")

        if action == "delete":
            chunk_id = hashlib.md5(content.encode("utf-8")).hexdigest()
            self.core.delete_fact(chunk_id)
            logger.info("MemoryEngine: deleted fact %s", chunk_id)
            return {"status": "deleted", "id": chunk_id}

        if action in ("create", "update"):
            # Attempt to embed, but fall back gracefully
            embedding = None
            try:
                from services.embeddings import embed_text

                embedding = await embed_text(content)
            except Exception as exc:
                logger.warning("MemoryEngine: embedding failed for manage(): %s", exc)

            chunk_id = self.core.save_fact(
                content=content,
                user_id=user_id,
                scope=scope,
                source=source,
                metadata=metadata,
                embedding=embedding,
            )

            # Also log to daily tier
            self.daily.append(
                entry_text=content,
                reason="manual",
                user_id=user_id,
            )

            logger.info(
                "MemoryEngine: %sd fact %s (scope=%s)",
                action,
                chunk_id,
                scope,
            )
            return {"status": action, "id": chunk_id, "embedded": embedding is not None}

        raise ValueError(f"Unknown action: {action}")

    async def search(
        self,
        query: str,
        limit: int = 10,
        scope: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Hybrid search across all memory tiers.

        Args:
            query: The search text (embedded for vector search, used as-is for keyword).
            limit: Maximum number of results.
            scope: Optional scope filter (e.g., ``"shared"``, ``"user"``).
            user_id: Optional user ID filter.

        Returns:
            Ranked list of SearchResult.
        """
        # Get query embedding (best-effort)
        query_embedding = None
        try:
            from services.embeddings import embed_query

            query_embedding = await embed_query(query)
        except Exception as exc:
            logger.warning(
                "MemoryEngine: embed_query failed for search, falling back to keyword only: %s",
                exc,
            )

        scopes = ["shared"]
        if scope == "user" and user_id:
            scopes.append("user")
        elif scope:
            scopes.append(scope)

        results = self.core.search(
            query_embedding=query_embedding,
            query_text=query,
            user_id=user_id,
            scopes=scopes,
            limit=limit,
        )

        # If no results from core, try context tier summary
        if not results:
            summary = self.context.get_summary()
            if summary and query.lower() in summary.lower():
                results.append(
                    SearchResult(
                        path="context",
                        start_line=0,
                        end_line=0,
                        score=0.5,
                        snippet=summary[:500],
                        source="context_tier",
                    )
                )

        return results

    async def flush(
        self,
        messages: List[ConversationTurn],
        scope: str = "shared",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a conversation turn into memory across all tiers.

        Steps:
            1. Update ContextTier (in-memory summarization).
            2. Write notable content to DailyTier (Markdown).
            3. Extract key facts and save to CoreTier (SQLite).

        Args:
            messages: List of conversation turns to process.
            scope: Memory scope.
            user_id: Optional user ID.

        Returns:
            Stats dict with counts of what was saved.
        """
        stats = {"context_appended": 0, "daily_appended": 0, "facts_saved": 0}

        # 1. Context tier — update summarization
        for msg in messages:
            needs_summary = self.context.append(msg)
            stats["context_appended"] += 1
            if needs_summary:
                logger.info("MemoryEngine: context budget exceeded, summary needed")

        # 2. Daily tier — write conversation to markdown
        if messages:
            lines = []
            for msg in messages:
                lines.append(f"**{msg.role}**: {msg.content}")
            daily_text = "\n\n".join(lines)
            self.daily.append(entry_text=daily_text, reason="flush", user_id=user_id)
            stats["daily_appended"] = 1

        # 3. Core tier — extract and save key facts
        # Use simple heuristic: save user messages with substantial content
        for msg in messages:
            if msg.role == "user" and len(msg.content.strip()) > 50:
                fact_content = msg.content.strip()
                try:
                    from services.embeddings import embed_text

                    embedding = await embed_text(fact_content)
                except Exception:
                    embedding = None

                self.core.save_fact(
                    content=fact_content,
                    user_id=user_id,
                    scope=scope,
                    source="conversation",
                    metadata={
                        "message_id": msg.message_id,
                        "timestamp": msg.timestamp or datetime.now().isoformat(),
                    },
                    embedding=embedding,
                )
                stats["facts_saved"] += 1

        logger.info(
            "MemoryEngine: flushed %d messages, %d facts saved",
            len(messages),
            stats["facts_saved"],
        )
        return stats

    async def dream(
        self,
        lookback_days: int = 7,
        scope: str = "shared",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Overnight consolidation — read recent daily entries and consolidate.

        This is a lightweight consolidation that:
            1. Reads recent days from DailyTier.
            2. Summarizes them into the ContextTier.
            3. Logs the consolidation event to DailyTier.

        Full LLM-powered consolidation (extracting facts from daily logs) can
        be added by passing a ``summarizer_fn`` to ``ContextTier.summarize()``.

        Args:
            lookback_days: How many days of daily records to consolidate.
            scope: Scope for any new memories created.
            user_id: Optional user ID.

        Returns:
            Stats dict.
        """
        stats = {"days_read": 0, "facts_consolidated": 0, "summary_updated": False}

        # 1. Read recent daily entries
        combined, has_content = self.daily.read_recent(
            lookback_days=lookback_days,
            user_id=user_id,
        )
        stats["days_read"] = lookback_days

        if not has_content:
            logger.info("MemoryEngine: dream found no daily content to consolidate")
            return stats

        # 2. Save a consolidated fact from daily content
        # Extract significant lines (non-header, non-empty)
        significant_lines = [
            line.strip()
            for line in combined.split("\n")
            if line.strip()
            and not line.startswith("#")
            and not line.startswith("_")
            and len(line.strip()) > 30
        ]
        if significant_lines:
            consolidated = " ".join(significant_lines[:5])  # top 5 lines
            try:
                from services.embeddings import embed_text

                embedding = await embed_text(consolidated)
            except Exception:
                embedding = None

            self.core.save_fact(
                content=f"Consolidated from daily records ({lookback_days} days): {consolidated}",
                user_id=user_id,
                scope=scope,
                source="dream",
                metadata={"lookback_days": lookback_days},
                embedding=embedding,
            )
            stats["facts_consolidated"] = 1

        # 3. Log consolidation to daily tier
        self.daily.append(
            entry_text=f"Consolidated {lookback_days} days of daily records.",
            reason="dream",
            user_id=user_id,
        )
        stats["summary_updated"] = True

        logger.info(
            "MemoryEngine: dream consolidated %d days, %d facts",
            lookback_days,
            stats["facts_consolidated"],
        )
        return stats

    # ------------------------------------------------------------------ #
    # Migration helper
    # ------------------------------------------------------------------ #

    async def migrate_from_mode_memory(
        self,
        content: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Migrate existing mode_memory content into the new engine.

        Called on first read of legacy mode_memory content to seed the
        CoreTier and DailyTier.
        """
        if not content or not content.strip():
            return

        # Save to core tier
        try:
            from services.embeddings import embed_text

            embedding = await embed_text(content)
        except Exception:
            embedding = None

        self.core.save_fact(
            content=content.strip(),
            user_id=user_id,
            scope="shared",
            source="migration",
            metadata={"migrated_from": "mode_memory"},
            embedding=embedding,
        )

        # Write to daily tier as historical entry
        self.daily.append(
            entry_text=f"Migrated from legacy memory:\n\n{content.strip()}",
            reason="manual",
            user_id=user_id,
        )

        logger.info("MemoryEngine: migrated mode_memory content (%d chars)", len(content))

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def close(self):
        """Close the CoreTier SQLite connection."""
        if self._core_tier is not None:
            self._core_tier.close()
            logger.info("MemoryEngine: closed core tier")


# Module-level singleton
_engine: Optional[MemoryEngine] = None


def get_engine() -> MemoryEngine:
    """Get or create the global MemoryEngine singleton."""
    global _engine
    if _engine is None:
        _engine = MemoryEngine()
    return _engine


def reset_engine():
    """Reset the singleton (useful for testing)."""
    global _engine
    if _engine is not None:
        _engine.close()
    _engine = None


__all__ = ["MemoryEngine", "get_engine", "reset_engine"]
