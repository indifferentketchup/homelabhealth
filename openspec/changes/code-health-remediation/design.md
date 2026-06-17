# Design -- Code Health Remediation

## Ordering Rationale

Tasks are grouped into three independent batches that can execute in parallel or sequence:

**Batch A: Frontend quick wins (Tasks 1-5)** -- All touch `useStreamOrchestrator.js` or `SystemTab.jsx`. Each is a small, isolated fix. Verified via `cd frontend && npm run build`.

**Batch B: Backend quick wins (Tasks 6-8)** -- All touch `chats.py` or `memory_tools.py`. Each is a small, isolated fix. Verified via `python -m py_compile`.

**Batch C: Structural improvements (Tasks 9-16)** -- Larger refactors that reduce duplication. Each is independently landable but should land after the quick wins in the same file to avoid merge conflicts. Verified via build + compile + relevant verify scripts.

### Dependency Matrix

- Tasks 1-5: no dependencies (all frontend, different fix locations)
- Tasks 6-8: no dependencies (all backend, different fix locations)
- Task 9 (renameChat extract): no dependencies (Sidebar.jsx standalone)
- Task 10 (_assembled_system_prompt error handling): no dependencies (chats.py standalone)
- Task 11 (send dedup): no dependencies (useStreamOrchestrator.js standalone, but should land after Tasks 1-4)
- Task 12 (runStream callbacks): no dependencies (useStreamOrchestrator.js standalone, but should land after Task 11)
- Task 13 (memory_tools split): no dependencies (memory_tools.py standalone, but should land after Task 8)
- Task 14 (export_chat helpers): no dependencies (chats.py standalone, but should land after Tasks 6-7)
- Task 15 (tier-logic centralization): no dependencies (SystemTab.jsx standalone, but should land after Task 5)
- Task 16 (SidebarLink extract): no dependencies (Sidebar.jsx standalone, but should land after Task 9)

## Guardrails

### Must Have

- All 16 tasks implemented and verified
- Wire-contract error strings remain byte-identical (verified by grepping for known strings)
- `useStream.js` is NOT modified (hard rule #2)
- `frontend/src/components/ui/` checked before any new imports (hard rule #1)
- `docker compose build --no-cache hlh_api` after any Python source change (hard rule #5)
- Each task independently landable and verifiable

### Must NOT Have

- No changes to `useStream.js`
- No changes to wire-contract error strings
- No changes to `schema.sql`
- No new runtime dependencies
- No changes to existing verify scripts
- No em dashes in any output

## Adversarial Validator Findings (folded)

- **V1 (BLOCKING, folded):** Tasks 10 and 11 reference `exc` in `except` blocks that don't capture it. Fixed: all affected `except Exception:` changed to `except Exception as exc:` in tasks.md.
- **V2 (ADVISORY, noted):** Wire-contract string `"Another response is still streaming..."` in Task 11 uses ellipsis. Full string is `"Another response is still streaming. Stop it first or wait for it to finish."` -- use full string for grep verification.
- **V3 (ADVISORY, folded):** Task 16 SidebarLink extraction scope reduced to only the 3 "All workspaces" / "Sources" / "Profile" links that share `Button variant="ghost" asChild > Link` pattern. Bottom icon buttons (668-700, 701-743) have different variants and layouts; excluded from SidebarLink.
- **V4 (ADVISORY, folded):** Task 15 `createChatIfNeeded` extraction must accept a `setStreamingChatRef` callback or return the chat ID so the SSE path can set `streamingChatRef.current` after creation.
- **V5 (ADVISORY, folded):** Task 14 re-export list updated to include `run_background_extraction`.
- **V6 (ADVISORY, noted):** Task 12 `prepend_safeguard` call is not wrapped -- spec's "always execute" claim is technically false under safeguard failure. Low risk.
- **V7 (ADVISORY, noted):** Task 13 `ai_rename_file` helper collision loop raises `HTTPException` -- helper must either raise custom exception or plan must specify handling.
- **V10 (confirmed):** All line numbers verified accurate against current HEAD.

## Junior Developer Findings (folded)

- **JD#1 (BLOCKING, folded):** Task 2 clarified -- retry catch should NOT reset `activeChatId` or `draft` (those belong to the "no active chat" path only). Match the durable retry pattern: `setPendingSend(false)` + `clearStreamUi()` + `setSendError()`.
- **JD#2 (BLOCKING, folded):** Task 16 SidebarLink scope reduced -- only covers the 3 nav links (All workspaces, Sources, Profile) that share `Button asChild > Link` with `variant="ghost"`. Bottom buttons (AI, Analytics, Settings) and pinned workspace dots are excluded as they use different structures.
- **JD#3 (BLOCKING, folded):** Task 14 clarified -- update imports in `main.py` and `inference_job.py` to point to new modules (clean approach), AND keep `__all__` re-exports in `memory_tools.py` for any unknown third-party importers.
- **JD#4 (BLOCKING, folded):** Task 7 clarified -- `renameChat(chatId, title)` is a pure API helper; `setEditingId(null)` stays in the calling context (`commitRename` and `startRename`).
- **JD#6 (BLOCKING, folded):** Task 10 verification updated -- add note that the new SSE `{"type": "warning", ...}` event must be checked against the frontend's SSE parser in `useStream.js` to ensure unknown event types are ignored gracefully (not erroring).
- **JD#8 (BLOCKING, noted):** Task 4 acceptance criteria acknowledged -- `npm run build` proves compilation but not runtime. Streaming smoke test is the real verification.
- **JD#9 (BLOCKING, folded):** Task 3 clarified -- ref should store `targetChatId` (the resolved chat ID from the durable path), not `activeChatId` (which could be null).

## Backward Compat Strategy

All changes are behavior-preserving refactors or bug fixes. No API contracts change. No SSE format changes. The only user-visible effects are:

1. Stuck UI states no longer occur after synchronous throws (Tasks 1-2)
2. Model warm-up failures now surface a warning instead of a generic error (Task 6)
3. Silent error swallowing now produces log output (Tasks 7-8)
4. Synthetic polling caps are now enforced (Task 5)

## Verification Strategy

- Frontend tasks: `cd frontend && npm run build`
- Backend tasks: `python -m py_compile <file>`
- Python changes: `docker compose build --no-cache hlh_api` then run relevant `verify_*.sh` scripts
- useStreamOrchestrator tasks: `grep -rn useStream frontend/src/` to verify no call-site breakage, plus streaming smoke test
- SystemTab tasks: preserve existing Playwright test IDs (`system-models-pull-all`, `system-model-pull-*`, `system-model-cancel-*`, `system-model-progress-*`, `system-synth-row-*`, `system-synth-test-*`, `system-synth-error-*`)
- Sidebar tasks: check `frontend/src/components/ui/` before imports

## Implementation notes

- 2026-06-15 live verification found that the mechanical cleanup had removed `Field` from `backend/routers/inference.py` while `DecomposeBody` and `AnalyzeBody` still used it at import time. The import was restored before rebuilding the API image.

- Validation finding V1 (2026-06-12): Task 12's per-section error handling declared `parts` after the workspace-prompt try/except that referenced it in its handler, so a workspace prompt fetch failure would raise NameError instead of degrading gracefully. Fixed by moving the `parts: list[str] = []` declaration above the first section block in `_assembled_system_prompt`. Verified with py_compile plus an AST check that the first reference to `parts` is the assignment.
