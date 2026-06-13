# Architecture Decisions — Fork Lift Wave 1

## Wave Ordering

### Decision: Four waves, dependency-respecting

```
Wave 1 (Foundation): Tasks 1-6 — no dependencies, all parallel
Wave 2 (Safety + Memory): Tasks 7-10 — sequential (safeguard → memory → audit → tools)
Wave 3 (RAG + Inference): Tasks 11-15 — all parallel within wave
Wave 4 (UI + Architecture): Tasks 16-20 — mostly parallel (17 depends on 16, 18 depends on 7)
```

**Rationale:** Wave 1 establishes infrastructure (hooks, config, verify) that Waves 2-4 depend on. Wave 2 is the critical path — safeguard rewrite must land before approval gates (Task 18), memory engine must land before memory tools (Task 10). Waves 3 and 4 have no cross-dependencies and can execute in any order after Wave 1.

### Dependency Matrix

- Tasks 1-6: no dependencies (Wave 1 foundation)
- Task 7 (safeguard rewrite): depends on Task 2 (hooks middleware)
- Task 8 (memory engine): standalone module, no dependencies
- Task 9 (audit recovery): depends on Task 2 (hooks for audit triggers)
- Task 10 (memory tools): depends on Task 8 (memory engine)
- Tasks 11-15: no dependencies (parallel within Wave 3)
- Task 16 (full ai-elements): no dependencies
- Task 17 (channel streaming): depends on Task 16 (ai-elements base)
- Task 18 (approval gate): depends on Task 7 (safeguards)
- Task 19 (conductor): no dependencies
- Task 20 (token analyzer): no dependencies

## Guardrails

### Must Have

- All 13 lifts implemented and verified
- Backward compatible — no existing feature breaks
- openspec directory with README, config.yaml, and this change batch
- Each lift adds its own verify script

### Must NOT Have

- No new external runtime dependencies (Python or npm)
- No changes to existing API contracts or wire spec error strings
- No changes to `schema.sql` table structure (additive only)
- No removal of existing verify scripts without replacement
- No premature abstraction — each lift stands alone

## Backward Compat Strategy

### Safeguard rewrite (Task 7)
Keep `prepend_safeguard()` function signature identical. New engine is called internally. `SAFEGUARD_VERSION` bumped to `b2-{date}`. Old verify scripts pass unchanged.

### Memory engine (Task 8)
Keep existing `mode_memory` table. New 3-tier engine reads from it on first migration, writes to its own tiers. Old API endpoints in `routers/memory.py` continue working — new engine is wired behind the same interface.

### Audit recovery (Task 9)
Additive to existing `services/audit.py`. New `audit_recovery.py` module with L0-L4 endpoints. Existing audit hash chain is untouched.

### Process pool (Task 14)
Backward compat: falls back to static `hlh_chat` if pool not configured. Existing `provider_client.py` resolution is extended, not replaced.

### Channel streaming (Task 17)
Old SSE format (non-channel) still accepted via upgrade shim. New channel format is opt-in on the server side.

### ai-elements (Task 16)
Components are additive. Old custom components remain alongside new ai-elements components. Migration is per-component, gradual.

## Data Model Decisions

No schema.sql changes in this batch. All new state lives in:
- Filesystem: memory engine uses `memory/YYYY-MM-DD.md` daily records, SQLite with WAL mode for FTS5 core tier
- In-memory: BM25 index built per-request, context tier summaries kept in process memory
- Config only: llama-cache-and-spec settings in `hlh_chat/models.ini`
- New Python modules: all additive, no existing files modified in breaking ways

## Verification Strategy

- Every task includes curl-based QA scenarios against the running stack
- New verify scripts live in `backend/scripts/verify_*.{sh,py}`
- Evidence files saved to `.omo/evidence/task-{N}-{scenario}.{ext}`
- UI changes verified via Playwright CLI where applicable
- Final verification wave: plan compliance audit, code quality review, integration QA, scope fidelity check
