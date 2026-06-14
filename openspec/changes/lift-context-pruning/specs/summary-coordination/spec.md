# Delta spec: summary-coordination (G.3)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: pruning.py SHALL exclude compacted messages from its transcript and threshold count

`summarize_and_compress` in `backend/services/pruning.py` SHALL add
`AND compacted_at IS NULL` to both the COUNT query (line 96) and the message
SELECT query (line 102). Compacted rows (marked by `compaction.py` with
`compacted_at = NOW()`) SHALL NOT be included in pruning's transcript or in
the count compared against `pruning_threshold`.

This ensures that when both services run sequentially in `inference_job.py`
(steps 8 and 9), the second service (pruning) does not re-summarize content
already soft-deleted by the first service (compaction), and does not overwrite
compaction's more accurate summary with one built from stale data.

#### Scenario: Compacted messages are excluded from pruning transcript

- **WHEN** `maybe_compact` runs first and marks N messages with `compacted_at = NOW()`
- **AND** `summarize_and_compress` runs immediately after in the same inference job
- **THEN** the `rows` fetch in `summarize_and_compress` SHALL NOT include any row where `compacted_at IS NOT NULL`
- **AND** the `actual` count used to compare against `threshold` SHALL reflect only non-compacted messages

#### Scenario: Pruning threshold evaluated against live message count only

- **WHEN** a chat has 25 non-compacted messages and 20 compacted messages
- **AND** `pruning_threshold` is 40
- **THEN** `summarize_and_compress` SHALL treat `actual` as 25
- **AND** pruning SHALL NOT trigger (25 < 40)

#### Scenario: Both services fire on same turn without summary collision

- **WHEN** prompt token pressure exceeds 85% triggering compaction
- **AND** non-compacted message count equals or exceeds `pruning_threshold` after compaction
- **THEN** pruning's transcript SHALL contain only post-compaction live messages
- **AND** `pruning_summary` SHALL reflect the pruning pass built on non-compacted content
- **AND** no ERROR log lines for compaction or pruning SHALL appear in `docker logs hlh_api`
