# Proposal: lift-context-pruning

**Date:** 2026-06-13
**Status:** proposed

## Summary

Three targeted improvements to HLH's context-management pipeline, derived from
a feasibility analysis of the Fission-AI/DCP dynamic-context-pruning plugin
(validation report: `/home/samkintop/opt/forks/_hlh_lift/validation/G.md`).
Two of the three items are genuine lifts from DCP's protected-content-pinning
and priority-map patterns. The third (G.3) is a latent bug uncovered during the
analysis: `compaction.py` and `pruning.py` both write `chats.pruning_summary`
sequentially with no coordination, so the second service silently overwrites the
first.

G.3 is a hard prerequisite for G.1 and must ship first or in the same batch.

## Motivation

**G.3 - Silent summary overwrite (BUG, PREREQUISITE)**

In `backend/services/inference_job.py` (lines 464-476) both services run
back-to-back after every inference response. `compaction.py` fires first
(token-pressure triggered at 85% of `ctx_max`), writes a new `pruning_summary`,
then `pruning.py` fires (message-count triggered at threshold=40), reads the
same column, overwrites it with its own summary. On any turn where both triggers
fire simultaneously, compaction's output is silently discarded. Additionally,
pruning.py fetches all messages (including those just soft-deleted by compaction)
when building its transcript, so it may re-summarize content that compaction
already summarized.

**G.1 - Critical-fact pinning (HIGH value)**

Both services ask the LLM to "preserve key medical facts" in the prompt text,
but the LLM can still paraphrase or drop a specific lab value, date, or dosage.
DCP's `appendProtectedUserMessages` and `appendProtectedProtectedInfo` solve the
analogous problem by appending verbatim protected content after the generated
summary. In HLH's health-record domain, the equivalent is: lab values with
units, explicit dates (ISO or US formats), diagnoses, and medication dosages.
These should be extracted with regex from the head messages before summarization
and appended as a `## PRESERVED FACTS` block after the LLM-generated text.

Because `compaction.py` uses `resolve_bundled_chat_provider()` and silently
no-ops on external-tier deployments, fact-pinning placed only there would be
invisible to external-tier users. The fix: implement fact-pinning as a shared
helper and call it from pruning.py's summary assembly as well.

**G.2 - Priority-aware head selection (MEDIUM value)**

`compaction.py` always compacts the N oldest messages regardless of their token
weight. A one-line exchange and a 2000-token document paste are treated
identically. DCP's `buildPriorityMap` scores by token count. HLH can approximate
this with `len(text) // 4` before choosing the compaction boundary.

## Scope

| ID  | File(s) touched                                   | Type               |
|-----|---------------------------------------------------|--------------------|
| G.3 | `backend/services/compaction.py`, `backend/services/pruning.py`, `backend/services/inference_job.py` | Bug fix (summary ownership) |
| G.1 | `backend/services/compaction.py`, `backend/services/pruning.py` (new shared helper `_extract_medical_facts`) | Feature (fact pinning) |
| G.2 | `backend/services/compaction.py` | Enhancement (priority head selection) |

No schema changes. No new Python dependencies. No frontend changes. No new API
endpoints.

## Out of scope

- LLM-directed compress_range / compress_message tool architecture (requires
  tool-call plumbing HLH does not have)
- Nudge injection and message-ID tagging (depend on tool-use architecture)
- Manual slash-command subsystem
- Tool-output deduplication and purge-errors (HLH has no tool-call messages in
  context)
- Sub-agent result injection
- Migrating to tiktoken for accurate token counting (tracked as a blocking
  unknown; char/4 heuristic is acceptable for this batch)

## Risk

Low overall. All three items touch only the post-inference background path
(`inference_job.py` steps 8 and 9). Failures in both services are already caught
by the surrounding `try/except` blocks and log rather than raise. G.3 fixes a
silent data-loss bug; the worst case before the fix is compaction's summary
being overwritten, which is the current behavior. G.1 and G.2 are additive.

## Blocking unknowns (carried from G.md)

- Token counting accuracy: char/4 heuristic used for G.2; accuracy on
  multilingual or abbreviation-heavy medical content is unvalidated. Accepted
  for this batch; a tiktoken upgrade is a future improvement.
- Medical fact regex coverage: regex patterns for G.1 must be validated manually
  against real health records. No test runner exists; verification is manual.
- External-tier visibility for G.1: resolved by the design (shared helper called
  from both services).
