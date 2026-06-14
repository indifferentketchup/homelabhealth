# Proposal: lift-deep-research

**Date:** 2026-06-13
**Status:** proposed

## Summary

Add an iterative multi-loop web research mode to homelabhealth and upgrade the
compaction summary prompt. The research loop runs multiple SearXNG searches,
summarizes per-iteration findings, reflects on gaps, and synthesizes a cited
answer. The compaction prompt gains richer health-context preservation. No
LangGraph, no sub-agent infrastructure, no new external dependencies.

## Motivation

HLH's current web search is single-shot: one SearXNG call per user message,
injected into the system prompt, with no iteration or gap-filling. For complex
health questions ("what are the second-line treatments for condition X after
metformin failure?") a single search sweep often returns shallow or tangential
snippets. The user must manually reformulate and re-ask.

The local-deep-researcher fork demonstrates that an iterative loop
(generate_query -> search -> summarize -> reflect -> follow-up -> loop ->
synthesize) produces materially better coverage for multi-faceted questions.
The pattern is fully portable as plain Python async code. HLH already has
SearXNG, an OpenAI-compat inference endpoint, and SSE streaming in place.

The compaction prompt (services/compaction.py:25-29) preserves health facts but
lacks structure around unresolved questions, medications, and decisions. The
chat-langchain fork's context_summary_prompt.py shows a concise improvement.
Upgrading the prompt is a 5-line edit with immediate benefit for long sessions.

## What changes

| Track | File(s) touched | Type |
|-------|-----------------|------|
| B1 | `backend/services/deep_research.py` (new) | New service |
| B1 | `backend/routers/chats.py` | New endpoint wired in |
| B2 | `backend/services/compaction.py` | Prompt edit |
| B1 | `backend/scripts/verify_deep_research.sh` (new) | Verify script |

## Scope

**In scope:**

- `services/deep_research.py`: async iterative research loop, max N loops
  (default 3, configurable via `global_settings.deep_research_max_loops`).
  Calls `services/searx.py::searx_search_sources` directly (adapted, not via
  LangChain wrapper). Per-iteration: search -> summarize -> compress findings
  -> reflect-on-gaps (chain-of-thought prompt, JSON output with safe fallback)
  -> decide follow-up query. Final step: synthesize with inline citations.
- New endpoint `POST /api/chats/{chat_id}/deep_research` that streams SSE
  progress events and final answer.
- `global_settings` key `deep_research_max_loops` (default "3") seeded with
  `INSERT ... ON CONFLICT (key) DO NOTHING` in `schema.sql`.
- `services/compaction.py` SUMMARY_SYSTEM_PROMPT enrichment (B2).
- `backend/scripts/verify_deep_research.sh` covering the endpoint and fallback
  paths.

**Out of scope (YAGNI / killed in validation):**

- Supervisor-researcher parallel delegation: requires sub-agent infrastructure
  not present; incompatible with single-slot llama-server.
- Link validation / live URL fetching: no meaningful value for snippet-based
  web search injection.
- Systematic literature review: blocked on sub-agent + arXiv infrastructure.
- Standalone conversation summarization: already exists (compaction.py +
  pruning.py). Only the prompt upgrade is actionable (B2).
- Webpage full-content summarization with structured output: deferred to Phase C;
  requires testing `response_format` JSON mode against local models first.
- Auto-triggering deep research via intent gate: deep research is slow on CPU
  (2-5 min for 3 loops); must be explicit user-invoked action only.
- Frontend UI for deep research mode trigger: deferred; the endpoint is usable
  via API and a future UI surface.

## Blocking unknowns (from validation B.md)

These are known risks the implementation must address explicitly:

- **BU-1 (CRITICAL):** JSON mode reliability on bundled models. The reflection
  step uses `response_format: {type: "json_object"}`. Reliability on
  medgemma-1.5-4b-it-Q4_K_M and qwen3.5-0.8B-Q8_0 is unconfirmed. Design
  mandates a safe fallback (use original topic as next query on parse failure).
- **BU-2 (HIGH):** SearXNG adapter API mismatch. `searx_search_sources` returns
  `(list[{title, url}], markdown_block_str)`. The deep_research loop must adapt
  to this tuple, not assume a dict.
- **BU-3 (MEDIUM):** Latency on CPU. One loop = ~4 sequential async LLM + HTTP
  calls. 3 loops can take 2-5 minutes on bundled CPU tier. SSE progress events
  mitigate UX impact. Deep research must never be auto-triggered.
- **BU-4 (LOW-MEDIUM):** Single-slot llama-server contention. Deep research
  monopolizes the bundled chat model. Document that concurrent chat sends will
  queue behind it.

## Risk

Medium. New service and endpoint are isolated from existing chat and RAG paths.
The compaction prompt change is low-risk (prompts do not affect data integrity).
The most likely failure mode is the JSON reflection fallback triggering on
bundled models, which is handled gracefully. No schema changes except one
idempotent `INSERT ... ON CONFLICT` for the new `global_settings` key.
