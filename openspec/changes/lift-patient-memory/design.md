# Design: lift-patient-memory

**Date:** 2026-06-13

---

## Architecture overview

Three existing memory stores today (none suitable for structured profiles):

1. **SQLite CoreTier** (`data/memory/long-term/index.db`, via `services/memory/core_tier.py`) --
   extraction/recall live path; MD5-keyed, no conflict resolution.
2. **`memory_entries` table** (PostgreSQL, `backend/schema.sql:178`) -- flat TEXT +
   pgvector, used by `services/rag.py:retrieve_memory_facts` + `routers/memory.py`.
3. **`workspace_memory` table** (PostgreSQL, `schema.sql:296`) -- multi-row TEXT,
   manually entered, injected by `_assembled_system_prompt` as bullet list.

**This change adds a fourth store: `workspace_patient_profile`** -- a single-row-per-
workspace JSONB document in PostgreSQL. It is the authoritative structured patient
profile. It does not replace the other three stores in this change; consolidation is
future work.

---

## C1a: Schema -- `workspace_patient_profile`

Add to `backend/schema.sql` after the `workspace_memory` table (line ~303):

```sql
CREATE TABLE IF NOT EXISTS workspace_patient_profile (
    workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    profile JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Backfill for existing workspaces (idempotent):

```sql
INSERT INTO workspace_patient_profile (workspace_id, profile)
SELECT id, '{}'::jsonb FROM workspaces
ON CONFLICT (workspace_id) DO NOTHING;
```

No HNSW index: profile is always fetched by `workspace_id` PK.

Initial JSONB shape (matches `create_empty_memory` pattern from C.md):

```json
{
  "version": "1.0",
  "name": null,
  "date_of_birth": null,
  "blood_type": null,
  "active_diagnoses": [],
  "current_medications": [],
  "allergies": [],
  "primary_care_provider": null,
  "insurance": null,
  "lab_baselines": {},
  "user_context": {"summary": "", "updatedAt": ""},
  "history": {
    "recentMonths": {"summary": "", "updatedAt": ""},
    "longTermBackground": {"summary": "", "updatedAt": ""}
  },
  "facts": []
}
```

`facts` is an array of objects:
```json
{
  "id": "<uuid4>",
  "content": "...",
  "category": "medical|preference|context|personal|other",
  "confidence": 0.0,
  "source": "extraction",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**asyncpg JSONB convention**: always pass profile dict as `json.dumps(profile)` and
cast with `::jsonb` in SQL. Never pass a raw Python dict.

---

## C1b: `backend/services/patient_profile.py` (new module)

Single-responsibility module for all profile CRUD and formatting. No coupling to
`MemoryEngine` or `CoreTier`.

Key functions:

```python
EMPTY_PROFILE: dict  # sentinel for fresh workspaces

async def get_profile(conn, workspace_id: UUID) -> dict:
    """Fetch profile or return EMPTY_PROFILE copy if row absent."""

async def upsert_profile(conn, workspace_id: UUID, profile: dict) -> None:
    """Full-document upsert. Pass profile as json.dumps(profile) string."""

async def apply_fact_updates(
    conn,
    workspace_id: UUID,
    new_facts: list[dict],
    facts_to_remove: list[str],  # list of fact IDs
) -> None:
    """Merge new_facts into profile['facts'], remove by ID, upsert."""

async def resolve_conflicts(
    profile: dict,
    new_facts: list[dict],
    provider: object,
    model: str,
) -> tuple[list[dict], list[str]]:
    """LLM conflict-resolution pass. Returns (facts_to_add, ids_to_remove).
    Skips LLM call if new_facts is empty. Uses _CONFLICT_RESOLUTION_PROMPT."""

def format_profile_for_injection(profile: dict, token_budget: int = 1500) -> str:
    """Render profile as prompt text. Sorted by confidence, truncated at budget.
    char/4 token estimator (no tiktoken dependency)."""
```

**Conflict-resolution LLM call** (C2):
- Uses `services/provider_client.py:build_headers` and `provider.base_url` -- same
  pattern as `memory_extraction.py` lines 86-97.
- Prompt: `_CONFLICT_RESOLUTION_PROMPT` (see specs/conflict-resolution-prompt.md).
- Returns a JSON object `{"factsToRemove": ["<id>",...], "newFacts": [...]}`.
- If LLM call fails or returns unparseable JSON, log warning and fall back to
  append-only (new_facts added, nothing removed).
- Gate: caller checks `memory_conflict_resolution_enabled` from `global_settings`
  before calling `resolve_conflicts`; if disabled, skip and call `apply_fact_updates`
  directly.

---

## C1c: Injection into `_assembled_system_prompt`

In `backend/routers/chats.py`, function `_assembled_system_prompt` (line 112).

After the `workspace_memory` block (lines 156-166), add a new try/except block:

```python
if workspace_id is not None:
    try:
        from services.patient_profile import get_profile, format_profile_for_injection
        _profile = await get_profile(conn, workspace_id)
        if _profile.get("facts") or _profile.get("active_diagnoses") or ...:
            _budget = int(await conn.fetchval(
                "SELECT value FROM global_settings WHERE key='memory_injection_token_budget'"
            ) or "1500")
            _profile_text = format_profile_for_injection(_profile, _budget)
            if _profile_text:
                parts.append(f"### Patient Profile\n{_profile_text}")
    except Exception as exc:
        logger.warning("_assembled_system_prompt: patient profile fetch failed: %s", exc)
```

Profile is injected unconditionally (no similarity gate) because it is the
authoritative structured record. It is placed after `workspace_memory` and before
context files.

---

## C1d: Profile CRUD endpoints

Add two endpoints. Pattern: follow `routers/memory.py` for response shapes.

```
GET  /api/workspaces/{workspace_id}/patient-profile
     -> 200 {"workspace_id": "...", "profile": {...}, "updated_at": "..."}
     -> 404 if workspace not found
     Auth: session required (deps.py)

PUT  /api/workspaces/{workspace_id}/patient-profile
     body: {"profile": {...}}
     -> 200 {"workspace_id": "...", "updated_at": "..."}
     Auth: session required
```

Mount via the existing workspaces router or as additions to `routers/chats.py`. The
workspaces router (`routers/workspaces.py`) is the preferred home.

---

## C2: Global settings seed

Add to `schema.sql` settings seed block:

```sql
INSERT INTO global_settings (key, value) VALUES
    ('memory_conflict_resolution_enabled', 'false'),
    ('memory_injection_token_budget', '1500')
ON CONFLICT (key) DO NOTHING;
```

Default `false` for conflict resolution: on a 4b bundled model a second LLM call
per exchange is expensive. Operators running external/larger providers can enable.

---

## C3: Debounce/dedup in `memory_hooks.py`

`inference_job.py` line 486: `asyncio.create_task(run_background_extraction(...))`.
The task key is `name=f"mem_extract_{assistant_id}"` (per-message, not per-workspace).
Under rapid exchanges a workspace can accumulate many overlapping extraction tasks.

**Design**: add a module-level dict `_pending_extraction: dict[str, asyncio.Task]`
keyed by `workspace_id` string. Exported function:

```python
# in memory_hooks.py
_pending_extraction: dict[str, asyncio.Task] = {}

async def schedule_extraction(
    workspace_id: str,
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
    pool: Any,
    *,
    debounce_seconds: float = 10.0,
) -> None:
    """Cancel any pending extraction for this workspace and reschedule."""
    if not workspace_id:
        return  # no workspace (workspace-less chat); skip silently
    existing = _pending_extraction.get(workspace_id)
    if existing and not existing.done():
        existing.cancel()

    async def _delayed():
        await asyncio.sleep(debounce_seconds)
        await run_background_extraction(
            workspace_id=workspace_id,
            user_message_text=user_message_text,
            assistant_text=assistant_text,
            provider=provider,
            model=model,
            pool=pool,
        )

    task = asyncio.create_task(_delayed(), name=f"mem_extract_{workspace_id}")
    _pending_extraction[workspace_id] = task
    # IMPORTANT: done_callback must check identity to avoid popping a replacement
    # task when the cancelled-old task's callback fires after the new task is stored.
    def _on_done(t: asyncio.Task) -> None:
        if _pending_extraction.get(workspace_id) is t:
            _pending_extraction.pop(workspace_id, None)
    task.add_done_callback(_on_done)
```

The identity check in `_on_done` prevents the following race: if task A is cancelled
and task B is already stored under the same workspace_id, task A's done_callback
fires after B is stored -- without the identity check it would pop B's reference,
leaving B unreferenced and eligible for GC before the sleep completes (V7).

`run_background_extraction` gains a `workspace_id: str` parameter (already
available from `chat_record["workspace_id"]`; the key is populated at
`routers/chats.py:1367` and passed as `chat_record` to `run_inference_job`).

**Signal detection** (C3b): before calling `extract_from_exchange`, run two pure-
Python regex checks transplanted from the source fork:

```python
def _detect_correction(text: str) -> bool:
    """Return True if text contains a correction signal."""
    patterns = [
        r"\b(no,?\s+that'?s?\s+(wrong|incorrect|not right))\b",
        r"\b(actually,?\s+it'?s?)\b",
        r"\b(i\s+said|i\s+meant)\b",
        r"\bplease\s+(fix|correct|update)\b",
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)

def _detect_reinforcement(text: str) -> bool:
    """Return True if text reinforces a prior fact."""
    patterns = [
        r"\b(yes,?\s+that'?s?\s+(right|correct))\b",
        r"\b(exactly|precisely|confirmed)\b",
        r"\b(still|continue\s+to|remain)\b",
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)
```

Annotate the extraction call with `signal_type: "correction"|"reinforcement"|None`
-- passed as metadata to `extract_from_exchange` for downstream confidence weighting.

---

## C3b: Extraction writes to `workspace_patient_profile`

**Owner of the profile write: `run_background_extraction` in `memory_hooks.py`.**

`extract_from_exchange` in `memory_extraction.py` is NOT changed (no new parameters,
no Postgres writes). It continues to write to SQLite CoreTier via `eng.manage()` as
before. It returns the list of extracted facts to the caller.

`run_background_extraction` receives the facts from `extract_from_exchange`, then
performs the Postgres profile write using a connection acquired from `pool`:

```python
async def run_background_extraction(
    user_message_text: str,
    assistant_text: str,
    provider: Any,
    model: str,
    *,
    workspace_id: str | None = None,
    pool: Any | None = None,
    signal_type: str | None = None,
) -> list[dict[str, Any]]:
    ...
    facts = await extract_from_exchange(
        user_text=user_message_text,
        assistant_text=assistant_text,
        provider=provider,
        model=model,
    )

    if workspace_id and pool and facts:
        from services.patient_profile import (
            get_profile, apply_fact_updates, resolve_conflicts
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        new_facts = [
            {
                "id": str(uuid4()),
                "content": f["content"],
                "category": f.get("category", "context"),
                "confidence": f.get("confidence", 0.5),
                "source": "extraction",
                "signal_type": signal_type,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            for f in facts
        ]
        async with pool.acquire() as conn:
            conflict_enabled = await conn.fetchval(
                "SELECT value FROM global_settings "
                "WHERE key = 'memory_conflict_resolution_enabled'"
            )
            if conflict_enabled == "true":
                current_profile = await get_profile(conn, workspace_id)
                to_add, to_remove = await resolve_conflicts(
                    current_profile, new_facts, provider, model
                )
            else:
                to_add, to_remove = new_facts, []
            await apply_fact_updates(conn, workspace_id, to_add, to_remove)
    return facts
```

This resolves the design inconsistency (V3 finding): `conn` is acquired via
`async with pool.acquire() as conn:` inside `run_background_extraction`, not passed
as a parameter to `extract_from_exchange`. The `memory_extraction.py` file requires
no signature changes.

---

## C4: `format_profile_for_injection`

Token budget estimator: `len(text) // 4` (char/4 fallback, no tiktoken).

Injection order:
1. Structured fields (name, DOB, blood type, active_diagnoses, current_medications,
   allergies, primary_care_provider, insurance, lab_baselines) -- always rendered if
   non-empty, regardless of confidence.
2. `facts` array -- sorted by `confidence` descending, then by `created_at`
   descending. Each fact rendered as a bullet: `- [{category}] {content}`.
3. History/user_context summaries -- appended if budget allows.

Hard truncation at budget (not soft truncation mid-sentence). Return empty string
if profile is `{}` or all structured fields are null/empty.

---

## Verification approach

Per CLAUDE.md: `psql -c` does not honor `-v` substitution; assert via API JSON.

`backend/scripts/verify_patient_memory.sh`:
1. Auth: `POST /api/auth/login` -> set cookie.
2. Create workspace via `POST /api/workspaces`.
3. Assert `GET /api/workspaces/{id}/patient-profile` returns `{"profile": {}}`.
4. `PUT /api/workspaces/{id}/patient-profile` with a small test profile.
5. Assert `GET` returns the updated profile.
6. POST a chat message (requires running stack + `memory_auto_extract_enabled=true`).
7. Poll `GET /api/workspaces/{id}/patient-profile` up to 30s; assert `facts` array
   gains at least one entry.
8. Assert `DELETE /api/workspaces/{id}` cascades and removes profile row (check via
   API, not psql).
9. Print PASS/FAIL and exit non-zero on any failure.

---

## Guardrails

**Must Have:**
- `CREATE TABLE IF NOT EXISTS` -- idempotent, safe on existing DBs.
- Backfill INSERT with `ON CONFLICT DO NOTHING` -- safe on fresh and existing DBs.
- `memory_conflict_resolution_enabled` defaults to `false`.
- All JSONB writes via `json.dumps(d)` + `::jsonb` cast (CLAUDE.md asyncpg convention).
- `extract_from_exchange` workspace_id parameter is optional; old callers unaffected.
- Conflict resolver falls back to append-only on any LLM/parse failure.
- `format_profile_for_injection` returns empty string for empty/null profiles.

**Must NOT Have:**
- No `os.environ.get("OPENAI_API_KEY")` or any of the five deprecated env vars.
- No `trustcall` import -- conflict resolution is vanilla LLM + JSON.
- No `tiktoken` import -- use char/4 estimator.
- No `ALTER TABLE ADD COLUMN` on `workspace_patient_profile` (new table, not migration).
- No threading.Timer (use asyncio.Task for debounce).
- No role CHECK constraint changes.

---

## Backward compatibility

- `memory_extraction.py:extract_from_exchange` signature is extended with optional
  keyword-only args; all existing callers continue to work.
- `memory_hooks.py:run_background_extraction` gains optional `workspace_id` and `pool`
  keyword args; the existing call in `inference_job.py` is updated to pass them.
- No changes to `MemoryEngine`, `CoreTier`, or `MemoryStore`.
- The SQLite CoreTier continues to receive extraction writes alongside the new
  Postgres profile writes (dual-write, not migration).
