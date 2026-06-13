# Tasks -- Code Health Remediation

16 independently landable tasks across frontend (verify: `npm run build`) and backend (verify: `py_compile` + no-cache rebuild).

---

## Frontend Tasks (verify: `cd frontend && npm run build`)

### Task 1: Add try/catch around runStream in SSE existing-chat path

**File:** `frontend/src/hooks/useStreamOrchestrator.js:514-518`

**What to do:**
- Wrap `await runStream(activeChatId, content, messages.length + 1, sourceIds)` in try/catch
- On catch: reset `pendingSend`, `streamText`, `optimisticUser`, call `clearStreamUi()`, set `sendError`
- Do NOT reset `activeChatId` or `draft` (those belong to the "no active chat" path only)
- Pattern: match the durable retry catch at lines 561-566 (`setPendingSend(false)` + `clearStreamUi()` + `setSendError()`)

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)
- Do not change any SSE event format

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] `grep -rn useStream frontend/src/` shows no new call sites

**Verify:** `cd frontend && npm run build`

---

### Task 2: Add try/catch around runStream in retry path

**File:** `frontend/src/hooks/useStreamOrchestrator.js:569-576`

**What to do:**
- Wrap `void runStream(activeChatId, last, messages.length, null, { retryLast: true })` in try/catch
- On catch: reset `pendingSend`, `streamText`, `optimisticUser`, call `clearStreamUi()`, set `sendError`
- Pattern: match Task 1's error handling

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes

**Verify:** `cd frontend && npm run build`

---

### Task 3: Store initiating chat ID in ref for durable cleanup

**File:** `frontend/src/hooks/useStreamOrchestrator.js:265-296`

**What to do:**
- Add a `durableInitChatRef = useRef(null)` 
- In the send function's durable path, after `targetChatId` is resolved (line 427 or after new chat creation at line 444), set `durableInitChatRef.current = targetChatId`
- In the sync effect's cleanup branch (line 276-292), read from `durableInitChatRef.current` instead of `activeChatId`
- Clear the ref after cleanup completes

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes

**Verify:** `cd frontend && npm run build`

---

### Task 4: Add clearStreamUi to forkAndStream catch block

**File:** `frontend/src/hooks/useStreamOrchestrator.js:538-544`

**What to do:**
- Add `clearStreamUi()` to the catch block after `setStreamText('')`

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes

**Verify:** `cd frontend && npm run build`

---

### Task 5: Use ref for synthAttempts in polling interval

**File:** `frontend/src/components/settings/SystemTab.jsx:581-606`

**What to do:**
- Add `synthAttemptsRef = useRef({})` alongside the state
- Sync ref from state via a useEffect: `synthAttemptsRef.current = synthAttempts`
- In the interval callback (line 589), read from `synthAttemptsRef.current` instead of `synthAttempts`
- Preserve the eslint-disable comment explaining why synthAttempts is excluded from deps

**Must NOT do:**
- Do not change Playwright test IDs (`system-synth-row-*`, `system-synth-test-*`, `system-synth-error-*`)

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] Existing Playwright selectors still match

**Verify:** `cd frontend && npm run build`

---

### Task 6: Extract SidebarLink component

**File:** `frontend/src/components/layout/Sidebar.jsx`

**What to do:**
- Extract `SidebarLink({ icon: Icon, label, to, collapsed, onClick, ariaLabel, variant })` as a memoized subcomponent above the `Sidebar` function
- Replace the 3 nav link patterns that share `Button asChild > Link` structure:
  - "All workspaces" (lines 403-426, variant="ghost")
  - "Sources" (lines 427-452, variant="ghost")
  - "Profile" (lines 641-666, variant="outline")
- Do NOT attempt to unify the bottom icon buttons (lines 668-700, 701-743) or pinned workspace dots (lines 569-599) -- they use different structures
- Check `frontend/src/components/ui/` before importing any new primitives (hard rule #1)

**Must NOT do:**
- Do not extract SidebarNav, PinnedWorkspaces, RecentChats, or other XL subcomponents (out of scope)
- Do not attempt to unify patterns with different Button variants or HTML structures

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] Sidebar renders correctly in both collapsed and expanded states (manual check)

**Verify:** `cd frontend && npm run build`

---

### Task 7: Extract renameChat helper in Sidebar

**File:** `frontend/src/components/layout/Sidebar.jsx:281-301`

**What to do:**
- Extract `renameChat(chatId, title)` that calls `patchChat`, `patchRecentChatsListCache`, and invalidates queries -- this is a pure API helper, it does NOT own editing state
- `commitRename` keeps `setEditingId(null)` and reads `editTitle` from state, then calls `renameChat(chatId, editTitle.trim())`
- `commitRenameFromPrompt` takes `(chatId, title)` and calls `renameChat(chatId, title)` directly

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes

**Verify:** `cd frontend && npm run build`

---

### Task 8: Centralize tier-logic in SystemTab

**File:** `frontend/src/components/settings/SystemTab.jsx:53-187,1164-1178`

**What to do:**
- Add methods to each TIERS entry: `isCpu()`, `rationale(sysinfo)`, `diskWarning()`
- Replace `rationaleFor()` switch statement with `TIERS.find(t => t.id === recommended)?.rationale(sysinfo)`
- Replace `isCpuTier` check with `TIERS.find(...)?.isCpu()`
- Preserve existing TIERS labels, footprints, and detect strings exactly

**Must NOT do:**
- Do not change Playwright test IDs
- Do not change tier IDs or labels

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] Tier picker renders identically to before

**Verify:** `cd frontend && npm run build`

---

## Backend Tasks (verify: `python -m py_compile` + `docker compose build --no-cache hlh_api`)

### Task 9: Upgrade memory_tools daily.append log level

**File:** `backend/services/memory_tools.py:487-488`

**What to do:**
- Change `logger.debug("memory_hook: daily append skipped: %s", exc)` to `logger.warning`

**Acceptance criteria:**
- [x] `python -m py_compile backend/services/memory_tools.py` passes

**Verify:** `python -m py_compile backend/services/memory_tools.py`

---

### Task 10: Yield SSE warning on model warm-up failure

**File:** `backend/routers/chats.py:1529-1537`

**What to do:**
- Change `except Exception:` at line 1536 to `except Exception as exc:`
- Replace `pass` with:
  ```python
  logger.warning("model warm-up failed for %s: %s", effective_model, exc)
  yield _sse(json.dumps({"type": "warning", "message": f"Model warm-up failed for {effective_model}. Inference will still be attempted."}))
  ```

**Must NOT do:**
- Do not change any wire-contract error strings
- Do not change the control flow (inference still proceeds after warm-up failure)

**Acceptance criteria:**
- [x] `python -m py_compile backend/routers/chats.py` passes
- [x] The new `{"type": "warning", ...}` SSE event is ignored gracefully by the frontend SSE parser in `useStream.js` (unknown event types should not cause errors)

**Verify:** `python -m py_compile backend/routers/chats.py`

---

### Task 11: Add logging for silently swallowed errors in chats.py

**File:** `backend/routers/chats.py:1190,1467,1743,1755,1786`

**What to do:**
- Line 1190-1191 (user profile fetch): change `except Exception:` to `except Exception as exc:` and add `logger.warning("user profile fetch failed: %s", exc)` before `user_profile_block = ""`
- Line 1467-1468 (attached source read): already has `logger.warning` -- no change needed
- Line 1742-1743 (auto-title): change `except Exception:` to `except Exception as exc:` and add `logger.warning("auto-title generation failed: %s", exc)` before `new_title = None`
- Line 1754-1755 (title DB write): change `except Exception:` to `except Exception as exc:` and add `logger.warning("auto-title DB write failed chat_id=%s: %s", chat_id, exc)` before `pass`
- Line 1786 (memory embedding): already has `logger.warning` -- no change needed

**Must NOT do:**
- Do not change any wire-contract error strings
- Do not change error handling behavior (all failures still degrade gracefully)

**Wire-contract strings near these locations (must remain byte-identical):**
- `"input_blocked"` at line 1216
- `"Inference was rejected by user."` at line 1577
- `"Another response is still streaming..."` at line 1289
- `"Document retrieval failed. Try again or start a fresh chat."` at line 1413
- `"Inference failed. Check server logs for details."` at line 1646
- `"Analysis failed. Check server logs for details."` at line 1558

**Acceptance criteria:**
- [x] `python -m py_compile backend/routers/chats.py` passes
- [x] All wire-contract strings above remain byte-identical (verify with `grep -n`)

**Verify:** `python -m py_compile backend/routers/chats.py`

---

### Task 12: Add per-section error handling to _assembled_system_prompt

**File:** `backend/routers/chats.py:112-262`

**What to do:**
- Wrap each major section in try/except:
  - Workspace prompt fetch (lines 123-128)
  - Workspace instructions fetch (lines 139-146)
  - Workspace memory fetch (lines 148-154)
  - Memory facts retrieval (lines 157-161)
  - Context files fetch (lines 164-173)
  - Custom instructions fetch (lines 176-189)
  - RAG retrieval (lines 200-227) -- already has outer try/except in gen(), leave as-is
- On failure: log which section failed, append a placeholder comment (e.g., `# [section_name unavailable]`), continue assembly
- Preserve the final `prepend_safeguard(assembled)` call -- it must always execute

**Must NOT do:**
- Do not change the function signature
- Do not change the return type
- Do not skip the safeguard prepend on any failure path

**Acceptance criteria:**
- [x] `python -m py_compile backend/routers/chats.py` passes

**Verify:** `python -m py_compile backend/routers/chats.py`

---

### Task 13: Extract export_chat helpers

**File:** `backend/routers/chats.py:805-926`

**What to do:**
- Extract `write_export_file(content, target_dir, initial_filename) -> pathlib.Path` -- handles file write and returns path
- Extract `ai_rename_file(file_path, target_dir, ts, user_sample, provider, model) -> tuple[pathlib.Path, bool]` -- handles AI title generation, slug creation, collision loop, rename. Returns (final_path, ai_renamed)
- Simplify `export_chat` to call these helpers

**Must NOT do:**
- Do not change the export endpoint's response shape
- Do not change the audit logging

**Acceptance criteria:**
- [x] `python -m py_compile backend/routers/chats.py` passes

**Verify:** `python -m py_compile backend/routers/chats.py`

---

### Task 14: Split memory_tools.py into modules

**File:** `backend/services/memory_tools.py:1-567`

**What to do:**
- Create `backend/services/memory_extraction.py` with:
  - `_EXTRACTION_SYSTEM_PROMPT`
  - `extract_from_exchange()`
  - `_parse_extraction_response()`
- Create `backend/services/memory_hooks.py` with:
  - `_post_tool_memory_hook()`
  - `register_memory_hooks()`
  - `run_background_extraction()`
  - `_EXTRACTION_MIN_TEXT_LENGTH`
- Keep `backend/services/memory_tools.py` with:
  - `manage_memory()`, `search_memory()`
  - Tool specs and registries (`MEMORY_TOOLS`, `MEMORY_TOOL_FUNCTIONS`, etc.)
  - Re-export `extract_from_exchange`, `run_background_extraction`, and `register_memory_hooks` for backward compat
- Update imports in `main.py` to `from services.memory_hooks import register_memory_hooks`
- Update imports in `services/inference_job.py` to `from services.memory_hooks import run_background_extraction`
- Keep `__all__` unchanged (re-exports handle any unknown third-party importers)

**Must NOT do:**
- Do not change any function signatures
- Do not change the `__all__` exports from `memory_tools.py` (backward compat)

**Acceptance criteria:**
- [x] `python -m py_compile backend/services/memory_tools.py` passes
- [x] `python -m py_compile backend/services/memory_extraction.py` passes
- [x] `python -m py_compile backend/services/memory_hooks.py` passes
- [x] `grep -rn "from services.memory_tools import" backend/` shows no broken imports

**Verify:** `python -m py_compile backend/services/memory_tools.py backend/services/memory_extraction.py backend/services/memory_hooks.py`

---

### Task 15: Extract useStreamOrchestrator send helpers

**File:** `frontend/src/hooks/useStreamOrchestrator.js:406-519`

**What to do:**
- Extract `createChatIfNeeded()` -- the "create chat if no active chat" block duplicated at lines 428-455 (durable) and 475-511 (SSE). The helper returns the resolved chat ID. The SSE path must set `streamingChatRef.current = chatId` after the helper returns; the durable path does NOT set this ref (it uses `durable` instead)
- Extract `beginStream(content, sourceIds)` -- sets up `pendingSend`, `beginStreamUi`, `setStreamText('')`, `setOptimisticUser`
- Extract `handleStreamError(e, content)` -- error cleanup: reset state, set sendError, restore draft
- Simplify `send()` to call these helpers in each path

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)
- Do not change the public callback signatures returned by the hook

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] `grep -rn useStream frontend/src/` shows no new call sites
- [x] Streaming smoke test: send a message in a chat, verify response streams correctly

**Verify:** `cd frontend && npm run build`

---

### Task 16: Extract useStreamOrchestrator runStream callbacks

**File:** `frontend/src/hooks/useStreamOrchestrator.js:298-404`

**What to do:**
- Extract named callback builders: `makeOnToken()`, `makeOnSearchSources()`, `makeOnRagContext()`, `makeOnPhase()`, `makeOnTitleUpdate()`, `makeOnDone()`, `makeOnError()`
- Each builder returns a stable callback (use useCallback or define outside runStream)
- Pass built callbacks to `consumeStream`

**Must NOT do:**
- Do not modify `useStream.js` (hard rule #2)
- Do not change the callback behavior

**Acceptance criteria:**
- [x] `cd frontend && npm run build` passes
- [x] `grep -rn useStream frontend/src/` shows no new call sites
- [x] Streaming smoke test: send a message, verify all stream phases render correctly

**Verify:** `cd frontend && npm run build`
