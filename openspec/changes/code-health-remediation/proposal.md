# Code Health Remediation

## TL;DR

Fix 9 quick-win bugs and apply 8 lower-risk structural improvements identified by the 2026-06-12 code health audit. Each task is independently landable and verifiable. No wire-contract changes, no schema changes, no new dependencies.

## Why This Matters

The code health audit found 20 prioritized findings across 5 files. The 9 quick wins (all effort S, low risk) fix real bug risks: stuck UI states from unhandled synchronous throws (useStreamOrchestrator.js), silent error swallowing that degrades UX without feedback (chats.py), a stale closure that breaks polling caps (SystemTab.jsx), a missing log level (memory_tools.py), and duplicated rename logic (Sidebar.jsx). The 8 structural items reduce duplication in the same files without changing behavior.

The high-risk XL items (chats.py file split, gen() closure extraction, full Sidebar subcomponent decomposition, ModelsPanel decomposition, useStreamOrchestrator dual-protocol unification) and all Deferred (YAGNI) items are explicitly out of scope.

## What Changes

### Quick Wins (effort S, low risk)

| # | File | Change | Bug Risk Fixed |
|---|------|--------|----------------|
| 1 | `useStreamOrchestrator.js:514-518` | try/catch around `await runStream()` in SSE existing-chat path | Stuck UI (pendingSend=true forever) |
| 2 | `useStreamOrchestrator.js:569-576` | try/catch around `void runStream()` in retry path | Stuck UI (same as above) |
| 3 | `useStreamOrchestrator.js:265-296` | Store initiating chat ID in ref for durable cleanup branch | Stale chat ID on switch |
| 4 | `useStreamOrchestrator.js:538-544` | Add `clearStreamUi()` to forkAndStream catch block | Stale phase indicators after failure |
| 5 | `SystemTab.jsx:581-606` | Use ref for synthAttempts in polling interval | MAX_SYNTH_ATTEMPTS cap never enforced |
| 6 | `chats.py:1529-1537` | Yield SSE warning on model warm-up failure | Generic "Inference failed" hides real cause |
| 7 | `chats.py:1190,1467,1743,1755,1786` | Add logging or SSE events for silently swallowed errors | Silent quality degradation |
| 8 | `memory_tools.py:487` | Upgrade `logger.debug` to `logger.warning` | Audit trail errors invisible in production |
| 9 | `Sidebar.jsx:281-301` | Extract `renameChat()` helper | Code duplication |

### Structural Improvements (effort M, low risk)

| # | File | Change | Duplication Reduced |
|---|------|--------|---------------------|
| 10 | `chats.py:112-262` | Per-section error handling in `_assembled_system_prompt` | 7 DB fetches with no error isolation |
| 11 | `useStreamOrchestrator.js:406-519` | Extract `createChatIfNeeded()`, `beginStream()`, `handleStreamError()` | 4 code paths with ~60 duplicated lines |
| 12 | `useStreamOrchestrator.js:298-404` | Extract named callback builders for `runStream` | 8 anonymous callbacks, none testable |
| 13 | `memory_tools.py:1-567` | Split into `memory_tools.py` + `memory_extraction.py` + `memory_hooks.py` | 4 concerns in one module |
| 14 | `chats.py:805-926` | Extract `write_export_file()` and `ai_rename_file()` helpers | I/O, AI rename, collision in one function |
| 15 | `SystemTab.jsx:53-187,1164-1178` | Centralize tier classification into a typed data object | Tier logic duplicated in 3+ places |
| 16 | `Sidebar.jsx:403-743` | Extract `SidebarLink({ icon, label, to, collapsed })` | Collapsed/expanded link pattern repeated 6+ times |

## Scope

**In scope:** Quick wins 1-9 and structural items 10-16. Backend Python, frontend React/JS, config files.

**Out of scope (deferred to future changes):**
- `chats.py` file split (#20) -- high risk, requires wire-contract audit across all error strings
- `gen()` closure extraction (#19) -- high risk, 440-line closure with 15+ captured variables
- Full Sidebar subcomponent decomposition (#16 in audit) -- XL effort, 676-line component
- ModelsPanel decomposition (#14 in audit) -- L effort, Playwright test ID preservation required
- useStreamOrchestrator dual-protocol unification (S14) -- XL effort, acknowledged technical debt
- All items in the audit's Deferred (YAGNI) section: safeguards_engine.py low cohesion, rag.py score, conductor.py score, supervisor_worker.py score, chunking.py score

## Non-Goals

- No new API endpoints
- No schema.sql changes
- No new Python or npm runtime dependencies
- No wire-contract error string changes (all strings matched by frontend and Playwright remain byte-identical)
- No changes to `useStream.js` (declared fragile per CLAUDE.md hard rule #2)
- No changes to existing verify scripts
