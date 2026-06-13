# Proposal: quick-wins-cleanup

**Date:** 2026-06-12
**Status:** proposed

## Summary

A batch of seven small, targeted fixes across backend and frontend. Each fix is
isolated to a single file (or a single matched pair of files). No schema changes
except one idempotent DROP. No new dependencies. All items were identified through
static analysis and grep-confirmed as having zero external consumers where
applicable.

## Motivation

These issues fall into three categories:

**Data correctness bugs** (A2, A9) cause silent runtime failures. A2 crashes
every source-selection write because the NOT NULL `position` column is omitted
from the INSERT. A9 leaks contextvars tokens because the hook context is set but
never reset, which silently corrupts context propagation under concurrent requests.

**Dead code** (S4, S10) adds maintenance surface. `process_pool.py` and the
`ai-elements` component suite are fully unreferenced and should be deleted so
future searchers are not misled.

**Race conditions** (C4, C7, C9) cause intermittent incorrect behavior that is
hard to reproduce in manual testing. C4 can delete a new pull's cancel event
when a concurrent task completes. C7 silently drops a resume call when switching
chats while the previous chat is still busy. C9 re-downloads a model that is
already ready.

**Schema hygiene** (S8) removes a HNSW index and table for a subsystem
(MedSigLIP) that was removed in v1.2.11. The table is confirmed empty; the DROP
is idempotent.

## Scope

| ID  | File(s) touched                                               | Type              |
|-----|---------------------------------------------------------------|-------------------|
| A2  | `backend/routers/chats.py`, new `backend/scripts/verify_source_selection.sh` | Bug fix |
| A9  | `backend/routers/chats.py`                                    | Bug fix           |
| S4  | `backend/services/process_pool.py` (delete)                   | Dead code removal |
| S8  | `backend/schema.sql`                                          | Schema hygiene    |
| S10 | `frontend/src/components/ai-elements/` (delete directory)     | Dead code removal |
| C4  | `backend/services/model_puller.py`                            | Race condition    |
| C7  | `frontend/src/hooks/useStreamOrchestrator.js`, `frontend/src/hooks/useDurableChat.js` | Race condition |
| C9  | `backend/services/model_puller.py`                            | Race condition    |

## Out of scope

- No provider, auth, or RAG changes.
- No new API endpoints.
- No frontend routing changes.
- No changes to `backend/schema.sql` CHECK constraints or existing columns.

## Risk

Low overall. Each fix touches a self-contained region. The two model_puller fixes
(C4, C9) share a file but affect different code paths within `pull_model`. The S8
DROP is idempotent and cannot affect existing data because the table is empty.
