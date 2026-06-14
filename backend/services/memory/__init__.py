"""3-tier SQLite memory system (ContextTier, DailyTier, CoreTier) — agent-search index only.

OWNERSHIP MAP (2026-06-14)
==========================

This product has FOUR distinct memory stores. Their read/write ownership is fixed here
so contributors know which store to touch for any given change.

Store 1: SQLite CoreTier  (this package -- services/memory/)
------------------------------------------------------------
Authority: agent-tool search index. NOT read at inference time. NOT injected into the
system prompt by any prompt_assembly.py code path.

  Writers (file:line):
    - services/memory_extraction.py:112   extract_from_exchange() -> eng.manage()
        Called by services/memory_hooks.py:run_background_extraction(), which is
        scheduled by services/inference_job.py:516 when global_settings key
        'memory_auto_extract_enabled' == 'true'.
    - routers/memory.py:96    PUT /api/memory -> engine.manage()  (on mode_memory save)
    - routers/memory.py:200   POST /api/memory/extract -> engine.manage()  (after LLM extraction)
    - routers/memory.py:338   POST /api/memory/entries/ -> engine.manage()  (UI manual create; best-effort dual-write)
    - engine.py:flush() / dream() -- internal engine methods, not called from any live route

  Readers:
    - routers/memory.py:224   POST /api/memory/search -> engine.search()
        This is a MANUAL UI endpoint. Admin users can search the CoreTier directly.
    - services/memory_tools.py:search_memory() / manage_memory()
        Tool specs wired for agent-tool registration (MEMORY_TOOLS / MEMORY_TOOL_FUNCTIONS).
        As of 2026-06-14 these tool dicts are defined but NOT bound to any live FastAPI
        route or inference tool-call dispatch path. search_memory() is UNREACHABLE from
        the inference pipeline -- it feeds only a future agent-search index.

  NOT read at inference time. The SQLite CoreTier is NEVER consulted by
  prompt_assembly.py or rag.py during chat.

Store 2: pgvector memory_entries  (Postgres table)
---------------------------------------------------
Authority: semantic vector recall injected into the inference system prompt.
This is the INFERENCE-TIME memory store for unstructured facts.

  Writers (file:line):
    - services/inference_job.py:477   auto-memory insert after each inference turn
    - routers/chats.py:820            auto-memory insert in the legacy SSE streaming path
    - routers/memory.py:327           POST /api/memory/entries/ (owner UI manual create)
    - routers/memory.py:257           POST /api/memory/embed-all (backfill embeddings)
    - routers/memory.py:360,385       PATCH/DELETE /api/memory/entries/{id} (UI edits)

  Readers:
    - services/rag.py:287             retrieve_memory_facts() -- INFERENCE path
    - services/prompt_assembly.py:328 calls retrieve_memory_facts() -> injected into system prompt

Store 3: workspace_memory (Postgres table, per-workspace rows)
--------------------------------------------------------------
Authority: manually-curated workspace notes injected into the system prompt verbatim.

  Writers (file:line):
    - routers/workspace_memory.py:68  POST /api/workspaces/{id}/memory (owner UI)
    - routers/workspace_memory.py:95  DELETE /api/workspaces/{id}/memory/{entry_id}

  Readers:
    - services/prompt_assembly.py:299 SELECT content FROM workspace_memory -- INFERENCE path

Store 4: workspace_patient_profile (Postgres table, JSONB per workspace)
------------------------------------------------------------------------
Authority: structured durable patient facts (diagnoses, meds, allergies, facts[]).
Authoritative for anything that must survive across chats and be reliably surfaced.

  Writers (file:line):
    - services/memory_hooks.py:222    apply_fact_updates() -- called from
        run_background_extraction() after each inference turn (gated by
        'memory_auto_extract_enabled' and 'memory_conflict_resolution_enabled').
    - routers/workspaces.py:513       PUT /api/workspaces/{id}/patient-profile (UI manual upsert)

  Readers:
    - services/prompt_assembly.py:318 get_profile() + format_profile_for_injection() -- INFERENCE path
    - routers/workspaces.py:472       GET /api/workspaces/{id}/patient-profile (UI read)

INFERENCE-TIME READS (what is injected into the system prompt per turn):
  1. workspace_memory rows (verbatim, all rows)
  2. workspace_patient_profile JSONB (structured fields + facts, budget-capped)
  3. memory_entries via retrieve_memory_facts() (pgvector cosine search, gated by threshold)
  NOT included: SQLite CoreTier

AUTHORITATIVE-FOR-X RULES:
  patient_profile  = inference-time durable structured facts (diagnoses, meds, facts[])
  memory_entries   = inference-time semantic/unstructured recall (pgvector cosine)
  workspace_memory = manually-curated notes, always injected verbatim
  CoreTier         = agent-search index only; populated by extraction but not read at inference

NOTE on memory_tools.py barrel:
  services/memory_tools.py re-exports register_memory_hooks and run_background_extraction
  from memory_hooks for backward compatibility. As of 2026-06-14, NO file outside the
  memory subsystem imports from memory_tools.py. main.py imports register_memory_hooks
  directly from services.memory_hooks. The barrel exists for future agent-tool binding.
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
