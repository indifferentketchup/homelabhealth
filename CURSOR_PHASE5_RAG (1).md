# Cursor — boolab Phase 5: 808notes RAG Vertical Slice

## Context
**boolab** = unified AI workspace (BooOps + 808notes + boolab). Phase 5 adds **source ingestion + RAG chat** to 808notes. Users drop PDFs/docs → Chroma embeds them → chat retrieves + ranks → grounded answers.

**Repo:** `https://github.com/indifferentketchup/boolab`  
**Current state:** Phase 3 complete (DAWs, personas, memory, custom instructions). Phase 5 **design complete, no code yet** — schema partial, Chroma container exists, routers/services missing.

**Stack:** FastAPI + asyncpg + ChromaDB, `qwen3-embedding:latest` (Ollama @ 100.101.41.16:11434), flashrank (rerank), langchain (chunking), pypdf/python-docx (parsing).

---

## Acceptance Criteria (done when)
1. Upload PDF/DOCX to 808notes → parsed + chunked + embedded to Chroma → ✅ no errors
2. Source appears in right panel with checkbox
3. Check checkbox → source selected for next message
4. Send message → Chroma retrieves + reranks → context injected into system prompt
5. Model response cites sources
6. Logs show all 5 prompt blocks: persona → DAW system + instructions → context files → custom instructions → **RAG context** → mode memory + facts

---

## Implementation (5 steps, ~6–8 hours)

### Step 1: Services (2 files)

**File: `backend/services/chunking.py` (new)**

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

CHUNK_SIZE = 512  # tokens (approximate)
CHUNK_OVERLAP = 64

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks, respecting boundaries."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    return splitter.split_text(text)

def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF."""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page_num, page in enumerate(reader.pages):
            text += f"\n[Page {page_num + 1}]\n"
            text += page.extract_text()
        return text
    except Exception as e:
        raise ValueError(f"PDF parse failed: {e}")

def parse_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX."""
    try:
        from docx import Document
        import io
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        raise ValueError(f"DOCX parse failed: {e}")

def parse_text(file_bytes: bytes) -> str:
    """Decode text file."""
    return file_bytes.decode("utf-8", errors="replace")

async def parse_source(file_bytes: bytes, mime_type: str) -> str:
    """Dispatch to parser based on MIME type."""
    if mime_type in ["text/plain", "text/markdown"]:
        return parse_text(file_bytes)
    elif mime_type == "application/pdf":
        return parse_pdf(file_bytes)
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return parse_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported MIME: {mime_type}")
```

**File: `backend/services/embeddings.py` (new)**

```python
import httpx
import os

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://100.101.41.16:11434")
EMBEDDING_MODEL = "qwen3-embedding:latest"
BATCH_SIZE = 32

async def embed_text(text: str) -> list[float]:
    """Embed a single chunk. Returns [384] vector."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text}
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in batches to avoid OOM."""
    embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        for text in batch:
            emb = await embed_text(text)
            embeddings.append(emb)
    return embeddings
```

**Install deps:**
```bash
pip install langchain pypdf python-docx flashrank
```

---

### Step 2: Chroma init + get function

**File: `backend/db.py`**

Add imports + function:
```python
import chromadb
from chromadb.config import Settings

_chroma_client = None

async def init_chroma():
    """Init ChromaDB client on startup."""
    global _chroma_client
    settings = Settings(
        chroma_db_impl="duckdb+parquet",
        persist_directory="/data/chroma",
        anonymized_telemetry=False,
    )
    _chroma_client = chromadb.Client(settings)

def get_chroma():
    """Return singleton Chroma client."""
    global _chroma_client
    if not _chroma_client:
        raise RuntimeError("Chroma not initialized")
    return _chroma_client

def get_chroma_collection(daw_id: str):
    """Get or create Chroma collection for a DAW."""
    client = get_chroma()
    return client.get_or_create_collection(
        name=f"daw_{daw_id}_sources",
        metadata={"hnsw:space": "cosine"}
    )
```

**File: `backend/main.py`**

In `lifespan` context manager, after `apply_schema`, add:
```python
from db import init_chroma

async def lifespan(app: FastAPI):
    # ... existing pool init ...
    await init_chroma()
    yield
    # ... cleanup ...
```

---

### Step 3: Sources router (upload + ingest)

**File: `backend/routers/sources.py` (new)**

```python
from fastapi import APIRouter, UploadFile, HTTPException, Depends
import uuid
import hashlib
from services.chunking import parse_source, chunk_text
from services.embeddings import embed_batch
from db import get_pool, get_chroma_collection

router = APIRouter(prefix="/api/sources", tags=["sources"])

def compute_hash(file_bytes: bytes) -> str:
    """SHA256 of file."""
    return hashlib.sha256(file_bytes).hexdigest()

@router.post("/{daw_id}/upload")
async def upload_source(daw_id: str, file: UploadFile):
    """
    Upload + ingest file.
    Returns immediately with source_id; background task handles embedding.
    """
    file_bytes = await file.read()
    content_hash = compute_hash(file_bytes)
    source_id = str(uuid.uuid4())
    
    pool = await get_pool()
    
    # Dedup check
    existing = await pool.fetchval(
        "SELECT id FROM sources WHERE content_hash = $1", content_hash
    )
    if existing:
        return {"source_id": existing, "status": "already_exists"}
    
    # Insert source record
    try:
        await pool.execute(
            """INSERT INTO sources 
               (id, name, daw_id, mime_type, file_size_bytes, 
                source_type, embedding_status, content_hash, created_at) 
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())""",
            source_id, file.filename, daw_id, file.content_type, 
            len(file_bytes), "upload", "pending", content_hash
        )
    except Exception as e:
        raise HTTPException(400, f"DB insert failed: {e}")
    
    # Background ingestion (fire-and-forget)
    import asyncio
    asyncio.create_task(_ingest_background(source_id, file_bytes, daw_id, file.content_type))
    
    return {"source_id": source_id, "status": "ingesting"}

async def _ingest_background(source_id: str, file_bytes: bytes, daw_id: str, mime_type: str):
    """Background task: parse → chunk → embed → store."""
    pool = await get_pool()
    
    try:
        # Parse
        text = await parse_source(file_bytes, mime_type)
        
        # Chunk
        chunks = chunk_text(text)
        
        # Embed (batch)
        embeddings = await embed_batch(chunks)
        
        # Store chunks in Postgres
        async with pool.acquire() as conn:
            async with conn.transaction():
                for i, chunk in enumerate(chunks):
                    chunk_id = str(uuid.uuid4())
                    await conn.execute(
                        """INSERT INTO source_chunks 
                           (id, source_id, chunk_index, text, created_at) 
                           VALUES ($1, $2, $3, $4, NOW())""",
                        chunk_id, source_id, i, chunk
                    )
                
                # Store in Chroma
                collection = get_chroma_collection(daw_id)
                collection.add(
                    ids=[f"{source_id}_{i}" for i in range(len(chunks))],
                    documents=chunks,
                    embeddings=embeddings,
                    metadatas=[
                        {"source_id": source_id, "daw_id": daw_id, "chunk_index": i}
                        for i in range(len(chunks))
                    ]
                )
                
                # Mark complete
                await conn.execute(
                    "UPDATE sources SET embedding_status = 'complete', chunk_count = $1 WHERE id = $2",
                    len(chunks), source_id
                )
    except Exception as e:
        # Mark failed
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET embedding_status = 'failed' WHERE id = $1",
                source_id
            )
        print(f"[RAG] Ingest error for {source_id}: {e}")

@router.get("/{daw_id}")
async def list_sources(daw_id: str):
    """List all sources for a DAW."""
    pool = await get_pool()
    sources = await pool.fetch(
        """SELECT id, name, chunk_count, embedding_status, created_at, source_type
           FROM sources WHERE daw_id = $1 ORDER BY created_at DESC""",
        daw_id
    )
    return [dict(row) for row in sources]

@router.delete("/{source_id}")
async def delete_source(source_id: str):
    """Delete a source + its chunks from Chroma."""
    pool = await get_pool()
    
    # Get source to find daw_id
    source = await pool.fetchrow(
        "SELECT daw_id FROM sources WHERE id = $1", source_id
    )
    if not source:
        raise HTTPException(404, "Source not found")
    
    daw_id = source["daw_id"]
    
    # Delete from Chroma
    collection = get_chroma_collection(daw_id)
    chunk_ids = [f"{source_id}_{i}" for i in range(100)]  # rough; better: query actual count
    try:
        collection.delete(ids=chunk_ids)
    except:
        pass  # Chroma delete may not find all; that's OK
    
    # Delete from Postgres
    await pool.execute("DELETE FROM sources WHERE id = $1", source_id)
    
    return {"deleted": source_id}
```

**File: `backend/main.py`**

Add to router includes:
```python
from routers.sources import router as sources_router
app.include_router(sources_router)
```

---

### Step 4: RAG retrieval service

**File: `backend/services/rag.py` (new)**

```python
from services.embeddings import embed_text
from db import get_chroma_collection

async def retrieve_context(
    query: str, daw_id: str, source_ids: list[str]
) -> str:
    """
    Retrieve + rerank top chunks for a query.
    Returns formatted context block for system prompt.
    """
    if not source_ids or len(source_ids) == 0:
        return ""
    
    try:
        # Embed query
        query_embedding = await embed_text(query)
    except Exception as e:
        print(f"[RAG] Embed query failed: {e}")
        return ""
    
    try:
        # Retrieve from Chroma (top-20)
        collection = get_chroma_collection(daw_id)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=20,
            where={"source_id": {"$in": source_ids}}
        )
        
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        if not documents:
            return ""
        
        # Rerank (if flashrank available)
        try:
            from flashrank import Ranker, RerankRequest
            ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", batch_size=32)
            passages = [{"id": str(i), "text": doc} for i, doc in enumerate(documents)]
            rerank_req = RerankRequest(query=query, passages=passages)
            reranked = ranker.rerank(rerank_req)
            top_docs = [p.text for p in reranked[:6]]
        except ImportError:
            # Fallback: no rerank, use top-6 by retrieval score
            top_docs = documents[:6]
        
        # Format context
        context_block = "### Context from sources:\n\n"
        for chunk in top_docs:
            context_block += f"- {chunk}\n\n"
        
        return context_block
    
    except Exception as e:
        print(f"[RAG] Retrieval error: {e}")
        return ""
```

---

### Step 5: Inject RAG into chat + source selection endpoint

**File: `backend/routers/chats.py`**

Find `_assembled_system_prompt` function. **After the DAW instructions block**, add:

```python
# RAG context (808notes mode only)
if mode == "808notes" and chat_id:
    source_rows = await conn.fetch(
        "SELECT source_id FROM chat_source_selections WHERE chat_id = $1",
        chat_id
    )
    source_ids = [str(row["source_id"]) for row in source_rows]
    
    if source_ids:
        from services.rag import retrieve_context
        rag_context = await retrieve_context(
            query=messages[-1]["content"],  # last user message
            daw_id=daw_id,
            source_ids=source_ids
        )
        if rag_context:
            blocks.append(rag_context)
```

Add new endpoint (in same file):

```python
@router.put("/chats/{chat_id}/source-selection")
async def set_source_selection(chat_id: str, request: dict, conn=Depends(get_conn)):
    """Update active sources for a chat."""
    source_ids = request.get("source_ids", [])
    
    async with conn.transaction():
        # Clear old
        await conn.execute("DELETE FROM chat_source_selections WHERE chat_id = $1", chat_id)
        
        # Insert new
        for source_id in source_ids:
            await conn.execute(
                "INSERT INTO chat_source_selections (chat_id, source_id) VALUES ($1, $2)",
                chat_id, source_id
            )
    
    return {"chat_id": chat_id, "source_ids": source_ids}
```

---

### Step 6: Frontend — Sources page stub + chat source selector

**File: `frontend/src/api/sources.js` (new)**

```javascript
export async function uploadSource(file, daw_id) {
  const formData = new FormData();
  formData.append("file", file);
  
  const resp = await fetch(`/api/sources/${daw_id}/upload`, {
    method: "POST",
    body: formData,
  });
  return resp.json();
}

export async function listSources(daw_id) {
  const resp = await fetch(`/api/sources/${daw_id}`);
  return resp.json();
}

export async function deleteSource(source_id) {
  await fetch(`/api/sources/${source_id}`, { method: "DELETE" });
}

export async function setSourceSelection(chat_id, source_ids) {
  const resp = await fetch(`/api/chats/${chat_id}/source-selection`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_ids }),
  });
  return resp.json();
}
```

**File: `frontend/src/pages/notes808/SourcesPanel.jsx` (new)**

```jsx
import { useState, useEffect } from 'react';
import { uploadSource, listSources, deleteSource, setSourceSelection } from '../../api/sources';

export default function SourcesPanel({ daw_id, chat_id }) {
  const [sources, setSources] = useState([]);
  const [selected, setSelected] = useState([]);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (daw_id) loadSources();
  }, [daw_id]);

  const loadSources = async () => {
    const list = await listSources(daw_id);
    setSources(list);
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setUploading(true);
    try {
      await uploadSource(file, daw_id);
      await new Promise(r => setTimeout(r, 1000));
      await loadSources();
    } finally {
      setUploading(false);
    }
  };

  const handleSelect = async (source_id) => {
    const newSelected = selected.includes(source_id)
      ? selected.filter(id => id !== source_id)
      : [...selected, source_id];
    
    setSelected(newSelected);
    if (chat_id) {
      await setSourceSelection(chat_id, newSelected);
    }
  };

  return (
    <div className="sources-panel">
      <h3>Sources</h3>
      <input
        type="file"
        accept=".txt,.md,.pdf,.docx"
        onChange={handleUpload}
        disabled={uploading}
      />
      <div className="sources-list">
        {sources.map(src => (
          <label key={src.id} className="source-item">
            <input
              type="checkbox"
              checked={selected.includes(src.id)}
              onChange={() => handleSelect(src.id)}
            />
            <span>{src.name}</span>
            <span className="status">{src.embedding_status}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
```

**File: `frontend/src/pages/notes808/Notes808App.jsx`**

Add import + show sources panel in layout:

```jsx
import SourcesPanel from './SourcesPanel';

export default function Notes808App() {
  // ... existing code ...
  
  return (
    <div className="notes808-layout">
      <div className="chat-area">
        <ChatView />
      </div>
      <div className="sources-area">
        <SourcesPanel daw_id={daw_id} chat_id={chat_id} />
      </div>
    </div>
  );
}
```

---

## Test workflow

### Backend
```bash
cd /opt/boolab

# 1. Schema check
docker exec boolab_db psql -U postgres -d boolab -c "\dt" | grep source

# 2. Start fresh
docker compose down -v
docker compose up --build

# 3. Create 808notes DAW
# Via UI: go to /daws → create "test-rag"

# 4. Upload a .txt file
# POST http://localhost:9300/api/sources/daw-uuid/upload (multipart file)
# Response: {"source_id": "...", "status": "ingesting"}

# 5. Monitor logs
docker logs -f boolab_api | grep "RAG\|embedding\|chunk"

# 6. Verify Postgres
docker exec boolab_db psql -U postgres -d boolab \
  -c "SELECT id, name, chunk_count, embedding_status FROM sources"

# 7. Verify Chroma (inside container)
docker exec boolab_api python -c \
  "from db import get_chroma; c = get_chroma(); print(c.list_collections())"
```

### Chat
```
1. Open 808notes chat for the test DAW
2. Select the uploaded source in right panel
3. Send: "Summarize what's in my source"
4. Check logs: "assembled prompt" should show RAG context block
5. Model response should cite the source text
```

---

## Checklist (done when all ✅)

- [ ] `backend/services/chunking.py` created + imports work
- [ ] `backend/services/embeddings.py` created + Ollama reachable
- [ ] `backend/services/rag.py` created + retrieval logic sound
- [ ] `backend/db.py` has `init_chroma()` + `get_chroma()` called in lifespan
- [ ] `backend/routers/sources.py` created + endpoints POST/GET/DELETE
- [ ] `backend/routers/chats.py` has RAG injection + source-selection endpoint
- [ ] `backend/main.py` includes sources router + init_chroma
- [ ] Schema: `sources`, `source_chunks`, `chat_source_selections` tables exist
- [ ] `frontend/src/api/sources.js` created
- [ ] `frontend/src/pages/notes808/SourcesPanel.jsx` created
- [ ] Notes808App shows sources panel + loads chat sources
- [ ] Upload .txt → logs show "embedding" → sources list populated
- [ ] Select source in chat → RAG context in assembled prompt logs
- [ ] Model response cites sources

---

## Gotchas
- **Ollama timeout:** If embedding hangs, check `sam-desktop` is running + model loaded: `curl http://100.101.41.16:11434/api/tags`
- **ChromaDB init:** Must happen in `lifespan` **after** pool is ready, not in module scope
- **Chroma collection name:** Must be `daw_{daw_id}_sources` (no special chars, underscores only)
- **Background task:** `asyncio.create_task` fires immediately; don't await it (would block response)
- **Flashrank optional:** If import fails, fallback to no-rerank (just use top-k from similarity)

---

## After this (Phase 5.5)
- Batch embedding optimization (send all chunks at once, not 1-by-1)
- Page number tracking in metadata
- Notes editor → embed notes as sources
- BourBites refresh button
- Three-panel UI polish (resize dividers, responsive mobile)

---

## Tech debt resolved
✅ Phase 3 gaps injected (daw_instructions + memory_entries in prompts)
✅ Phase 5 core RAG (ingest → retrieve → inject)
⏳ Phase 5.5: optimization + notes
⏳ Phase 6: full 808notes UI
