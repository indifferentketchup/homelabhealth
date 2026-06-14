# Design: lift-context-pruning

**Date:** 2026-06-13

---

## G.3 - Summary ownership and coordination fix

### Problem (from code evidence)

`backend/services/inference_job.py` lines 464-476:

```python
# 8. Compaction
try:
    from services.compaction import maybe_compact
    await maybe_compact(chat_id, prompt_tokens_val, ctx_max)
except Exception as exc:
    logger.error("inference_job: compaction failed: %s", exc)

# 9. Pruning
try:
    from services.pruning import summarize_and_compress
    await summarize_and_compress(str(chat_id), pool)
except Exception as exc:
    logger.error("inference_job: pruning failed: %s", exc)
```

Both services write `chats.pruning_summary` with no coordination. Each reads
the existing summary before running and passes it to the LLM as rolling context.
When both triggers fire on the same turn:

1. `maybe_compact` reads `pruning_summary = "S_prev"`, generates `"S_compact"`,
   writes it back.
2. `summarize_and_compress` re-reads `pruning_summary` -- but the `chat` row was
   fetched from the DB connection acquired *before* the compaction `UPDATE`
   committed if running under the same pool.

In practice asyncpg returns a fresh connection from the pool for each
`pool.acquire()` call, so pruning.py does see the updated summary. The more
significant problem is that pruning.py fetches ALL messages with no
`compacted_at IS NULL` filter (`pruning.py` line 102):

```python
rows = await conn.fetch(
    """
    SELECT id, role, content, created_at
    FROM messages
    WHERE chat_id = $1::uuid
    ORDER BY created_at ASC, id ASC
    """,
    chat_id,
)
```

This means pruning.py's transcript includes rows already soft-deleted by
compaction (`compacted_at IS NOT NULL`). The summary it generates then
overwrites compaction's finer summary with content that double-counts
soft-deleted messages.

### Design decision: ownership split

- `compaction.py` owns `pruning_summary` for token-pressure-triggered runs.
- `pruning.py` owns `pruning_summary` for message-count-triggered runs.
- The coordination rule: `pruning.py` must exclude `compacted_at IS NOT NULL`
  rows from its transcript so it does not re-summarize already-compacted
  content.
- `inference_job.py` calls compaction first; pruning reads the post-compaction
  state of the table.

This is the minimal change. It avoids reorganizing the call order (G.3 is
already a bug fix; a larger restructure is deferred with a YAGNI gate).

### Fix

In `pruning.py` `summarize_and_compress`, change the `SELECT` on line 102 to
add `AND compacted_at IS NULL`:

```python
rows = await conn.fetch(
    """
    SELECT id, role, content, created_at
    FROM messages
    WHERE chat_id = $1::uuid AND compacted_at IS NULL
    ORDER BY created_at ASC, id ASC
    """,
    chat_id,
)
```

Also update the `COUNT` query on line 96 to match, so the `actual` count used
against `threshold` is only non-compacted messages:

```python
count_row = await conn.fetchrow(
    "SELECT COUNT(*)::int AS c FROM messages WHERE chat_id = $1::uuid AND compacted_at IS NULL",
    chat_id,
)
```

These two changes ensure pruning.py operates only on the live (non-compacted)
message set, preventing double-summarization and summary overwrite.

### Guardrails

- Must NOT reorder the compaction/pruning calls in `inference_job.py` beyond
  what is documented here; that restructure is deferred.
- Must NOT add a distributed lock or cross-service coordination mechanism;
  the sequential call order plus the filter fix is sufficient.
- Must NOT change the pruning hard-delete behavior (rows with
  `compacted_at IS NOT NULL` remain deleted by the existing logic that only
  deletes from `to_prune`, which now excludes them).

---

## G.1 - Critical-fact pinning (shared helper)

### Design

Add a module-level function `_extract_medical_facts(text: str) -> list[str]`
in `compaction.py`. It will also be importable by `pruning.py`.

The function applies regex patterns against the input text and returns a
deduplicated list of matched spans. The patterns target:

- **Lab values with units**: e.g. `HbA1c 7.2%`, `A1C = 7.2`, `TSH 2.4 mIU/L`,
  `eGFR 58 mL/min`, `BP 120/80`, `glucose 94 mg/dL`
- **Explicit ISO and US dates**: `2026-04-15`, `04/15/2026`, `April 15, 2026`
- **Diagnoses / ICD-adjacent terms**: pattern is practical -- lines containing
  "diagnosed with", "diagnosis:", "impression:", followed by a capitalized noun
  phrase
- **Medication dosages**: `metformin 500mg`, `lisinopril 10 mg`, `aspirin 81mg`

The function returns the list sorted by order of appearance (not deduplicated
within the same surface form since the same fact may appear in multiple messages
and both occurrences should pin).

In both `_generate_summary` (compaction.py) and `summarize_and_compress`
(pruning.py), after the LLM summary is returned and non-empty, append the
preserved-facts block:

```
## PRESERVED FACTS
(extracted from messages being summarized; treat as ground truth)
- HbA1c 7.2% on 2026-04-15
- ...
```

The block is appended to `summary` before it is written to `chats.pruning_summary`.

Update `SUMMARY_SYSTEM_PROMPT` in `compaction.py` to reference the block:

```
"Summarize the following conversation for context continuity. "
"Preserve: key medical facts, test results mentioned, dates discussed, "
"decisions made, and action items. Be concise but complete. "
"A PRESERVED FACTS block will be appended after your summary -- "
"treat those verbatim facts as authoritative ground truth."
```

The pruning.py inline summary prompt (in `_openai_summarize`) must receive the
same instruction addendum.

### Placement decision

The `_extract_medical_facts` helper lives in `compaction.py` because that module
already handles the head-text assembly step. `pruning.py` calls it via a direct
import:

```python
from services.compaction import _extract_medical_facts
```

This is a private import (`_` prefix) by convention. If the function grows into
a shared utility, it can be promoted to `services/context_utils.py` in a future
batch (YAGNI gate: one caller for now).

### Fact-pinning for external-tier users

`compaction.py:_generate_summary` calls `resolve_bundled_chat_provider()` and
returns `None` on external-tier deployments, so the summarize step is skipped
entirely there. Fact-pinning is appended to the LLM's output, so it only runs
when there is a summary. For external-tier users, pruning.py is the only
active summarization path; fact-pinning applied in pruning.py covers them.

### Guardrails

- Must NOT use `re.MULTILINE | re.IGNORECASE | re.DOTALL` combinatorially in a
  single pattern that can catastrophically backtrack on large inputs. Each
  pattern is bounded (max match length ~120 chars via `{1,40}` quantifiers on
  capturing groups).
- Must NOT raise on empty input; return `[]`.
- Must NOT bloat the summary beyond 512 chars of fact lines per invocation.
  Cap at 20 extracted facts with longest-match priority.

---

## G.2 - Priority-aware head selection

### Design

In `compaction.py` `_run_compaction`, after building `head = rows[:-tail_count]`,
re-sort the head by estimated token weight descending before building
`head_lines` and `head_ids`. This means the most expensive messages (by length)
are compacted in the current pass. The tail (most recent `TAIL_TURNS * 2` rows)
is never touched.

The token estimate is `len(plain_text) // 4` (char/4 heuristic). This is
computed during the decrypt loop.

Implementation sketch:

```python
# Decrypt head and compute weight
head_entries = []
for r in head:
    plain = decrypt_column(r["content"], str(r["id"]))
    weight = len(plain) // 4
    head_entries.append((r, plain, weight))

# Sort by weight descending (compact most expensive first)
head_entries.sort(key=lambda e: e[2], reverse=True)

head_lines = [f"[{e[0]['role']}]: {e[1]}" for e in head_entries]
head_text = "\n".join(head_lines)
head_ids = [e[0]["id"] for e in head_entries]
```

The summary is generated from this re-ordered transcript. The `compacted_at`
update uses `head_ids` as before. Order within the summary prompt is now
most-expensive-first rather than chronological, which is acceptable for a
summarization task (the LLM does not need chronological order to produce a
coherent summary).

### Guardrails

- Must NOT change the tail selection; `rows[:-tail_count]` is preserved.
- Must NOT change the `UPDATE messages SET compacted_at = NOW()` logic; only
  the presentation order for the LLM prompt changes.
- The char/4 heuristic is documented in a comment in the code. Do NOT treat it
  as authoritative token count; it is an approximation.

---

## Dependency and ordering

G.3 must be implemented before or alongside G.1. The PRESERVED FACTS block is
appended to `summary` in both services; if summary ownership is not fixed first,
the block may itself be overwritten by the second service. The recommended
implementation order: G.3 first, then G.1, then G.2 (G.2 is independent but
benefits from testing in the same pass).

## Backward compatibility

- No schema changes. `pruning_summary TEXT` column already exists
  (`schema.sql` line 84).
- No new DB columns or tables.
- No new API endpoints.
- No frontend changes.
- The `compacted_at IS NULL` filter in pruning.py is additive; it only reduces
  the set of rows pruning sees. It will not break anything on existing DBs where
  no rows have `compacted_at IS NOT NULL` (pruning fires before compaction on
  those).

## Implementation notes

### G.3 - Mechanism is threshold-gated serialization, not ownership split

The design section "ownership split" overstated mutual exclusion. The actual
mechanism is threshold-gated serialization: after compaction marks N messages
`compacted_at = NOW()`, pruning's COUNT query (with the IS NULL filter) returns
only the remaining non-compacted rows. In the common case (40-message chat, 32
compacted, tail=8 kept), non-compacted count drops below the 40-message
threshold and pruning exits early without writing. This is the effective
prevention of double-summarization -- it relies on the threshold, not on code
that explicitly blocks writes. The edge case (enough messages remain after
compaction to still trigger pruning) still causes an overwrite; the YAGNI gate
on explicit mutual exclusion is intentional and documented.

### G.1-3 (V2 fix) - Decrypted transcript required for fact extraction in pruning.py

The original plan called `_extract_medical_facts(transcript)` where `transcript`
was assembled from `r['content']` without decryption. When `HLH_MASTER_KEY` is
set, `r['content']` is AES-GCM ciphertext and the regex returns nothing. The
implementation builds a separate `decrypted_transcript` using `decrypt_column`
per row before calling `_extract_medical_facts`. The `bundle` variable sent to
the LLM is NOT changed; fixing that pre-existing issue is out of scope for this
batch.

### G.1-1 (V1 fix) - Pattern 1 separator extended; Pattern 2 trailing \\b dropped

Pattern 1 separator extended from `[=:]` to `[=:\\s]` so `HbA1c 7.2%` (space
separator) matches. Pattern 2 trailing `\\b` dropped so `%` at end-of-span
matches correctly. Both fixes verified by a python3 regex test at
implementation time.

## YAGNI deferred

- Promote `_extract_medical_facts` to `services/context_utils.py`: deferred
  until there are two or more callers.
- Replace char/4 heuristic with tiktoken: deferred until measurable accuracy
  gap confirmed on real conversations.
- Restructure compaction/pruning into a single unified context-manager service:
  deferred; G.3's filter fix is sufficient to remove the data-loss bug.
- Add configurable fact-pinning patterns via `global_settings`: deferred; regex
  set is hardcoded for now, change trigger is user-reported missed fact category.
