# Cursor — boolab: Tweak persona + multi-DAW RAG retrieval

## Task
Implement Tweak as a **persona** in boolab that automatically retrieves RAG context from **all DAW sources** (across all DAWs in a mode) plus BourBites context, and injects both into the system prompt when Tweak is selected.

---

## What's done
- ✅ Tweak DAW stubs in Tweak bot context
- ❌ Tweak persona not seeded in boolab database
- ❌ Multi-DAW RAG retrieval service not implemented
- ❌ System prompt assembly doesn't know about Tweak persona special behavior

---

## Implementation (4 steps)

### Step 1: Seed Tweak personas in database

**File:** `backend/schema.sql` — add to seed data (run on next startup):

```sql
-- Tweak persona for BooOps mode
INSERT INTO personas (id, mode, name, emoji, system_prompt, memory_blob, is_default, is_public)
VALUES (
  '00000000-0000-0000-0000-000000tweek01',
  'booops',
  'Tweak',
  '🤖',
  'You are Tweak, a pragmatic, snarky, science-first assistant. You respond directly, no fluff. You cite sources when relevant. You have access to knowledge from all your DAW sources and academic projects.',
  '{}',
  false,
  true
)
ON CONFLICT (mode, name) DO NOTHING;

-- Tweak persona for 808notes mode
INSERT INTO personas (id, mode, name, emoji, system_prompt, memory_blob, is_default, is_public)
VALUES (
  '00000000-0000-0000-0000-000000tweek02',
  '808notes',
  'Tweak',
  '🤖',
  'You are Tweak in 808notes mode—pragmatic and snarky. Ground responses in available sources and academic context. Cite what you know.',
  '{}',
  false,
  true
)
ON CONFLICT (mode, name) DO NOTHING;
```

**Deploy:** Just update `schema.sql`; next `docker compose up -d` will run it.

---

### Step 2: Multi-DAW RAG retrieval service

**File:** `backend/services/rag.py` — add new function:

```python
import httpx
from services.embeddings import embed_text
from flashrank import Ranker, RerankRequest
from typing import List

ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

async def retrieve_context_all_daws(
    query: str,
    mode: str,
    chroma,
    top_k: int = 6
) -> str:
    """
    Retrieve RAG context from ALL DAWs' sources in a mode.
    Queries all Chroma collections matching daw_*_sources, merges results, reranks.
    Used when Tweak persona is selected.
    """
    if not query:
        return ""
    
    # Embed query once
    query_embedding = await embed_text(query)
    
    # List all Chroma collections
    try:
        collections = chroma.list_collections()
    except Exception as e:
        print(f"Error listing Chroma collections: {e}")
        return ""
    
    all_chunks = []
    all_daw_names = []
    
    # Query all daw_*_sources collections
    for collection in collections:
        col_name = collection.name if hasattr(collection, 'name') else collection
        
        # Only query sources collections (skip notes, etc.)
        if not isinstance(col_name, str) or not col_name.endswith("_sources"):
            continue
        
        # Extract DAW name from collection name (daw_{daw_id}_sources)
        daw_name = col_name.replace("daw_", "").replace("_sources", "")
        
        try:
            collection_obj = chroma.get_collection(name=col_name)
            
            # Query this DAW's sources (top-20 pre-rerank)
            results = collection_obj.query(
                query_embeddings=[query_embedding],
                n_results=20
            )
            
            if results and results['documents'] and results['documents'][0]:
                chunks = results['documents'][0]
                all_chunks.extend(chunks)
                all_daw_names.extend([daw_name] * len(chunks))
        except Exception as e:
            # Collection doesn't exist or query failed, skip
            continue
    
    if not all_chunks:
        return ""
    
    # Rerank all chunks across all DAWs
    passages = [
        {"id": str(i), "text": chunk}
        for i, chunk in enumerate(all_chunks)
    ]
    
    try:
        rerank_req = RerankRequest(query=query, passages=passages)
        reranked = ranker.rerank(rerank_req)
        
        # Format top-k with attribution
        context_lines = ["### Context from your sources:\n"]
        for i, passage in enumerate(reranked[:top_k]):
            # Try to get DAW name from original list
            orig_idx = int(passage.id)
            daw_name = all_daw_names[orig_idx] if orig_idx < len(all_daw_names) else "unknown"
            context_lines.append(f"[{daw_name}] {passage.text}\n")
        
        return "\n".join(context_lines)
    except Exception as e:
        print(f"Error reranking: {e}")
        # Fallback: just return top chunks without reranking
        context_lines = ["### Context from your sources (unranked):\n"]
        for i, chunk in enumerate(all_chunks[:top_k]):
            daw_name = all_daw_names[i] if i < len(all_daw_names) else "unknown"
            context_lines.append(f"[{daw_name}] {chunk}\n")
        return "\n".join(context_lines)
```

---

### Step 3: BourBites context service

**File:** `backend/services/bourbites.py` (create new):

```python
import httpx
from typing import Dict

async def fetch_bourbites_context() -> Dict:
    """Fetch academic context from BourBites API."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "http://100.114.205.53:8600/api/context"
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"Error fetching BourBites context: {e}")
    
    return {}

def format_bourbites_context(data: Dict) -> str:
    """Format BourBites context for injection into system prompt."""
    if not data:
        return ""
    
    lines = ["### Academic Context (BourBites):\n"]
    
    if data.get('docs'):
        lines.append("**Documents:**")
        for doc in data['docs'][:5]:
            title = doc.get('title', 'untitled')
            lines.append(f"  - {title}")
    
    if data.get('todos'):
        active_todos = [t for t in data['todos'] if not t.get('completed')]
        if active_todos:
            lines.append("\n**Active Todos:**")
            for todo in active_todos[:5]:
                text = todo.get('text', '')
                lines.append(f"  ○ {text}")
    
    if data.get('projects'):
        lines.append("\n**Projects:**")
        for proj in data['projects'][:3]:
            name = proj.get('name', '')
            status = proj.get('status', 'unknown')
            lines.append(f"  - {name} ({status})")
    
    if data.get('upcoming'):
        lines.append("\n**Upcoming (next 7 days):**")
        for evt in data['upcoming'][:3]:
            date = evt.get('date', '')
            title = evt.get('title', '')
            lines.append(f"  - {date}: {title}")
    
    return "\n".join(lines)
```

---

### Step 4: Modify system prompt assembly for Tweak persona

**File:** `backend/routers/chats.py` → `_assembled_system_prompt` function:

Replace or extend the function to detect Tweak persona and inject multi-DAW RAG:

```python
from services.rag import retrieve_context_all_daws
from services.bourbites import fetch_bourbites_context, format_bourbites_context

async def _assembled_system_prompt(
    conn,
    chat_id: str,
    daw_id: str,
    mode: str,
    persona_id: str,
    web_search_enabled: bool,
    chroma,
    messages: list
):
    """Assemble system prompt with persona, RAG, context, etc."""
    blocks = []
    
    # 1. Fetch persona
    persona = await conn.fetchrow(
        "SELECT name, system_prompt FROM personas WHERE id = $1",
        persona_id
    )
    persona_name = persona['name'] if persona else "Assistant"
    
    if persona:
        blocks.append(persona['system_prompt'])
    
    # 2. If Tweak persona: inject multi-DAW RAG + BourBites
    if persona_name == "Tweak":
        # Get user's current query
        user_query = messages[-1]["content"] if messages else ""
        
        if user_query:
            # Retrieve from all DAW sources
            rag_context = await retrieve_context_all_daws(
                query=user_query,
                mode=mode,
                chroma=chroma,
                top_k=6
            )
            if rag_context:
                blocks.append(rag_context)
        
        # Fetch and inject BourBites context
        bourbites_data = await fetch_bourbites_context()
        bourbites_context = format_bourbites_context(bourbites_data)
        if bourbites_context:
            blocks.append(bourbites_context)
    
    # 3. If DAW selected (and not Tweak's RAG retrieval): add DAW system prompt
    if daw_id:
        daw = await conn.fetchrow(
            "SELECT system_prompt FROM daws WHERE id = $1",
            daw_id
        )
        if daw and daw['system_prompt']:
            blocks.append(daw['system_prompt'])
    
    # 4. DAW instructions (if DAW selected)
    if daw_id:
        daw_instructions = await conn.fetch(
            "SELECT instruction FROM daw_instructions WHERE daw_id = $1 ORDER BY created_at",
            daw_id
        )
        if daw_instructions:
            instr_lines = "\n".join([f"- {row['instruction']}" for row in daw_instructions])
            blocks.append(f"### DAW Instructions\n{instr_lines}")
    
    # 5. Context files (from DAW, if selected)
    if daw_id:
        context_files = await conn.fetch(
            "SELECT content FROM daw_context_files WHERE daw_id = $1",
            daw_id
        )
        for cf in context_files:
            blocks.append(cf['content'])
    
    # 6. Custom instructions (global + mode)
    custom_global = await conn.fetchval(
        "SELECT content FROM custom_instructions WHERE scope = 'global' LIMIT 1"
    )
    if custom_global:
        blocks.append(f"### Global Instructions\n{custom_global}")
    
    custom_mode = await conn.fetchval(
        "SELECT content FROM custom_instructions WHERE scope = $1 LIMIT 1",
        mode
    )
    if custom_mode:
        blocks.append(f"### {mode} Instructions\n{custom_mode}")
    
    # 7. Mode memory (blob)
    mode_memory = await conn.fetchval(
        "SELECT memory_blob FROM mode_memory WHERE mode = $1",
        mode
    )
    if mode_memory:
        blocks.append(f"### Remembered Context\n{mode_memory}")
    
    # 8. Memory entries (facts)
    memory_entries = await conn.fetch(
        "SELECT fact FROM memory_entries WHERE mode = $1 AND is_deleted = false ORDER BY created_at",
        mode
    )
    if memory_entries:
        fact_lines = "\n".join([f"- {row['fact']}" for row in memory_entries])
        blocks.append(f"### Remembered Facts\n{fact_lines}")
    
    # Join all blocks
    return "\n\n---\n\n".join(blocks)
```

---

## Test workflow

### 1. Deploy changes
```bash
cd /opt/boolab

# Update schema.sql with Tweak seed data
# Update backend/services/rag.py with new function
# Create backend/services/bourbites.py
# Modify backend/routers/chats.py system prompt assembly

docker compose build boolab_api
docker compose up -d
```

### 2. Create test data
```bash
# In boolab web UI:
# 1. Create a DAW in 808notes: "Research Notes"
# 2. Upload a .txt or .pdf file to that DAW (via Sources page)
# 3. Wait for embedding to complete (check logs)
```

### 3. Chat with Tweak
```
- Open BooOps or 808notes
- Select Tweak persona (should appear in persona dropdown)
- Don't select a DAW (Tweak retrieves from all)
- Send message: "What research have I done?"
- Check logs: docker logs -f boolab_api
- Should see RAG context from "Research Notes" + BourBites context in assembled prompt
```

### 4. Verify in logs
```bash
docker logs -f boolab_api | grep "assembled prompt"
# Output should include:
# - "You are Tweak, pragmatic..." (persona)
# - "[Research Notes] chunk text..." (multi-DAW RAG)
# - "Academic Context (BourBites):" (BourBites context)
```

---

## Acceptance criteria
✅ Tweak persona seeded in both BooOps + 808notes modes  
✅ Tweak persona selectable in chat UI (appears in persona dropdown)  
✅ Multi-DAW RAG retrieval queries all daw_*_sources collections  
✅ RAG context injected when Tweak selected (not for other personas)  
✅ BourBites context fetched and injected  
✅ System prompt logs show all blocks in correct order  
✅ No errors in `docker logs boolab_api`  
✅ Works with multiple DAWs (merges + reranks across them)  

---

## Notes
- **Emoji:** Tweak uses 🤖; easily changed in seed data or later via `/api/personas/{id}` endpoint
- **Query embedding:** Uses same qwen3-embedding as DAW sources (consistent)
- **Reranking:** Uses flashrank to score chunks across all DAWs together (accurate relevance)
- **BourBites fallback:** If BourBites API unreachable, gracefully skips that block
- **No DAW selection needed:** Tweak works without selecting a DAW (unlike other personas)

---

## Next step
After this works, proceed to **prompt 2: Discord bot fetches Tweak persona from boolab**.
