# Architecture Decisions — Single-Patient Demo

## Status

This batch is still active.

What is already true in the working tree:
- demo data has been rewritten into dated first-person journal entries
- dead FHIR handling has been removed from `backend/routers/demo.py`
- frontend has a demo-loading CTA wired to `POST /api/demo/load`

What is still missing before archive:
- the frontend does not yet hide the CTA for non-admin users
- end-to-end verification against a running stack has not been recorded

## Data Format Decision

### Decision: First-person journal as plain `.txt`

**Chosen:** First-person narrative journal entries, one `.txt` file per date, formatted in plain prose with optional paragraph breaks.

**Alternative considered:** Keep clinical report format and add a "translation layer" in the UI. Rejected — RAG retrieval would surface clinical reports in chat context, which is jarring when the user asks "what were my symptoms in September?"

**Rationale:** The app is designed for personal health records. The demo should illustrate the intended use case, not a different one. First-person journal entries produce RAG results that feel like the user's own words. They also make the demo feel warm and personal, not sterile.

**Format specification:**
- File naming: `YYYY-MM-DD Brief description.txt` (sorts chronologically)
- Content: Free-text prose, no structured headers required
- Voice: First-person ("I", "my", "me")
- Length: 200-500 words per entry
- Must include: date reference in first sentence, subjective experience, plain-language results interpretation

## Frontend Placement

### Decision: "Try Demo" button on WorkspaceLanding (home page)

**Chosen:** Add a dedicated card/section on the WorkspaceLanding component, shown when the workspace list is empty OR as a persistent option below the workspace grid.

**Alternative considered:** Add to SetupPage after account creation. Rejected — the setup flow already auto-redirects to `/` after login; adding another step would feel like a wizard. The landing page is the natural discover point.

**Alternative considered:** Add to the sidebar. Rejected — too hidden for a first-time user exploring the app.

**Rationale:** The landing page is the first screen a new user sees after setup. It currently shows an empty state with "No workspaces yet" and a "New Workspace" button. Adding a "Try Demo" option here meets the user where they are.

### UI contract
- Button text: "Try Demo" with a subtitle "Load sample health records"
- States: idle → loading (spinner + "Loading demo data…") → success (navigate to Demo workspace) → error (inline error message)
- Already-exists case: the endpoint returns `{status: "exists", workspace_id: "..."}`. Button should still appear, but clicking navigates to existing Demo workspace instead of re-creating.

## Backend Cleanup

### Dead code removal: `_fhir_bundle_to_text()`

**What to remove:**
- `_fhir_bundle_to_text()` function (lines 28-80 of `backend/routers/demo.py`)
- The `.json` file handling branch in `load_demo()` (the `if f.suffix == ".json"` / `elif f.suffix == ".txt"` block)
- `import json` (only used by `_fhir_bundle_to_text` — grep confirms no other json usage in the file)

**What stays:**
- `import uuid` (used for source_id generation)
- `from typing import Any` (used in route parameter type hint)
- `import asyncio` (used for `asyncio.create_task`)
- `import pathlib` (used for `DEMO_DIR`)
- The `.txt` file handling branch (simplified to just read `.txt` files)
- Everything else in the router

**Risk:** Zero. No FHIR JSON files exist in demo_data. The dead code has never been exercised in production.

## API Contract

### Existing endpoints (unchanged)

```
POST /api/demo/load   → { status: "loaded" | "exists", workspace_id, documents? }
DELETE /api/demo/unload → { status: "removed" | "absent" }
```

Both require admin auth (the first user created via setup is admin).

### New frontend API wrapper

```js
// frontend/src/api/workspaces.js (addition)
export const loadDemo = () => apiFetch('/api/demo/load', { method: 'POST' })
```

The wrapper reuses `apiFetch` which sends the session cookie automatically.

## Edge Cases

| Case | Handling |
|------|----------|
| User not admin | Button hidden (demo requires admin; non-admin users can't trigger it) |
| Demo already loaded | Button navigates to existing Demo workspace instead of re-loading |
| demo_data directory missing | Backend returns 500; frontend shows error message |
| No workspaces at all | Button shown in empty state |
| User has other workspaces | Button shown as secondary option below workspace grid |
| Mobile | Button renders inline in the responsive layout |
| Ingest still in progress | Navigate immediately after POST; sources appear as they complete (existing behavior) |

## Migration Path

1. Rewrite demo data files (no schema change, no migration)
2. Clean up demo.py (no schema change)
3. Add frontend button (no migration)
4. Deploy: `docker compose up --build -d` rebuilds both frontend and backend

No database migration required. The Demo workspace is created fresh each time; if it already exists, it's reused.

## Amendment: Demo Loader Atomicity (B4)

**Date:** 2026-06-12

### Problem

Three bugs exist in `backend/routers/demo.py` (`load_demo`), identified during architecture analysis.

**B4-1: No transaction wrapping workspace and source INSERTs**

The workspace INSERT and each per-source INSERT each acquire a separate connection from the pool with no enclosing transaction:

```python
async with pool.acquire() as conn:          # connection 1: workspace
    ws_id = await conn.fetchval(...)

for f in sorted(DEMO_DIR.iterdir()):
    ...
    async with pool.acquire() as conn:      # connection 2..N: each source, separately
        await conn.execute("INSERT INTO sources ...")
```

If the process crashes, loses its DB connection, or receives SIGTERM between the workspace INSERT and the source INSERTs, the workspace row is committed but no sources are linked to it. On the next `POST /api/demo/load` call the name-based idempotency check (`WHERE name = 'Demo'`) finds the orphaned workspace and returns `{status: "exists"}` with zero documents -- permanently blocking a clean reload without manual DB intervention.

**B4-2: Fire-and-forget ingest tasks with no held reference**

```python
asyncio.create_task(_ingest_source(source_id, ws_id, raw, "text/plain", f.stem))
```

`asyncio.create_task` returns a `Task` object. When no reference is held, the garbage collector can discard the task before it finishes. On process restart (e.g., `docker compose restart hlh_api`) all in-flight tasks are abandoned with no recovery path. Sources created during the interrupted run remain at `embedding_status='pending'` indefinitely -- they are never retried and never surface in RAG.

**B4-3: `file_url` is NULL for every demo source**

The INSERT does not set `file_url`:

```python
await conn.execute(
    """
    INSERT INTO sources (id, workspace_id, name, source_type, mime_type,
                         file_size_bytes, embedding_status)
    VALUES ($1::uuid, $2::uuid, $3, 'txt', 'text/plain', $4, 'pending')
    """,
    source_id, ws_id, f.stem, len(raw),
)
```

Any code path that later needs to re-read the source file (re-ingest, download, vision processing) finds `file_url IS NULL` and silently skips or errors. The demo content is embedded at ingest time so this is currently latent, but it violates the invariant every other source creation path upholds.

### Fix Design

**Fix for B4-1: Single transaction wrapping all INSERTs**

Acquire one connection and open one transaction that covers the workspace INSERT and all source INSERTs. If any INSERT fails, the entire transaction rolls back and leaves no orphaned workspace.

Pseudocode:

```python
pending: list[tuple] = []

async with pool.acquire() as conn:
    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE name = $1", DEMO_WS_NAME
        )
        if existing:
            all_complete = await conn.fetchval(
                """SELECT bool_and(embedding_status = 'complete')
                   FROM sources WHERE workspace_id = $1""",
                existing["id"],
            )
            if all_complete:
                return {"status": "exists", "workspace_id": str(existing["id"])}
            # partial or stuck: delete and recreate atomically
            await conn.execute(
                "DELETE FROM workspaces WHERE id = $1", existing["id"]
            )

        ws_id = await conn.fetchval(
            "INSERT INTO workspaces (...) VALUES (...) RETURNING id", ...
        )

        for f in sorted(DEMO_DIR.iterdir()):
            if f.suffix != ".txt":
                continue
            text = f.read_text()
            if not text.strip():
                continue
            raw = text.encode("utf-8")
            source_id = uuid.uuid4()
            dest = pathlib.Path("/data/uploads") / f"{source_id}.txt"
            dest.write_bytes(raw)   # raises OSError before INSERT if path unwritable
            await conn.execute(
                """INSERT INTO sources
                   (id, workspace_id, name, source_type, mime_type,
                    file_size_bytes, file_url, embedding_status)
                   VALUES ($1,$2,$3,'txt','text/plain',$4,$5,'pending')""",
                source_id, ws_id, f.stem, len(raw), str(dest),
            )
            pending.append((source_id, ws_id, raw, f.stem))

# transaction committed -- now safe to fire ingest tasks
tasks: list[asyncio.Task] = []
for source_id, ws_id, raw, name in pending:
    t = asyncio.create_task(_ingest_source(source_id, ws_id, raw, "text/plain", name))
    tasks.append(t)
```

**Idempotency states**

The idempotency check must distinguish three states:

| State | Condition | Action |
|-------|-----------|--------|
| Never loaded | No workspace row named "Demo" | Create workspace + sources |
| Complete | Workspace exists AND `bool_and(embedding_status = 'complete')` is TRUE | Return `{status: "exists"}` |
| Partial or stuck | Workspace exists AND any source is not complete | DELETE workspace (CASCADE deletes sources + chunks) then re-create |

The DELETE and new workspace INSERT happen inside the same transaction, so the transition is atomic.

**Fix for B4-2: Retain task references**

Collect all `asyncio.create_task(...)` return values into a list. This prevents the garbage collector from dropping tasks that have not yet been scheduled. The list goes out of scope after the return, but by that point the event loop has taken ownership of each task.

Note: tasks still running when the process receives SIGTERM are abandoned regardless -- this is unchanged. The fix targets only the GC-drop-before-scheduling window. Post-restart recovery of permanently-stuck `pending` sources is a separate concern.

**Fix for B4-3: Write file before INSERT, populate `file_url`**

Copy each demo file to `/data/uploads/{source_id}.txt` before executing the sources INSERT so the path is available inside the transaction. If `dest.write_bytes` raises, the exception propagates out of the `conn.transaction()` block and triggers automatic rollback.

### Files Affected

- `backend/routers/demo.py` -- all three fixes apply to `load_demo` only; `unload_demo` is unchanged

### No Schema Change

`sources.file_url` already exists as `TEXT` (nullable). No column addition or migration is required.
