# Proposal: lift-groundedness-eval

**Date:** 2026-06-13
**Status:** proposed

## Summary

Wire groundedness scoring into the chat response pipeline as a non-blocking async
background task. The eval router exists (`backend/routers/eval.py`) but is not
mounted in `main.py`, making all eval endpoints unreachable. A complete async judge
service module is already implemented; it only needs extraction and connection.

## Motivation

Every assistant response is currently stored with no signal about whether its
claims are supported by the retrieved context. On a personal health record app,
an ungrounded hallucination (e.g., a lab value not present in any source document)
is a patient-safety issue, not just a quality issue.

Two specific gaps block meaningful evaluation today:

1. **Eval router not mounted.** `backend/routers/eval.py` defines three eval
   endpoints (groundedness, helpfulness, retrieval-relevance) but none are
   reachable because the router is absent from `main.py`'s `include_router`
   chain. This is the prerequisite for all downstream work.

2. **No post-generation groundedness check.** After `rag.py` retrieves context
   and `chats.py` generates the assistant response, no code compares the response
   to the context it was grounded on. The `output_scan = scan_output(assistant_text)`
   call at `chats.py:1712` only runs regex-based PII/injection checks; it does not
   assess factual support.

3. **ResponseAnalysisBatch is a false-safety stub.** `safeguards_engine.py:685-696`
   defines a `process()` method that unconditionally marks every guideline as
   `was_followed=True`. This class is not called anywhere, but if it were wired
   without being fixed first, it would silently report full compliance for every
   response. The stub must be replaced before the class is wired.

## Approach

- **Step 0:** Mount the eval router in `main.py` (one line).
- **Step 1:** Extract `_call_llm_as_judge`, `_parse_eval_response`, and
  `_build_eval_response` from `eval.py` into a new `services/eval_judge.py`
  module so `chats.py` can import them without a circular dependency on the router.
- **Step 2:** Add `groundedness_score FLOAT` column to the `messages` table via
  idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Store violation strings
  in the existing `guard_flags` JSONB rather than a second JSONB column.
- **Step 3:** After the message INSERT in `chats.py`, fire an `asyncio.create_task`
  background task that calls the judge and writes `groundedness_score` and any
  violations back to the messages row. The task is gated by a
  `groundedness_eval_enabled` key in `global_settings` (default `false`) and a
  `groundedness_eval_sample_rate` key (default `1.0`). The task soft-fails on any
  error; it never raises into the response path.
- **Step 4:** Route judge calls to the bundled `gemma-tasks` slot (270M, 512-token
  context) when the bundled tier is active. On external tier, use the workspace
  provider. This avoids blocking the 4B/27B chat model during scoring.
- **Step 5:** Replace the `ResponseAnalysisBatch.process()` stub in
  `safeguards_engine.py` with a real async LLM call via the extracted
  `eval_judge.py` infrastructure. Do NOT wire this class into any call site in
  this change; fixing the stub is prerequisite to future wiring.

## Scope

| Step | File(s) touched | Type |
|------|-----------------|------|
| 0    | `backend/main.py` | Router mount (1 line) |
| 1    | `backend/services/eval_judge.py` (new), `backend/routers/eval.py` | Service extraction |
| 2    | `backend/schema.sql` | Idempotent schema addition |
| 3    | `backend/routers/chats.py` | Async background task |
| 4    | `backend/services/eval_judge.py` | Tasks-slot routing |
| 5    | `backend/services/safeguards_engine.py` | Stub replacement |

## Out of scope

- PII semantic judge (regex scan via `guard.py` is already live; semantic PII is
  deferred).
- Importing the `openevals` package (pulls langchain + langsmith; extract prompt
  text only, no package import).
- Wiring `ResponseAnalysisBatch` into any call site (fix stub only, no wiring).
- Inline/synchronous groundedness gate (latency on bundled CPU makes this
  infeasible; async/sampled is mandatory for bundled tier).
- Frontend score display (deferred; score is persisted and queryable, display is a
  separate UX change).
- Hallucination prompt for non-RAG paths (deferred; `{reference_outputs}` slot
  maps to nothing in the current data model).

## Risk

Medium. The eval router mount and schema column are low-risk (both are purely
additive). The background task in `chats.py` is the highest-risk edit: it runs
after message commit and must not leak exceptions back to the streaming response.
The `ResponseAnalysisBatch` stub replacement touches `safeguards_engine.py` but
adds no new call sites, limiting blast radius.

## Open decisions carried from D.md

- **Latency budget on bundled tier:** async background task is mandatory; inline
  judge is ruled out. Confirmed by D.md blocking unknown #1.
- **Judge output through reasoning_strip:** MedGemma wraps output in `<THINKING>`
  blocks. The judge call goes to `gemma-tasks` (Gemma 3 270M, not MedGemma) so
  `<THINKING>` wrap is not expected. Verify with a smoke test before shipping.
- **Storage:** dedicated `groundedness_score FLOAT` column for the numeric score
  (queryable, indexable); violations appended into `guard_flags` JSONB alongside
  existing guard scan results (avoids a second JSONB column).
