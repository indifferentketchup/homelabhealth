# Cursor — boolab Phase 5: RAG vertical slice (sources → Chroma → chat injection)

## Task
Implement the core RAG pipeline: upload a source file → parse/chunk/embed → store in Chroma → retrieve on chat → inject context into 808notes model responses. This is a **complete, but minimal** flow: text files only, simple chunking, one DAW per chat.

---

## Architecture (from RAG_PIPELINE.md)

### Ingestion (user uploads file)
```
Upload file (.txt, .md, .pdf, .docx)
    ↓ [parse_source] → extract text
    ↓ [chunk_text] → RecursiveCharacterTextSplitter (512 tokens, 64 overlap)
    ↓ [embed_chunks] → qwen3-embedding @ 100.101.41.16:11434 (batch 32)
    ↓ [store_chroma] → collection: daw_{daw_id}_sources
    ↓ SSE stream: {"stage": "...", "progress": ...}
```

### Query (user sends chat message)
```
Message + source_ids
    ↓ [embed_query] → qwen3-embedding
    ↓ [retrieve_chroma] → top-k 20 from daw_{daw_id}_sources, filter by source_id
    ↓ [rerank] → flashrank (keep top 6)
    ↓ [format_context] → "### Sources:\n[SOURCE: name]\nchunk\n\n..."
    ↓ [inject_system_prompt] → prepend to model call (in _assembled_system_prompt)
    ↓ [stream] → Ollama/Claude responds with context
```

---

## Schema (already in schema.sql)

```sql
-- Files uploaded by user
CREATE TABLE sources (
  id UUID PRIMARY KEY,
  name TEXT,
  source_type TEXT,  -- 'upload', 'note', 'bourbites'
  daw_id UUID REFERENCES daws(id),
  chunk_count INT,
  embedding_status TEXT,  -- 'pending', 'in_progress', 'complete', 'failed'
  created_at TIMESTAMP
);

-- Text chunks from sources
CREATE TABLE source_chunks (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES sources(id),
  chunk_index INT,
  text TEXT,
  page_number INT,
  created_at TIMESTAMP
);

-- User's manual notes
CREATE TABLE notes (
  id UUID PRIMARY KEY,
  daw_id UUID REFERENCES daws(id),
  title TEXT,
  content TEXT,
  created_at TIMESTAMP
);

-- Active sources for a specific chat
CREATE TABLE chat_source_selections (
  chat_id UUID REFERENCES chats(id),
  source_id UUID REFERENCES sources(id),
  PRIMARY KEY (chat_id, source_id)
);
```

ChromaDB collections: `daw_{daw_id}_sources`, `daw_{daw_id}_notes`

---

## Implementation (5 steps, ~6–8 hours total)

### Step 1: Embedding service (`backend/services/embeddings.py`)

```python
import httpx
import json
from typing import List

OLLAMA_BASE = "http://100.101.41.16:11434"
EMBEDDING_MODEL = "qwen3-embedding:latest"

async def embed_text(text: str) -> List[float]:
    """Embed a single text chunk. Returns [384] vector."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text}
        )
        return resp.json()["embedding"]

async def embed_batch(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    """Embed multiple texts in batches to avoid OOM."""
    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        for text in batch:
            emb = await embed_text(text)
            embeddings.append(emb)
    return embeddings
```

**Test:** `python -m pytest backend/tests/test_embeddings.py`

---

### Step 2: Chunking service (`backend/services/chunking.py`)

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> List[str]:
    """
    Split text into semantic chunks respecting sentence/paragraph boundaries.
    Chunk size in tokens (approximate, not exact).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    return splitter.split_text(text)

def parse_text_file(file_path: str) -> str:
    """Read .txt or .md file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_pdf(file_path: str) -> str:
    """Parse PDF using pypdf. Falls back to raw text if no PDF support."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page_num, page in enumerate(reader.pages):
            text += f"\n[Page {page_num + 1}]\n"
            text += page.extract_text()
        return text
    except ImportError:
        # PDF parsing not available; return placeholder
        return f"[PDF file: {file_path} — PDF parsing not installed]"

def parse_docx(file_path: str) -> str:
    """Parse .docx using python-docx."""
    try:
        from docx import Document
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except ImportError:
        return f"[DOCX file: {file_path} — python-docx not installed]"

def parse_source(file_path: str, mime_type: str) -> str:
    """Dispatch to correct parser based on file type."""
    if mime_type in ['text/plain', 'text/markdown']:
        return parse_text_file(file_path)
    elif mime_type == 'application/pdf':
        return parse_pdf(file_path)
    elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        return parse_docx(file_path)
    else:
        raise ValueError(f"Unsupported mime type: {mime_type}")
```

**Install deps:** `pip install langchain pypdf python-docx`

---

### Step 3: Source upload + ingestion (`backend/routers/sources.py`)

```python
from fastapi import APIRouter, UploadFile, File, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
import uuid
import json
from services.chunking import parse_source, chunk_text
from services.embeddings import embed_batch
from db import get_conn, get_chroma

router = APIRouter()

async def ingest_source_task(
    source_id: str, file_path: str, daw_id: str, mime_type: str, conn, chroma
):
    """Background task: parse → chunk → embed → store."""
    try:
        # Update status
        await conn.execute(
            "UPDATE sources SET embedding_status = 'in_progress' WHERE id = $1",
            source_id
        )
        
        # Parse
        text = parse_source(file_path, mime_type)
        
        # Chunk
        chunks = chunk_text(text, chunk_size=512, chunk_overlap=64)
        
        # Embed
        embeddings = await embed_batch(chunks)
        
        # Store chunks in Postgres
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO source_chunks 
                   (id, source_id, chunk_index, text) 
                   VALUES ($1, $2, $3, $4)""",
                chunk_id, source_id, i, chunk
            )
        
        # Store in Chroma
        collection_name = f"daw_{daw_id}_sources"
        collection = chroma.get_or_create_collection(name=collection_name)
        collection.add(
            ids=[f"{source_id}_{i}" for i in range(len(chunks))],
            documents=chunks,
            embeddings=embeddings,
            metadatas=[
                {
                    "source_id": source_id,
                    "daw_id": daw_id,
                    "chunk_index": i,
                    "page_number": None
                }
                for i in range(len(chunks))
            ]
        )
        
        # Update source status
        await conn.execute(
            "UPDATE sources SET embedding_status = 'complete', chunk_count = $1 WHERE id = $2",
            len(chunks), source_id
        )
        
    except Exception as e:
        await conn.execute(
            "UPDATE sources SET embedding_status = 'failed' WHERE id = $1",
            source_id
        )
        print(f"Ingestion error: {e}")

@router.post("/api/sources/upload")
async def upload_source(
    file: UploadFile,
    daw_id: str,
    background_tasks: BackgroundTasks,
    conn = Depends(get_conn),
    chroma = Depends(get_chroma)
):
    """
    Upload a file, trigger async ingestion pipeline, return immediately with SSE stream.
    """
    # Save file to disk
    source_id = str(uuid.uuid4())
    file_path = f"/data/sources/{daw_id}/{source_id}"
    
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    # Create source record
    await conn.execute(
        """INSERT INTO sources 
           (id, name, source_type, daw_id, embedding_status, created_at) 
           VALUES ($1, $2, $3, $4, $5, NOW())""",
        source_id, file.filename, 'upload', daw_id, 'pending'
    )
    
    # Start background task
    background_tasks.add_task(
        ingest_source_task,
        source_id, file_path, daw_id, file.content_type, conn, chroma
    )
    
    return {"source_id": source_id, "status": "ingesting"}

@router.get("/api/sources/{daw_id}")
async def list_sources(daw_id: str, conn = Depends(get_conn)):
    """List all sources for a DAW."""
    sources = await conn.fetch(
        """SELECT id, name, chunk_count, embedding_status, created_at 
           FROM sources WHERE daw_id = $1 ORDER BY created_at DESC""",
        daw_id
    )
    return sources
```

---

### Step 4: Retrieval service (`backend/services/rag.py`)

```python
from flashrank import Ranker, RerankRequest
from services.embeddings import embed_text

ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

async def retrieve_context(
    query: str,
    daw_id: str,
    source_ids: list,
    chroma,
    top_k: int = 6
) -> str:
    """
    1. Embed query
    2. Retrieve top-20 from Chroma (filtered by source_ids)
    3. Rerank with flashrank, keep top-k
    4. Format with attribution
    """
    if not source_ids:
        return ""
    
    # Embed query
    query_embedding = await embed_text(query)
    
    # Retrieve from Chroma
    collection = chroma.get_collection(name=f"daw_{daw_id}_sources")
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=20,
        where={"source_id": {"$in": source_ids}}
    )
    
    chunks = results['documents'][0] if results['documents'] else []
    if not chunks:
        return ""
    
    # Rerank
    passages = [{"id": str(i), "text": chunk} for i, chunk in enumerate(chunks)]
    rerank_req = RerankRequest(query=query, passages=passages)
    reranked = ranker.rerank(rerank_req)
    
    # Keep top-k
    top_chunks = [p.text for p in reranked[:top_k]]
    
    # Format context
    context = "### Context from sources:\n\n"
    for chunk in top_chunks:
        context += f"- {chunk}\n\n"
    
    return context
```

**Install deps:** `pip install flashrank`

---

### Step 5: Inject into 808notes chat (`backend/routers/chats.py`)

In the `_assembled_system_prompt` function, after DAW instructions block, **if mode is `808notes`**:

```python
# After DAW instructions block, add:

if mode == "808notes":
    # Fetch active source selection for this chat
    source_ids = await conn.fetch(
        "SELECT source_id FROM chat_source_selections WHERE chat_id = $1",
        chat_id
    )
    source_ids = [str(row['source_id']) for row in source_ids]
    
    if source_ids:
        # Retrieve context
        rag_context = await retrieve_context(
            query=messages[-1]["content"],  # last user message
            daw_id=daw_id,
            source_ids=source_ids,
            chroma=chroma,
            top_k=6
        )
        if rag_context:
            blocks.append(rag_context)
```

Also add endpoint for source selection:
```python
@router.put("/api/chats/{chat_id}/source-selection")
async def set_source_selection(
    chat_id: str,
    request: dict,  # {"source_ids": ["uuid1", "uuid2"]}
    conn = Depends(get_conn)
):
    """Update which sources are active for this chat."""
    source_ids = request.get("source_ids", [])
    
    # Clear old selection
    await conn.execute(
        "DELETE FROM chat_source_selections WHERE chat_id = $1",
        chat_id
    )
    
    # Insert new selection
    for source_id in source_ids:
        await conn.execute(
            "INSERT INTO chat_source_selections (chat_id, source_id) VALUES ($1, $2)",
            chat_id, source_id
        )
    
    return {"chat_id": chat_id, "source_ids": source_ids}
```

---

### Frontend: Sources page + chat source toggle

**File:** `frontend/src/pages/notes808/SourcesPage.jsx`

```jsx
import { useState, useEffect } from 'react';
import { uploadSource, listSources } from '../../api/sources';

export default function SourcesPage() {
  const [sources, setSources] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    fetchSources();
  }, []);

  const fetchSources = async () => {
    // Assumes daw_id is in URL or Zustand store
    const daw_id = new URLSearchParams(window.location.search).get('daw_id');
    const list = await listSources(daw_id);
    setSources(list);
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    const daw_id = new URLSearchParams(window.location.search).get('daw_id');
    
    setUploading(true);
    try {
      const { source_id } = await uploadSource(file, daw_id);
      setStatus(`Uploading ${file.name}...`);
      
      // Poll for completion
      const poll = setInterval(async () => {
        const updated = await listSources(daw_id);
        const src = updated.find(s => s.id === source_id);
        if (src?.embedding_status === 'complete') {
          clearInterval(poll);
          setSources(updated);
          setStatus(`✓ ${file.name} embedded (${src.chunk_count} chunks)`);
          setTimeout(() => setStatus(""), 3000);
        }
      }, 1000);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="sources-page">
      <h2>Knowledge Sources</h2>
      <input
        type="file"
        accept=".txt,.md,.pdf,.docx"
        onChange={handleUpload}
        disabled={uploading}
      />
      {status && <p>{status}</p>}
      <div className="sources-list">
        {sources.map(src => (
          <div key={src.id} className="source-item">
            <h4>{src.name}</h4>
            <p>{src.chunk_count} chunks • {src.embedding_status}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**File:** `frontend/src/components/chat/ChatView.jsx` — add source selector:

```jsx
// In chat view header:
<div className="source-selector">
  <label>Active sources:</label>
  <select multiple onChange={(e) => {
    const ids = Array.from(e.target.selectedOptions, opt => opt.value);
    setSourceSelection(chat_id, ids);
  }}>
    {sources.map(src => (
      <option key={src.id} value={src.id}>
        {src.name} ({src.chunk_count})
      </option>
    ))}
  </select>
</div>
```

---

## Test workflow

### 1. Local dev
```bash
cd /opt/boolab
docker compose up -d
# Create a DAW in 808notes
# Upload a .txt file (or markdown) from Sources page
# Check logs: docker logs -f boolab_api
# Should see: "parsing" → "chunking" → "embedding" → "complete"
```

### 2. Chat test
```
- Start a 808notes chat with that DAW
- Select the uploaded source in the source selector
- Send a message: "What's in this document?"
- Model should cite chunks from the source
```

### 3. Verify in logs
```bash
docker logs boolab_api | grep "assembled prompt"
# Should show RAG context block between DAW instructions and mode memory
```

---

## Acceptance criteria
✅ Upload endpoint accepts .txt, .md, .pdf, .docx  
✅ Ingestion chunks text + embeds with qwen3-embedding  
✅ Chunks stored in Postgres + Chroma with correct daw_id collection  
✅ Source selector in chat UI toggles sources active/inactive  
✅ RAG context injected into system prompt when sources selected  
✅ Model cites chunks in response  
✅ No errors in logs on upload, query, or stream  
✅ Background task completes even if connection closes  

---

## After this
- **Phase 5.5**: Reranking polish, batch embedding optimization, page number tracking
- **Phase 6**: Notes editor (create notes as sources), BourBites refresh button
- **Phase 7**: Full 808notes three-panel UI (sources + notes + chat)

---

## Cursor setup hints
- **Imports**: Make sure `from db import get_chroma` exists (singleton ChromaDB client)
- **ENV**: Ensure `OLLAMA_BASE`, `EMBEDDING_MODEL` are set in `.env` or hardcoded for local test
- **Deps**: `pip install langchain pypdf python-docx flashrank`
- **Schema**: Verify `sources`, `source_chunks`, `chat_source_selections` tables exist in `schema.sql`
