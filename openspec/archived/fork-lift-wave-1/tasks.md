# Tasks — Fork Lift Wave 1

Wave groups and numbered implementation tasks with acceptance criteria.

---

## Wave 1: Foundation

### Task 1: Create openspec directory structure

**What to do:**
- Create `openspec/` directory at repo root
- Create `openspec/README.md` with layout and conventions
- Create `openspec/config.yaml` with project context
- Create `openspec/changes/fork-lift-wave-1/` directory
- Create proposal.md, design.md, tasks.md for this batch

**Files to create:**
- `openspec/README.md`
- `openspec/config.yaml`
- `openspec/changes/fork-lift-wave-1/proposal.md`
- `openspec/changes/fork-lift-wave-1/design.md`
- `openspec/changes/fork-lift-wave-1/tasks.md`

**Must NOT do:**
- Do not change any existing source code

**Acceptance criteria:**
- [ ] `openspec/README.md` exists with layout and slug conventions
- [ ] `openspec/config.yaml` exists with project context
- [ ] `openspec/changes/fork-lift-wave-1/` has proposal.md, design.md, tasks.md
- [ ] Files follow openspec format per `/opt/boocode/openspec/README.md`

**Commit:** YES — `docs: add openspec directory with fork-lift-wave-1 batch`

---

### Task 2: Add lifecycle hooks middleware

**What to do:**
- Create `backend/services/hooks.py`
- Implement four hook points: `pre_tool_execution`, `post_tool_execution`, `on_stop`, `on_user_prompt`
- Each hook has a registry for consumers to register/deregister callbacks
- Wire hooks into `routers/chats.py` POST /messages flow
- Wire hooks into `services/audit.py` for automatic audit capture
- Wire hooks into `services/guard.py` for scan integration
- Zero new dependencies — pure Python callbacks + contextvars

**Reference:** `/opt/boocode/apps/server/src/services/hooks.ts`

**Blocks:** Task 7 (safeguard rewrite), Task 9 (audit recovery)

**QA:**
```
Scenario: Pre-tool hook fires on chat message
  Steps: curl POST /api/chats/{id}/messages
  Expected: "pre_tool: chat.completion" in logs, audit event created

Scenario: Post-tool hook captures execution time
  Steps: Same as above
  Expected: post_tool_execution fires with duration_ms > 0
```

**Commit:** YES — `feat(services): add lifecycle hooks middleware`

---

### Task 3: Implement model config pattern

**What to do:**
- Create `frontend/src/config/models.js`
- Define ChatModel type with: id, name, provider, description, tiers, contextWindow, reasoningEffort, vision
- Define `getCapabilities(tier)` — returns models for a given tier
- Map 7 hardware tiers to model configs
- Export `DEFAULT_MODELS`, `getModelsForTier(tier)`, `getModelById(id)`
- Wire into existing `useAppStore` and `AISettings.jsx`

**Reference:** `/opt/forks/chatbot/lib/ai/models.ts`

**QA:**
```
Scenario: Models load correctly per tier
  Steps: GET /api/system/profile → getModelsForTier(tier)
  Expected: Returns array of model configs matching current tier
```

**Commit:** YES — `feat(frontend): add structured model config`

---

### Task 4: Register type-inject MCP server

**What to do:**
- Install `@nick-vi/type-inject-mcp` via npm
- Add MCP server config to server startup
- Tools: `lookup_type`, `list_types`
- Configure token budget and filtering
- Wire PostToolUse hook on Read to auto-inject type signatures

**Reference:** `/opt/forks/type-inject/packages/mcp/`

**QA:**
```
Scenario: Type-inject MCP server responds
  Steps: Query MCP server for tools → lookup_type for known component
  Expected: Type signatures returned
```

**Commit:** YES — `feat(devtools): add type-inject MCP server`

---

### Task 5: Wire verify-gate pattern

**What to do:**
- Create `scripts/verify-gate.sh` — auto-discovers and runs verify scripts
- Scans `backend/scripts/verify_*.{sh,py}`
- Reports: `N passed, M failed, K skipped`
- Informational gate (not blocking)

**Reference:** `/opt/forks/pskoett-skills/skills/verify-gate/SKILL.md`

**QA:**
```
Scenario: Verify gate runs all scripts
  Steps: bash scripts/verify-gate.sh
  Expected: Reports pass/fail per script, exits 0 if all pass
```

**Commit:** YES — `chore: add verify-gate script`

---

### Task 6: Install ai-elements Sources component

**What to do:**
- `cd frontend && npx shadcn@latest add https://elements.ai-sdk.dev/api/registry/all.json`
- Import `Sources` into `MessageBubble.jsx`
- Wire to `sources_used` data from assistant messages
- Style to match design tokens

**Reference:** `/opt/forks/ai-elements/packages/elements/src/sources.tsx`

**Blocks:** Task 16 (full ai-elements install)

**QA:**
```
Scenario: RAG sources render in chat
  Steps: Open chat UI, find assistant message with sources
  Expected: Sources collapsible with count badge visible
```

**Commit:** YES (groups with Task 16) — `feat(ui): add ai-elements Sources component`

---

## Wave 2: Safety + Memory

### Task 7: Rewrite services/safeguards.py with Guideline model

**What to do:**
- Create `backend/services/safeguards_engine.py`
- Guideline model: each rule has condition, action, criticality, labels, tags
- Multi-batch matcher: 6 batch types (Observational, Actionable, PreviouslyApplied, Disambiguation, ResponseAnalysis, LowCriticality)
- Relational resolver: DEPENDS_ON, PRIORITIZES, ENTAILS relationships
- Wire into existing `prepend_safeguard()` — replace flat string with engine call
- Bump `SAFEGUARD_VERSION` to `b2-{date}`
- Add verification script `verify_safeguards_guideline.sh`

**Reference:** `/opt/forks/boocontext-audit/src/guideline.ts`, `matching.ts`, `resolver.ts`

**Blocked by:** Task 2 (hooks middleware)
**Blocks:** Task 18 (approval gates)

**QA:**
```
Scenario: Guideline matching fires on diagnosis question
  Steps: POST message "What condition do I have with these symptoms?"
  Expected: Response explains possibilities, states "not a definitive diagnosis"

Scenario: Crisis guideline blocks response
  Steps: POST message expressing self-harm
  Expected: [CRISIS] tags present, no other content
```

**Commit:** YES — `feat(safeguards): rewrite with Guideline engine`

---

### Task 8: Replace mode_memory with 3-tier memory engine

**What to do:**
- Create `backend/services/memory/` package
- `context_tier.py` — in-memory summarization with token budget
- `daily_tier.py` — Markdown daily records `memory/YYYY-MM-DD.md`
- `core_tier.py` — SQLite FTS5 + vector BLOB hybrid search
- `hybrid_search.py` — weighted merge: `0.7 * vector_score + 0.3 * keyword_score` with temporal decay
- `schemas.py` — MemoryChunk, SearchResult, ExtractedMemory types
- `store.py` — SQLite with WAL mode, FTS5 virtual tables
- `engine.py` — MemoryEngine class with manage(), search(), flush(), dream()
- `background/deep_dream.py` — overnight LLM consolidation
- Keep existing `mode_memory` table for backward compat (migrate on read)
- Wire into `routers/memory.py` — old endpoints continue working
- Add verify script `verify_memory_engine.py`

**Reference:** `/opt/forks/memory_engine/`

**Blocks:** Task 10 (memory tools)

**QA:**
```
Scenario: Memory round-trip (store + search)
  Steps: PUT /api/memory → GET /api/memory → POST /api/memory/extract
  Expected: Memory persisted and retrievable

Scenario: Hybrid search returns keyword + vector results
  Steps: Insert memories, search with exact keyword
  Expected: Keyword match ranked above tangential vector match
```

**Commit:** YES — `feat(memory): 3-tier memory engine with hybrid search`

---

### Task 9: Add L0-L4 graded context recovery to services/audit.py

**What to do:**
- Create `backend/services/audit_recovery.py`
- 5 recovery levels: L0 index (~200 tok), L1 session trail (~500 tok), L2 corrections (~1000 tok), L3 full context (~3000 tok), L4 cross-day (~5000+ tok)
- JSONL buffer for in-flight capture
- Flush pipeline: PostToolUse → buffer, Stop → flush, UserPromptSubmit → context injection
- Wire into hooks from Task 2
- Add `/api/audit/recover?level=N` endpoint
- Add verify script `verify_audit_recovery.sh`

**Reference:** `/opt/forks/audit-harness/lib/audit_context.py`

**Blocked by:** Task 2 (hooks middleware)

**QA:**
```
Scenario: Recovery returns L0 summary
  Steps: GET /api/audit/recover?level=0
  Expected: Index with session count and timestamps, not full events

Scenario: L3 recovery returns full trail
  Steps: Create chat message, GET /api/audit/recover?level=3
  Expected: Full audit trail with all events
```

**Commit:** YES — `feat(audit): add graded context recovery L0-L4`

---

### Task 10: Implement LangMem-style memory extraction tools

**What to do:**
- Create `backend/services/memory_tools.py`
- `manage_memory(content, action, metadata)` — create/update/delete memories
- `search_memory(query, limit)` — uses hybrid search from Task 8
- Background extraction: `extract_memory_from_conversation(text)` — AI extracts facts post-completion
- Wire into inference loop as PostToolUse hook

**Reference:** `/opt/forks/langmem/src/langmem/knowledge/tools.py`, `extraction.py`

**Blocked by:** Task 8 (memory engine)

**QA:**
```
Scenario: Agent stores and retrieves memory
  Steps: manage_memory(create, "fact") → search_memory("query")
  Expected: Stored fact returned in search results
```

**Commit:** YES — `feat(memory): add agent-managed memory tools`

---

## Wave 3: RAG + Inference

### Task 11: Add BM25 pre-filter to rag.py

**What to do:**
- Add `_bm25_prefilter(queries, source_ids, top_k)` to `rag.py`
- Build per-request BM25 index, score candidates, filter to `BM25_PREFILTER_K = 400`
- Parameters: k1=1.5, b=0.75 (Okapi BM25 defaults)
- Graceful fallback to full vector search on failure
- Add `rag_bm25_enabled` global_settings toggle (default: true)

**Reference:** `/opt/forks/tree-sitter-analyzer/.../semantic_search.py`

**QA:**
```
Scenario: BM25 pre-filter narrows chunks
  Steps: Enable BM25, send RAG query, check chunk count in logs
  Expected: BM25 narrows to 400, logs show speedup

Scenario: BM25 fallback on empty index
  Steps: Send query with no BM25 matches
  Expected: Full vector search fallback, results returned
```

**Commit:** YES — `feat(rag): add BM25 pre-filter for 133x retrieval speedup`

---

### Task 12: Implement RAG evaluator endpoints

**What to do:**
- Create `backend/routers/eval.py`
- `POST /api/eval/groundedness` — LLM output supported by context?
- `POST /api/eval/helpfulness` — response addresses query?
- `POST /api/eval/retrieval-relevance` — docs are relevant?
- Each uses LLM-as-judge via workspace provider
- Pre-built prompts from OpenEvals
- Error-tolerant — evaluator failure returns None
- Add `/api/eval/settings` for thresholds

**Reference:** `/opt/forks/openevals/python/openevals/prompts/rag/`

**QA:**
```
Scenario: Groundedness eval returns score
  Steps: POST /api/eval/groundedness with made-up response
  Expected: Score < 1.0 (not fully grounded)

Scenario: Helpfulness eval for relevant response
  Steps: POST /api/eval/helpfulness with matching query+response
  Expected: Score > 0.7
```

**Commit:** YES — `feat(eval): add RAG quality evaluation endpoints`

---

### Task 13: Apply llama-cache-and-spec config

**What to do:**
- Edit `hlh_chat/models.ini` global section with:
  - `--cache-type-k q4_0` (KV cache quant, ~4x VRAM savings)
  - `--cache-reuse 256` (KV cache reuse across turns)
  - `--spec-type ngram-mod --spec-ngram-mod-thsh 2` (speculative decoding, 2-3x tok/s)
  - `--slot-save-path /tmp/llama-slots` (disk-persistent KV cache)
  - `--cache-idle-slots` (auto-save idle slot caches)
  - `--metrics` (Prometheus endpoint)
  - `--sleep-idle-seconds 600` (GPU memory reclaim)
- Create `/tmp/llama-slots` tmpfs in docker-compose for hlh_chat
- Add verify script `verify_inference_perf.sh`

**Reference:** `/opt/boocode/openspec/changes/llama-cache-and-spec/proposal.md`

**QA:**
```
Scenario: KV cache quant enabled
  Steps: docker logs hlh_chat | grep "cache-type"
  Expected: "--cache-type-k q4_0" active in logs

Scenario: Spec decoding active
  Steps: docker logs hlh_chat | grep "spec"
  Expected: ngram spec decoding loaded
```

**Commit:** YES — `perf(chat): enable KV cache quant + ngram spec decoding`

---

### Task 14: Build llama-sidecar process pool

**What to do:**
- Create `backend/services/process_pool.py`
- Hash-keyed process reuse, max concurrent (default 2), port range 9000-9099
- Background health checks every 30s, auto-kill on timeout (default 300s), LRU eviction
- OpenAI-compatible proxy: `/v1/chat/completions`, `/v1/models`, `/sidecars/{hash}`
- Integrate with `services/provider_client.py`
- Falls back to static hlh_chat if pool not configured

**Reference:** `/opt/forks/llama-sidecar/internal/pool/pool.go`

**QA:**
```
Scenario: Process pool spawns and health-checks
  Steps: POST chat request → check pool health endpoint
  Expected: Sidecar shown as healthy with model info

Scenario: Pool reuses existing sidecar
  Steps: Two chat requests same model
  Expected: Same sidecar reused (count = 1)
```

**Commit:** YES — `feat(chat): add llama-sidecar process pool`

---

### Task 15: Implement supervisor-worker for complex health queries

**What to do:**
- Create `backend/services/supervisor_worker.py`
- Supervisor: decomposes complex query into sub-questions via LLM structured output
- Workers: run in parallel via `asyncio.gather()`, each returns structured answer with confidence + citations
- Synthesis: collects answers, flags contradictions, confidence scoring
- Wire into chat pipeline — triggered by query complexity heuristic (>50 words, multiple ? marks, "compare" keywords)
- Add `/api/inference/decompose` debug endpoint

**Reference:** `/opt/forks/open_deep_research/.../deep_researcher.py`

**QA:**
```
Scenario: Simple query bypasses supervisor-worker
  Steps: POST "What is my LDL level?"
  Expected: Direct answer, no decomposition

Scenario: Complex query decomposes
  Steps: POST "How do my recent labs compare to last year?"
  Expected: 2+ sub-questions, independent answers synthesized
```

**Commit:** YES — `feat(rag): add supervisor-worker for complex health queries`

---

## Wave 4: UI + Architecture

### Task 16: Install full ai-elements component suite

**What to do:**
- Run ai-elements CLI: `npx shadcn@latest add https://elements.ai-sdk.dev/api/registry/all.json`
- Install: Conversation, Message, Sources (done), Tool, Reasoning, CodeBlock, PromptInput, InlineCitation, Attachments, Shimmer
- Adapt for homelabhealth's design tokens and data model

**Reference:** `/opt/forks/ai-elements/packages/elements/src/`

**Blocks:** Task 17 (channel streaming)

**QA:**
```
Scenario: Conversation component renders chat
  Steps: Open chat page, verify conversation container
  Expected: Conversation visible, scroll-to-bottom works
```

**Commit:** YES (with Task 6) — `feat(ui): install ai-elements chat components`

---

### Task 17: Upgrade streaming with channel-based reducer

**What to do:**
- Refactor `useStream.js` to use typed channel deltas
- Channels: text, tool_call, tool_result, status, metadata
- Each delta: `{ channel, type, payload, seq }` with monotonic sequence
- `channelReducer(state, delta)` and `ChannelBuffer` for out-of-order reordering
- Mid-stream reconnection: replay from last known seq
- Backward compat shim for old SSE format

**Reference:** `/opt/boocode/openspec/changes/streaming-codeblocks-messages-components-v2/`

**Blocked by:** Task 16 (ai-elements base)

**QA:**
```
Scenario: Channel deltas render in correct order
  Steps: Send chat message, check streaming state
  Expected: Text deltas render in seq order regardless of arrival
```

**Commit:** YES — `refactor(stream): channel-based streaming reducer`

---

### Task 18: Add human approval gate

**What to do:**
- Create `backend/services/approval_gate.py`
- Pauses inference, sends `{ type: "approval_required", prompt, options }` via SSE
- Frontend shows approval dialog with accept/reject/edit
- User responds, inference resumes or stops
- Wire as post_tool_hook
- Timeout 60s → auto-continue with warning

**Reference:** `/opt/boocode/openspec/changes/orchestrator-flow-advanced/`

**Blocked by:** Task 7 (safeguards for gating logic)

**QA:**
```
Scenario: Approval gate triggers and accepts
  Steps: POST message triggering approval → check SSE stream
  Expected: approval_required event emitted, pipeline paused
```

**Commit:** YES — `feat(chat): add human approval gate`

---

### Task 19: Implement conductor wave scheduler

**What to do:**
- Create `backend/services/conductor.py`
- Wave scheduler: flow as array of parallel step groups with barriers
- Spine factory: fold step, synthesizer, validator, render from analysis angles
- Default health angles: clinical, safety, data-integrity, patient-facing
- Wire as: `POST /api/inference/analyze` with `{ query, angles }`

**Reference:** `/opt/boocode/conductor/src/flow.ts`, `spine.ts`

**QA:**
```
Scenario: Wave scheduler runs parallel analysis
  Steps: POST /api/inference/analyze with 3 angles
  Expected: All 3 complete in parallel (wall clock ≈ single step time)

Scenario: Wave barrier enforces ordering
  Steps: wave1 (research) → wave2 (synthesis)
  Expected: All wave1 steps complete before wave2 starts
```

**Commit:** YES — `feat(analysis): add conductor wave scheduler`

---

### Task 20: Add token analyzer UI dashboard

**What to do:**
- Create `frontend/src/pages/workspace/AnalyticsPage.jsx`
- Tabbed dashboard: Session Usage, Tool Costs, Provider Compare, Trend
- Backend: `GET /api/analytics/tokens` from existing tables
- Data: messages.tokens_used, bundled_models, providers
- Charts: simple CSS/canvas (no chart library dependency)
- Route: `/analytics`, nav button in sidebar

**Reference:** `/opt/boocode/openspec/changes/token-analyzer-ui/`

**QA:**
```
Scenario: Analytics page loads with data
  Steps: Open /analytics
  Expected: Usage statistics display with real data in all tabs
```

**Commit:** YES — `feat(ui): add token analyzer dashboard`

---

## Final Verification Wave

### Task F1: Plan compliance audit
- Read plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist. Compare deliverables against plan.

### Task F2: Code quality review
- `python -m py_compile backend/**/*.py` + `cd frontend && npm run build`. Check for `as any`, empty catches, `console.log` in prod, commented-out code, unused imports, AI slop.

### Task F3: Integration QA
- Clean stack start. Full chat flow: create workspace → upload document → send message → RAG answer → audit trail → safeguard compliance. Cross-task integration.

### Task F4: Scope fidelity check
- For each task: read spec, read diff. 1:1 — everything in spec was built, nothing beyond spec was added. Check "Must NOT do" compliance.
