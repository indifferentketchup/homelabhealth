# Delta spec: rag-priority-invariant (A4)

**Date:** 2026-06-12

## ADDED Requirements

### Requirement: Priority sources SHALL bypass BM25 prefiltering

`retrieve_context` SHALL partition source IDs into `priority_set` (from `priority_source_ids`) and `non_priority_ids` (all other workspace sources). BM25 prefiltering SHALL operate only on `non_priority_ids`. Priority sources SHALL NEVER be passed to `_bm25_prefilter`.

#### Scenario: Priority source chunks are not filtered by BM25

- **WHEN** `retrieve_context` is called with `priority_source_ids` containing source S
- **AND** BM25 is enabled
- **THEN** source S SHALL NOT be included in the `_bm25_prefilter` call
- **AND** chunks from source S SHALL be candidates for the priority query regardless of BM25 score

#### Scenario: General pool BM25 uses only non-priority sources

- **WHEN** `retrieve_context` is called with both priority and non-priority sources
- **AND** BM25 is enabled
- **THEN** `_bm25_prefilter` SHALL receive only `non_priority_ids`
- **AND** the returned `bm25_ids` SHALL contain only non-priority source chunks

### Requirement: Priority query SHALL not apply BM25 filter

The priority query SHALL fetch chunks from `priority_set` sources ordered by vector cosine distance with no `AND sc.id = ANY(bm25_ids)` clause. All chunks from priority sources with non-null embeddings are candidates, subject only to `TOP_K_RETRIEVE` ordering.

```sql
SELECT sc.id, sc.text, sc.source_id, s.name AS source_name
FROM source_chunks sc
JOIN sources s ON s.id = sc.source_id
WHERE sc.source_id = ANY($3::uuid[])
  AND sc.embedding IS NOT NULL
ORDER BY sc.embedding <=> $2::vector
LIMIT $1
```

#### Scenario: Priority source with low BM25 score still contributes context

- **WHEN** a priority source S has chunks whose keywords score near zero against the query
- **THEN** chunks from source S SHALL still appear in the priority query results ordered by vector distance

#### Scenario: Priority source without BM25 tokens still contributes context

- **WHEN** the query has no tokens that overlap with priority source S content
- **AND** source S has chunks with non-null embeddings
- **THEN** at least one chunk from source S SHALL appear in the final RAG context (subject to `TOP_K_RETRIEVE` and `TOP_AFTER_RERANK` caps)

### Requirement: General pool SHALL use non-priority source IDs

The general pool vector query SHALL operate on `non_priority_ids` (not the full `source_ids` list) to avoid overlap with the priority query. This makes the partition clean: each query operates on a distinct, non-overlapping source set.

#### Scenario: General pool excludes priority sources

- **WHEN** `retrieve_context` is called with priority sources
- **THEN** the general pool query SHALL use `non_priority_ids` as its source filter
- **AND** the dedup at the merge step SHALL be retained as a safety net even though the two queries operate on disjoint sets

#### Scenario: No priority sources means full workspace is non-priority

- **WHEN** `retrieve_context` is called with no `priority_source_ids`
- **THEN** `non_priority_ids` SHALL equal the full `source_ids` list
- **AND** BM25 prefiltering SHALL operate on the full workspace source set

### Requirement: Priority chunks SHALL bypass reranker score gate

Priority chunks SHALL bypass the `rag_rerank_score_min` gate in the final merge step. A priority chunk with a low reranker score is still included. This is intentional: the user explicitly attached the source and expects it consulted.

#### Scenario: Low reranker score does not exclude priority chunk

- **WHEN** a priority chunk's reranker score falls below `rag_rerank_score_min`
- **THEN** the chunk SHALL still be included in the final context
- **AND** priority chunks SHALL be placed first in the merged list before `TOP_AFTER_RERANK` cap

### Requirement: BM25 fallback SHALL not affect priority invariant

If `_bm25_prefilter` returns `None` (query has no tokens, all chunks scored zero, or a DB error), `bm25_ids` stays `None` and the general pool query SHALL run without any BM25 filter. The priority invariant SHALL remain unaffected because priority sources never depended on the BM25 path.

#### Scenario: BM25 returns None does not change priority behavior

- **WHEN** `_bm25_prefilter` returns `None`
- **THEN** the general pool query SHALL run without `bm25_ids` filter
- **AND** the priority query SHALL continue operating on `priority_set` as before
