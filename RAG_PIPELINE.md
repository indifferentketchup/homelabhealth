# boolab — RAG Pipeline Design
Last updated: March 2026

## Overview
808notes uses a RAG (Retrieval-Augmented Generation) pipeline to ground AI responses in your uploaded sources. BooOps can optionally use the same pipeline when sources are attached to a DAW context file with the "embeddable" checkbox.

---

## Ingestion Pipeline (when a source is uploaded)

```
Upload file
    ↓
Parse to text
    ├── PDF       → pypdf
    ├── DOCX      → python-docx
    ├── TXT/MD    → raw read
    ├── HTML      → BeautifulSoup strip tags
    ├── CSV/XLSX  → pandas → markdown table
    ├── URL       → httpx fetch → BeautifulSoup
    └── Code      → raw read (preserve formatting)
    ↓
Chunk text
    → RecursiveCharacterTextSplitter
    → chunk_size: 512 tokens (configurable)
    → chunk_overlap: 64 tokens (configurable)
    → respects paragraph/sentence boundaries
    ↓
Embed chunks
    → POST http://100.101.41.16:11434/api/embeddings
    → model: qwen3-embedding:latest
    → batch in groups of 32 to avoid OOM
    ↓
Store in ChromaDB
    → collection: daw_{daw_id}_sources
    → document: chunk text
    → metadata: { source_id, daw_id, source_name, source_type, chunk_index, page_number }
    ↓
Update source record
    → embedding_status = 'complete'
    → chunk_count = N
```

Progress reported via SSE stream:
```
data: {"stage": "parsing", "progress": 0}
data: {"stage": "chunking", "progress": 20}
data: {"stage": "embedding", "progress": 40, "chunks_done": 5, "chunks_total": 23}
data: {"stage": "complete", "progress": 100}
```

---

## Query Pipeline (when user sends a message)

```
User message + active source IDs
    ↓
Embed query
    → POST /api/embeddings (qwen3-embedding)
    ↓
Retrieve from ChromaDB
    → collection: daw_{daw_id}_sources
    → filter: { source_id: { $in: [active_source_ids] } }
    → top_k: 20 (pre-rerank pool, configurable)
    ↓
Rerank (flashrank)
    → cross-encoder scores each chunk against query
    → keep top 6 (configurable top_k setting)
    ↓
Build context
    → format chunks with source attribution
    → prepend to system prompt:
      "Answer based on these sources:\n\n[SOURCE: filename]\n{chunk}\n\n..."
    ↓
Stream to LLM
    → Ollama or Claude API
    → include: system prompt + context + chat history (pruned)
    ↓
Stream response to frontend
```

---

## Context Pruning (shared by BooOps + 808notes)

Triggered when `message_count >= pruning_threshold` (default: 40).

```
Take messages[0..N-10]  (keep last 10 messages intact)
    ↓
Send to Ollama:
    "Summarize this conversation concisely, preserving key facts, decisions, and context:
     {messages}"
    ↓
Store summary in chats.pruning_summary
    ↓
Delete messages[0..N-10] from DB
    ↓
On next chat load, inject summary as first system message:
    "Previous conversation summary: {pruning_summary}"
```

Manual clear: deletes all messages, clears pruning_summary.

---

## ChromaDB Collections

```
daw_{daw_id}_sources    — all embedded source chunks for this DAW
daw_{daw_id}_notes      — notes that have been converted to sources
```

Notes converted to sources are chunked and embedded the same way as uploaded files.
`source_type = 'note'` in the metadata for attribution.

BourBites context (`source_type = 'bourbites'`) is fetched from
`http://100.114.205.53:8600/context`, parsed as markdown, chunked, and embedded
into `daw_{daw_id}_sources` with `source_type = 'bourbites'`.
Re-fetched and re-embedded on "Refresh BourBites" button click.

---

## Reranking (flashrank)

```python
from flashrank import Ranker, RerankRequest

ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

request = RerankRequest(
    query=user_query,
    passages=[{"id": chunk_id, "text": chunk_text} for ...]
)
results = ranker.rerank(request)
# results sorted by relevance score, take top_k
```

Reranking adds ~100-300ms latency. Toggle in 808notes settings if needed.

---

## Source Selection State

Stored in `chat_source_selections` table.
When user changes selection, frontend sends:
```
PUT /api/chats/{chat_id}/source-selection
{ "source_ids": ["uuid1", "uuid2"] }
```
Selection persists until changed. Applies to the next message sent, not retroactively.

Empty selection = no RAG (falls through to web search or general knowledge depending on toggle).

---

## Embedding Model Notes

- `qwen3-embedding:latest` running on sam-desktop (`100.101.41.16:11434`)
- 9.9GB VRAM when loaded — check if qwen3.5:9b is also loaded (Tweak uses it)
- `KEEP_ALIVE=30m` set on Ollama — model unloads after 30 min idle
- If embedding fails due to model not loaded, retry with 5s backoff x3
- Batch size 32 chunks per embedding call to avoid timeouts
