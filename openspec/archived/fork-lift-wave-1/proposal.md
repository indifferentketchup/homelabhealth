# Fork Lift Wave 1 — 13 High-Value Feature Lifts

## TL;DR

Port 13 proven patterns from the `/opt/forks` and `/opt/boocode` ecosystems into homelabhealth. Each lift is independently valuable, backward compatible, and parallelizable across four waves.

## Why This Matters

homelabhealth ships bundled AI by default (llama.cpp, SearXNG, MedGemma), but its safety, memory, UI, retrieval, observability, and architecture patterns were built from scratch in v1.0. Mature open-source projects have solved these same problems with proven patterns. Instead of reinventing, this batch lifts their best ideas.

## What We Are Lifting

Each lift with source and why:

| # | Lift | Source | Why |
|---|------|--------|-----|
| 1 | **openspec directory** | `/opt/boocode/openspec/` | Standardized feature planning convention. Makes every future batch predictable. |
| 2 | **Lifecycle hooks** | `/opt/boocode/apps/server/src/services/hooks.ts` | Pre/post tool execution, on-stop, on-user-prompt hooks. Enables audit, guard, and safeguard wiring without spaghetti. |
| 3 | **Model config pattern** | `/opt/forks/chatbot/lib/ai/models.ts` | Structured model definitions per hardware tier. Makes tier-to-model mapping explicit instead of scattered if/else. |
| 4 | **Type-inject MCP** | `/opt/forks/type-inject/packages/mcp/` | AI type awareness during coding. Agents can look up types instead of guessing. |
| 5 | **Verify-gate pattern** | `/opt/forks/pskoett-skills/skills/verify-gate/SKILL.md` | Auto-discovers and runs verify scripts. Catch regressions before they merge. |
| 6 | **ai-elements Sources** | `/opt/forks/ai-elements/packages/elements/src/` | Collapsible RAG citation display with count badge. Standard component vs custom CSS. |
| 7 | **Guideline model** | `/opt/forks/boocontext-audit/src/` | Structured safeguard rules with condition/action/criticality, multi-batch matching, relational resolution. Replaces flat string prepend. |
| 8 | **3-tier memory engine** | `/opt/forks/memory_engine/` | Context/daily/core tiers + hybrid search (vector + BM25 + temporal decay). Replaces flat `mode_memory` table. |
| 9 | **Graded context recovery** | `/opt/forks/audit-harness/lib/audit_context.py` | L0-L4 recovery levels for audit context. Recover conversation state from sparse to full. |
| 10 | **LangMem-style memory tools** | `/opt/forks/langmem/src/langmem/knowledge/` | Agent-managed create/update/delete/search memories. Background extraction from conversation turns. |
| 11 | **BM25 pre-filter** | `/opt/forks/tree-sitter-analyzer/.../semantic_search.py` | Keyword pre-filter narrows 40k chunks to 400 before pgvector cosine search. ~133x retrieval speedup. |
| 12 | **RAG evaluator endpoints** | `/opt/forks/openevals/python/openevals/prompts/rag/` | LLM-as-judge groundedness, helpfulness, retrieval-relevance scoring. Measure RAG quality. |
| 13 | **llama-cache-and-spec** | `/opt/boocode/openspec/changes/llama-cache-and-spec/` | KV cache quantization, ngram speculative decoding, slot persistence. 2-4x inference speedup on GPU tiers. |
| 14 | **Process pool manager** | `/opt/forks/llama-sidecar/internal/pool/` | Dynamic per-model sidecar processes with health checks, LRU eviction, port allocation. Replaces single static hlh_chat. |
| 15 | **Supervisor-worker** | `/opt/forks/open_deep_research/.../deep_researcher.py` | Query decomposition into parallel sub-questions, synthesis with contradiction detection. For complex health queries. |
| 16 | **Full ai-elements suite** | `/opt/forks/ai-elements/packages/elements/src/` | 10 standard chat UI components: Conversation, Message, CodeBlock, PromptInput, etc. |
| 17 | **Channel-based streaming** | `/opt/boocode/openspec/changes/streaming-codeblocks-messages.../` | Typed channel deltas with seq ordering and mid-stream reconnection. Robust streaming. |
| 18 | **Human approval gate** | `/opt/boocode/openspec/changes/orchestrator-flow-advanced/` | Pause inference for user approval on safety-critical or ambiguous results. |
| 19 | **Conductor wave scheduler** | `/opt/boocode/conductor/src/flow.ts` | Multi-perspective analysis: parallel wave groups with barriers, automatic spine factory. |
| 20 | **Token analyzer UI** | `/opt/boocode/openspec/changes/token-analyzer-ui/` | Per-session token cost, tool breakdown, provider compare, trend chart. No new chart deps. |

## Scope

**In scope:** All 20 tasks across 4 waves. Backend Python modules, frontend React components, config files, and verify scripts. openspec directory convention.

**Out of scope:** Changes to existing API contracts, wire spec error strings, or schema.sql table structures. No new Python or npm runtime dependencies. No premature abstraction — each lift stands alone.

## Parallel Waves

```
Wave 1 (Foundation — 6 tasks, no dependencies):
  openspec docs, lifecycle hooks, model config, type-inject MCP, verify-gate, ai-elements Sources

Wave 2 (Safety + Memory — 4 tasks, mostly sequential):
  Guideline safeguard rewrite, 3-tier memory engine, L0-L4 audit recovery, LangMem-style tools

Wave 3 (RAG + Inference — 5 tasks, parallel):
  BM25 pre-filter, RAG evaluator endpoints, llama-cache-and-spec, process pool, supervisor-worker

Wave 4 (UI + Architecture — 5 tasks, mostly parallel):
  Full ai-elements suite, channel streaming, approval gate, conductor scheduler, token analyzer
```
