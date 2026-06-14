# Delta spec: priority-compaction (G.2)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: _run_compaction SHALL select the compaction head by estimated token weight

`_run_compaction` in `backend/services/compaction.py` SHALL estimate the token
weight of each head message as `len(plain_text) // 4` and use that estimate as
a budget heuristic. When the head exceeds `HEAD_SUMMARY_TOKEN_BUDGET`, the
lowest-weight head entries SHALL be dropped first until the remaining head fits
within budget. The surviving head entries SHALL be rendered in their original
chronological order in `head_text`.

The head selection (`rows[:-tail_count]`) SHALL remain unchanged. The source
comment SHALL document that the char/4 heuristic is only an approximation and is
not an accurate token count.

#### Scenario: Lowest-weight messages are dropped before heavier ones

- **WHEN** the head contains messages of different lengths and compaction must
  drop at least one message to fit the budget
- **THEN** the shortest message SHALL be dropped before a longer message
- **AND** the surviving messages SHALL remain in chronological order in `head_text`

#### Scenario: Tail messages are never reordered or compacted

- **WHEN** `_run_compaction` runs
- **THEN** the last `TAIL_TURNS * 2` messages from the ordered fetch SHALL NOT
  be included in `head_ids`
- **AND** those rows SHALL NOT receive a `compacted_at` update

#### Scenario: All head messages are still marked compacted regardless of drop order

- **WHEN** priority sorting reorders the head entries
- **THEN** `head_ids` SHALL contain the IDs of all messages in `head` (the
  unsorted boundary set), not just the heaviest ones
- **AND** `UPDATE messages SET compacted_at = NOW() WHERE id = ANY($1::uuid[])`
  SHALL include every head message ID
