"""Chat CRUD, message listing, and streaming sends (OpenAI-compatible local inference or Claude)."""

import uuid

import json
import os
import logging
import posixpath
from typing import Any, AsyncIterator

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth_deps import (
    assert_daw_usable,
    assert_persona_usable,
    get_principal,
)
from db import get_pool
from routers.dubdrive_sync import _dubdrive_read_bytes
from services import code_chunker
from services.pruning import summarize_and_compress
from services.rag import (
    retrieve_context,
    retrieve_memory_facts,
    retrieve_repo_chunks,
    should_retrieve,
)
from services.repo_ingest import validate_relative_file_path, validate_repo_path
from services.searx import searx_search_sources

router = APIRouter()
logger = logging.getLogger(__name__)

BOOCODE_CONTEXT_CHAR_BUDGET = int(os.environ.get("BOOCODE_CONTEXT_CHAR_BUDGET", "40000"))
BOOCODE_ATTACH_CHAR_BUDGET = int(os.environ.get("BOOCODE_ATTACH_CHAR_BUDGET", "20000"))

BOOCODE_ARCHITECT_PREAMBLE = """\
You are a read-only code architect. You review codebases and draft precise prompts
for a separate coding agent (OpenCode) to execute. You do NOT edit files.

When the user asks for a change:
1. One-paragraph plan
2. OpenCode-ready prompt inside a fenced ```prompt code block
3. List of files to be touched (paths only, one per line)

When citing code, reference file path + symbol name. Do not invent file contents
not present in Repo Context.
"""


def _format_repo_chunks(chunks: list[dict[str, Any]]) -> str:
    """Format repo chunks into the ## Repo Context block, capped at BOOCODE_CONTEXT_CHAR_BUDGET.

    Drops the lowest-similarity chunks first if the formatted block would overflow.
    """
    if not chunks:
        return ""

    header = (
        "## Repo Context\n"
        "The following code fragments were retrieved from the repo bound to this DAW.\n"
        "Cite chunks by file path. If a question cannot be answered from these fragments,\n"
        "say so — do not fabricate file contents.\n"
    )

    ordered = sorted(chunks, key=lambda c: float(c.get("similarity") or 0.0), reverse=True)

    rendered: list[str] = []
    total = len(header)
    for c in ordered:
        path = c.get("path") or "?"
        sym_name = c.get("symbol_name") or ""
        lang = c.get("language") or ""
        head_bits = [path]
        if sym_name:
            head_bits.append(sym_name)
        head = ":".join(head_bits)
        marker = f"[{head}" + (f" ({lang})" if lang else "") + "]"
        body = c.get("content") or ""
        piece = f"\n{marker}\n{body}\n"
        if total + len(piece) > BOOCODE_CONTEXT_CHAR_BUDGET:
            break
        rendered.append(piece)
        total += len(piece)

    if not rendered:
        return ""
    return header + "".join(rendered)


async def _render_boocode_attachments(
    refs: list["BoocodeFileRef"],
    repo_root_raw: str,
    char_budget: int,
) -> str:
    """Render attached repo files as fenced code blocks, capped by count and chars.

    Returns "" if no files rendered. Safe to call with any input —
    invalid paths / binary / oversize files are skipped, not raised.
    """
    if not refs or not repo_root_raw:
        return ""
    try:
        repo_root = validate_repo_path(repo_root_raw)
    except ValueError:
        return ""
    if not repo_root:
        return ""

    rendered: list[str] = []
    total = 0
    for ref in refs[:4]:
        try:
            rel = validate_relative_file_path(ref.path)
        except ValueError:
            continue
        raw = await _dubdrive_read_bytes(posixpath.join(repo_root, rel))
        if raw is None or len(raw) > code_chunker.MAX_FILE_BYTES:
            continue
        if b"\x00" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        lang = code_chunker.resolve_language(rel) or ""
        header = f"\n\n[attached file: {rel}{f' ({lang})' if lang else ''}]\n"
        fence_open = f"```{lang}\n"
        fence_close = "\n```\n"
        framing_len = len(header) + len(fence_open) + len(fence_close)
        remaining = char_budget - total - framing_len
        if remaining <= 0:
            break
        if len(text) > remaining:
            trunc_marker = "\n[truncated]"
            keep = max(0, remaining - len(trunc_marker))
            text = text[:keep] + trunc_marker
        piece = header + fence_open + text + fence_close
        rendered.append(piece)
        total += len(piece)
        if total >= char_budget:
            break

    return "".join(rendered)


async def _default_persona_id_for_mode(conn: asyncpg.Connection, mode: str) -> uuid.UUID | None:
    """Default persona for new chat: global personas table + per-app default flags."""
    m = mode if mode in ("booops", "808notes") else "booops"
    if m == "808notes":
        return await conn.fetchval(
            "SELECT id FROM personas WHERE is_default_808notes IS TRUE LIMIT 1",
        )
    return await conn.fetchval(
        "SELECT id FROM personas WHERE is_default_booops IS TRUE LIMIT 1",
    )








_AUTO_MEMORY_TRIGGERS = (
    "remember that",
    "note that",
    "don't forget",
    "dont forget",
    "keep in mind",
)


def _first_auto_memory_sentence(text: str) -> str | None:
    if not text or not text.strip():
        return None
    lower = text.lower()
    best: int | None = None
    for trig in _AUTO_MEMORY_TRIGGERS:
        i = lower.find(trig)
        if i != -1 and (best is None or i < best):
            best = i
    if best is None:
        return None
    idx = best
    s = text
    start = 0
    for i in range(min(idx, max(len(s) - 1, 0)), -1, -1):
        if i < 0:
            break
        c = s[i]
        if c in ".!?\n":
            start = i + 1
            while start < len(s) and s[start] in " \t":
                start += 1
            break
    end = len(s)
    for j in range(idx, len(s)):
        c = s[j]
        if c in ".!?":
            end = j + 1
            break
        if c == "\n":
            end = j
            break
    snippet = s[start:end].strip()
    return snippet or None


async def _site_default_model(conn: asyncpg.Connection, mode: str) -> str:
    key = "default_model_808notes" if mode == "808notes" else "default_model"
    row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", key)
    if row and row["value"]:
        v = str(row["value"]).strip()
        if v:
            return v
    return (
        os.environ.get("DEFAULT_MODEL", "llama-gpu/qwen3.5-9b-exl3") or "llama-gpu/qwen3.5-9b-exl3"
    ).strip()


async def _assembled_system_prompt(
    conn: asyncpg.Connection,
    chat: asyncpg.Record,
    *,
    user_query_for_rag: str | None = None,
    include_site_private: bool = True,
    session_skill_ids: list[str] | None = None,
    boocode_files: list["BoocodeFileRef"] | None = None,
) -> tuple[str, dict[str, int] | None]:
    """Persona → DAW prompt + daw_instructions + semantic memory facts → context files → custom instructions → RAG → mode_memory."""
    mode = chat["mode"] if chat["mode"] in ("booops", "808notes") else "booops"
    pid = chat["persona_id"]
    daw_id = chat["daw_id"]
    daw_prompt = ""
    daw_persona_id = None
    daw_rag_mode_effective = "auto"
    daw_table_mode = "booops"
    daw_repo_path = ""
    if daw_id is not None:
        ws = await conn.fetchrow(
            "SELECT system_prompt, persona_id, mode, rag_mode, repo_path FROM daws WHERE id = $1::uuid",
            daw_id,
        )
        if ws:
            daw_prompt = (ws["system_prompt"] or "").strip()
            daw_persona_id = ws["persona_id"]
            daw_table_mode = ws["mode"] if ws["mode"] in ("booops", "808notes", "boocode") else "booops"
            daw_repo_path = (ws["repo_path"] or "").strip() if "repo_path" in ws.keys() else ""
            if daw_table_mode == "boocode" and not daw_prompt:
                daw_prompt = BOOCODE_ARCHITECT_PREAMBLE
            if daw_table_mode == "808notes":
                daw_rag_mode_effective = "always"
            elif daw_table_mode == "boocode":
                daw_rag_mode_effective = "always"
            else:
                rm = ws.get("rag_mode")
                daw_rag_mode_effective = rm if rm in ("auto", "always", "off") else "auto"

    resolve_pid = pid if pid is not None else daw_persona_id

    persona_prompt = ""
    if resolve_pid is not None:
        pr = await conn.fetchrow(
            "SELECT system_prompt FROM personas WHERE id = $1::uuid",
            resolve_pid,
        )
        if pr:
            persona_prompt = (pr["system_prompt"] or "").strip()

    if not persona_prompt:
        if mode == "808notes":
            d = await conn.fetchrow(
                "SELECT system_prompt FROM personas WHERE is_default_808notes IS TRUE LIMIT 1",
            )
        else:
            d = await conn.fetchrow(
                "SELECT system_prompt FROM personas WHERE is_default_booops IS TRUE LIMIT 1",
            )
        if d:
            persona_prompt = (d["system_prompt"] or "").strip()

    parts: list[str] = []
    daw_instr_count = 0
    mem_entries_count = 0
    rag_context_chars = 0

    if persona_prompt:
        parts.append(persona_prompt)
    if daw_prompt:
        parts.append(daw_prompt)

    # Force-include: user-attached boocode files (prepended before ## Repo Context so
    # they are seen first by the model; see 2026-04-22 Phase 4 plan Task 1).
    boocode_prepend = ""
    refs = list(boocode_files or [])
    if refs and daw_table_mode == "boocode":
        boocode_prepend = await _render_boocode_attachments(
            refs,
            daw_repo_path,
            BOOCODE_ATTACH_CHAR_BUDGET,
        )
        if boocode_prepend:
            logger.info("chat_boocode_attached chars=%s daw=%s", len(boocode_prepend), str(daw_id))

    if (
        daw_table_mode == "boocode"
        and daw_id is not None
        and user_query_for_rag
        and str(user_query_for_rag).strip()
        and chat.get("rag_enabled") is not False
    ):
        repo_chunks = await retrieve_repo_chunks(
            conn,
            str(daw_id),
            str(user_query_for_rag).strip(),
            top_k=20,
        )
        repo_block = ""
        if repo_chunks:
            repo_block = _format_repo_chunks(repo_chunks)
        combined = boocode_prepend + repo_block
        if combined:
            parts.append(combined)
    elif boocode_prepend:
        parts.append(boocode_prepend)

    if daw_id:
        daw_instructions = await conn.fetch(
            "SELECT content AS instruction FROM daw_instructions WHERE daw_id = $1::uuid ORDER BY created_at",
            daw_id,
        )
        if daw_instructions:
            daw_instr_count = len(daw_instructions)
            instr_text = "\n".join([f"- {r['instruction']}" for r in daw_instructions])
            parts.append(f"### DAW Instructions\n{instr_text}")

        daw_mem_rows = await conn.fetch(
            "SELECT content FROM daw_memory WHERE daw_id = $1::uuid ORDER BY created_at ASC",
            daw_id,
        )
        if daw_mem_rows:
            mem_lines = "\n".join(f"- {r['content']}" for r in daw_mem_rows)
            parts.append(f"[DAW Memory]\n{mem_lines}")

        # Skills injection: DAW skills + optional session skills (deduplicated)
        session_skill_set = set(session_skill_ids) if session_skill_ids else set()
        if daw_id and not session_skill_set:
            # Only fetch DAW skills if no session skills provided (session skills override DAW skills)
            skill_rows = await conn.fetch(
                """
                SELECT s.raw_content 
                FROM daw_skills ds
                JOIN skills s ON s.id = ds.skill_id
                WHERE ds.daw_id = $1::uuid AND ds.active = true
                ORDER BY ds.added_at DESC
                """,
                daw_id,
            )
            for sr in skill_rows:
                if sr["raw_content"]:
                    parts.append(f"\n---\n## Active Skill\n{sr['raw_content']}")
        elif session_skill_set:
            # Fetch session skills only
            if session_skill_set:
                skill_rows = await conn.fetch(
                    """
                    SELECT id, raw_content FROM skills WHERE id = ANY($1::uuid[])
                    """,
                    list(session_skill_set),
                )
                for sr in skill_rows:
                    if sr["raw_content"]:
                        parts.append(f"\n---\n## Active Skill\n{sr['raw_content']}")

    if daw_id is not None and include_site_private and user_query_for_rag:
        memory_facts = await retrieve_memory_facts(str(user_query_for_rag), mode, conn)
        if memory_facts:
            mem_entries_count = len(memory_facts)
            bullets = "\n".join([f"- {f}" for f in memory_facts])
            parts.append(f"### Relevant Context\n{bullets}")

    if daw_id is not None:
        cf_rows = await conn.fetch(
            """
            SELECT filename, content FROM daw_context_files
            WHERE daw_id = $1::uuid
            ORDER BY sort_order ASC NULLS LAST, created_at ASC
            """,
            daw_id,
        )
        for cf in cf_rows:
            parts.append(f"[Context file: {cf['filename']}]\n{cf['content']}")

    if include_site_private:
        ci_rows = await conn.fetch(
            """
            SELECT scope, content FROM custom_instructions
            WHERE scope IN ('global', $1::text) AND btrim(content) <> ''
            ORDER BY CASE WHEN scope = 'global' THEN 0 ELSE 1 END, scope ASC
            """,
            mode,
        )
        custom_instr = "\n\n".join(
            (r["content"] or "").strip() for r in ci_rows if (r["content"] or "").strip()
        )
        if custom_instr:
            parts.append(custom_instr)

    q_for_rag = str(user_query_for_rag or "").strip()
    rag_disabled = daw_rag_mode_effective == "off"
    use_intent_gate = daw_rag_mode_effective == "auto"
    intent_allows = (await should_retrieve(q_for_rag, mode)) if (q_for_rag and use_intent_gate) else True
    if (
        daw_id is not None
        and q_for_rag
        and chat.get("rag_enabled") is not False
        and not rag_disabled
        and use_intent_gate
        and not intent_allows
    ):
        logger.info(
            "RAG skipped by intent gate query_words=%d mode=%s",
            len(q_for_rag.split()),
            mode,
        )

    rag_ok = (
        not rag_disabled
        and bool(user_query_for_rag and str(user_query_for_rag).strip())
        and daw_id is not None
        and chat.get("rag_enabled") is not False
        and (intent_allows if use_intent_gate else True)
    )
    sse_rag_meta: dict[str, int] | None = None
    if rag_ok:
        cid = chat.get("id")
        if cid is not None:
            sel = await conn.fetch(
                "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
                cid,
            )
            source_ids = [str(r["source_id"]) for r in sel]
            if not source_ids:
                daw_sources = await conn.fetch(
                    "SELECT id FROM sources WHERE daw_id = $1::uuid AND embedding_status = 'complete'",
                    uuid.UUID(str(daw_id)),
                )
                source_ids = [str(r["id"]) for r in daw_sources]
            if source_ids:
                rag_block, rag_n = await retrieve_context(
                    str(user_query_for_rag).strip(),
                    str(daw_id),
                    source_ids,
                )
                if rag_block:
                    parts.append(rag_block)
                    rag_context_chars = len(rag_block)
                    sse_rag_meta = {"count": rag_n, "chars": rag_context_chars}

    assembled = "\n\n".join(parts)

    mem_text = ""
    if daw_id is not None and include_site_private:
        mem = await conn.fetchrow("SELECT content FROM mode_memory WHERE mode = $1", mode)
        mem_text = (mem["content"] or "").strip() if mem else ""
        if mem_text:
            if len(mem_text) > 2000:
                mem_text = mem_text[:2000] + "\n[truncated]"
            block = "## What I know about you:\n" + mem_text
            assembled = f"{assembled}\n\n{block}" if assembled else block

    preview = (assembled[:2000] + "…") if len(assembled) > 2000 else assembled
    logger.info(
        "assembled prompt mode=%s daw_id=%s is_daw_chat=%s len=%d daw_instruction_rows=%d "
        "memory_entry_rows=%d mode_memory_len=%d rag_context_chars=%d preview=%s",
        mode,
        str(daw_id) if daw_id else None,
        daw_id is not None,
        len(assembled),
        daw_instr_count,
        mem_entries_count,
        len(mem_text),
        rag_context_chars,
        preview,
    )
    logger.debug("assembled prompt full text=%s", assembled)

    return assembled, sse_rag_meta


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _inference_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _openai_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("BIFROST_API_KEY") or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _clean_auto_title(raw: str) -> str:
    t = (raw or "").strip()
    while len(t) >= 2 and t[0] in "\"'" and t[0] == t[-1]:
        t = t[1:-1].strip()
    return (t.strip(" \"'") or "")[:60]


async def _openai_short_chat_title(model: str, user_message_text: str) -> str | None:
    """Non-streaming title via OpenAI-compatible /v1/chat/completions; returns None on failure."""
    base = _inference_base()
    excerpt = (user_message_text or "")[:300]
    prompt = (
        "Generate a short chat title (4-6 words, no punctuation, no quotes) for a conversation "
        f"that starts with this message: {excerpt}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 48,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.post(
                f"{base}/v1/chat/completions",
                json=payload,
                headers=_openai_headers(),
            )
            if r.status_code >= 400:
                return None
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            msg = choices[0].get("message") or {}
            raw = (msg.get("content") or "").strip()
            cleaned = _clean_auto_title(raw)
            return cleaned or None
    except Exception:
        return None


async def _stream_ollama(
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[bytes]:
    base = _inference_base()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    logger.info("openai /v1/chat/completions model=%s", model)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{base}/v1/chat/completions",
                json=payload,
                headers=_openai_headers(),
            ) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(json.dumps({"error": f"Inference error {resp.status_code}: {err}"}))
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        err = chunk.get("error")
                        if err is not None:
                            yield _sse(json.dumps({"error": str(err)}))
                            return
                        choices = chunk.get("choices")
                        if isinstance(choices, list) and len(choices) > 0:
                            delta = (choices[0] or {}).get("delta") or {}
                            piece = delta.get("content") or ""
                            if piece:
                                yield _sse(json.dumps({"content": piece}))
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    yield _sse("[DONE]")


class ChatCreate(BaseModel):
    title: str | None = None
    model: str | None = Field(default=None)
    daw_id: uuid.UUID | None = None
    mode: str = "booops"
    web_search_enabled: bool | None = None
    persona_id: uuid.UUID | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    web_search_enabled: bool | None = None
    persona_id: uuid.UUID | None = None
    daw_id: uuid.UUID | None = None


class BoocodeFileRef(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    model: str | None = None
    session_skill_ids: list[str] | None = None
    boocode_files: list[BoocodeFileRef] | None = None


class WebSearchToggleBody(BaseModel):
    enabled: bool


class SourceSelectionBody(BaseModel):
    source_ids: list[uuid.UUID] = Field(default_factory=list)


def _chat_row(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "daw_id": str(r["daw_id"]) if r["daw_id"] else None,
        "mode": r["mode"],
        "persona_id": str(r["persona_id"]) if r["persona_id"] else None,
        "model": r["model"],
        "web_search_enabled": r["web_search_enabled"],
        "rag_enabled": r["rag_enabled"],
        "pruning_summary": r["pruning_summary"],
        "message_count": r["message_count"],
        "is_main_chat": r["is_main_chat"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _message_row(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "chat_id": str(r["chat_id"]),
        "role": r["role"],
        "content": r["content"],
        "model": r["model"],
        "tokens_used": r["tokens_used"],
        "sources_used": r["sources_used"],
        "forked_from": str(r["forked_from"]) if r["forked_from"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.post("/")
async def create_chat(body: ChatCreate, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    allowed_modes = ("booops", "808notes", "boocode")
    mode = body.mode if body.mode in allowed_modes else "booops"
    default_model = os.environ.get("DEFAULT_MODEL", "llama-gpu/qwen3.5-9b-exl3")
    async with pool.acquire() as conn:
        await assert_persona_usable(conn, principal, body.persona_id)
        await assert_daw_usable(conn, principal, body.daw_id)
        if body.daw_id is not None:
            daw_mode = await conn.fetchval(
                "SELECT mode FROM daws WHERE id = $1::uuid", body.daw_id
            )
            if daw_mode in allowed_modes:
                mode = daw_mode
        persona_id_for_insert = body.persona_id
        if persona_id_for_insert is None:
            persona_id_for_insert = await _default_persona_id_for_mode(conn, mode)
        row = await conn.fetchrow(
            """
            INSERT INTO chats (title, daw_id, mode, model, web_search_enabled, rag_enabled, persona_id, owner_id)
            VALUES ($1, $2, $3,
                COALESCE(
                    $4,
                    (SELECT NULLIF(TRIM(model), '') FROM daws WHERE id = $2::uuid),
                    (SELECT value FROM global_settings WHERE key = (
                        CASE
                            WHEN $3::text = '808notes' THEN 'default_model_808notes'
                            WHEN $3::text = 'boocode' THEN 'default_model_boocode'
                            ELSE 'default_model'
                        END
                    ) LIMIT 1),
                    $6
                ),
                COALESCE($5, FALSE),
                $9,
                $7,
                $8)
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            body.title,
            body.daw_id,
            mode,
            body.model,
            body.web_search_enabled,
            default_model,
            persona_id_for_insert,
            principal["user_id"],
            body.daw_id is not None,
        )
    return _chat_row(row)


@router.get("/")
async def list_chats(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = Query("booops"),
    daw_id: uuid.UUID | None = Query(None, description="When set, only chats for this DAW workspace."),
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    m = mode if mode in ("booops", "808notes") else "booops"
    cols = """
                id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
    """
    async with pool.acquire() as conn:
        if daw_id is not None:
            rows = await conn.fetch(
                f"""
                SELECT {cols}
                FROM chats
                WHERE mode = $3 AND daw_id = $4::uuid
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
                m,
                daw_id,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM chats WHERE mode = $1 AND daw_id = $2::uuid",
                m,
                daw_id,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT {cols}
                FROM chats
                WHERE mode = $3
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
                m,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM chats WHERE mode = $1",
                m,
            )
    return {"items": [_chat_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/non-daw")
async def delete_non_daw_chats(
    mode: str = Query("booops"),
    principal: dict[str, Any] = Depends(get_principal),
):
    """Delete all chats in the given mode that are not tied to a DAW (daw_id IS NULL)."""
    pool = await get_pool()
    m = mode if mode in ("booops", "808notes") else "booops"
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            """
            WITH deleted AS (
                DELETE FROM chats
                WHERE mode = $1 AND daw_id IS NULL
                RETURNING 1
            )
            SELECT COUNT(*)::int FROM deleted
            """,
            m,
        )
    return {"deleted": int(deleted or 0), "mode": m}


@router.get("/{chat_id}")
async def get_chat(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _chat_row(row)


@router.patch("/{chat_id}/web-search")
async def patch_web_search(
    chat_id: uuid.UUID,
    body: WebSearchToggleBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        row = await conn.fetchrow(
            """
            UPDATE chats
            SET web_search_enabled = $2, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING web_search_enabled
            """,
            chat_id,
            body.enabled,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"web_search_enabled": bool(row["web_search_enabled"])}


@router.get("/{chat_id}/source-selection")
async def get_source_selection(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = await conn.fetch(
            "SELECT source_id FROM chat_source_selections WHERE chat_id = $1::uuid",
            chat_id,
        )
    return {"chat_id": str(chat_id), "source_ids": [str(r["source_id"]) for r in rows]}


@router.put("/{chat_id}/source-selection")
async def put_source_selection(
    chat_id: uuid.UUID,
    body: SourceSelectionBody,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        for sid in body.source_ids:
            ok = await conn.fetchval("SELECT 1 FROM sources WHERE id = $1::uuid", sid)
            if ok is None:
                raise HTTPException(status_code=400, detail=f"Unknown source_id {sid}")
        async with conn.transaction():
            await conn.execute("DELETE FROM chat_source_selections WHERE chat_id = $1::uuid", chat_id)
            for sid in body.source_ids:
                await conn.execute(
                    """
                    INSERT INTO chat_source_selections (chat_id, source_id)
                    VALUES ($1::uuid, $2::uuid)
                    """,
                    chat_id,
                    sid,
                )
    return {"chat_id": str(chat_id), "source_ids": [str(s) for s in body.source_ids]}


@router.patch("/{chat_id}")
async def patch_chat(
    chat_id: uuid.UUID,
    body: ChatPatch,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    data = body.model_dump(exclude_unset=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        if not data:
            return _chat_row(row)
        new_title = data.get("title", row["title"])
        new_model = data.get("model", row["model"])
        new_ws = data.get("web_search_enabled", row["web_search_enabled"])
        new_persona = row["persona_id"] if "persona_id" not in data else data["persona_id"]
        new_daw = row["daw_id"] if "daw_id" not in data else data["daw_id"]

        if new_persona is not None:
            await assert_persona_usable(conn, principal, new_persona)
        if new_daw is not None:
            await assert_daw_usable(conn, principal, new_daw)

        updated = await conn.fetchrow(
            """
            UPDATE chats
            SET title = $2, model = $3, web_search_enabled = $4,
                persona_id = $5, daw_id = $6, updated_at = NOW()
            WHERE id = $1::uuid
            RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                pruning_summary, message_count, is_main_chat, created_at, updated_at
            """,
            chat_id,
            new_title,
            new_model,
            new_ws,
            new_persona,
            new_daw,
        )
    return _chat_row(updated)


@router.delete("/{chat_id}")
async def delete_chat(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if cur is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        result = await conn.execute("DELETE FROM chats WHERE id = $1::uuid", chat_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"ok": True}


@router.get("/{chat_id}/messages")
async def list_messages(chat_id: uuid.UUID, principal: dict[str, Any] = Depends(get_principal)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
        if c is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = await conn.fetch(
            """
            SELECT id, chat_id, role, content, model, tokens_used, sources_used, forked_from, created_at
            FROM messages
            WHERE chat_id = $1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )
    return {"items": [_message_row(r) for r in rows]}


@router.post("/{chat_id}/messages/{message_id}/fork")
async def fork_chat_at_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            src = await conn.fetchrow(
                """
                SELECT id, title, mode, model, persona_id, daw_id,
                    web_search_enabled, rag_enabled
                FROM chats
                WHERE id = $1::uuid
                """,
                chat_id,
            )
            if src is None:
                raise HTTPException(status_code=404, detail="Chat not found")

            target = await conn.fetchrow(
                """
                SELECT id FROM messages
                WHERE id = $1::uuid AND chat_id = $2::uuid
                """,
                message_id,
                chat_id,
            )
            if target is None:
                raise HTTPException(status_code=400, detail="Message does not belong to this chat")

            msg_rows = await conn.fetch(
                """
                SELECT id, role, content, model, tokens_used, sources_used
                FROM messages
                WHERE chat_id = $1::uuid
                ORDER BY created_at ASC, id ASC
                """,
                chat_id,
            )
            copies: list[Any] = []
            for r in msg_rows:
                copies.append(r)
                if r["id"] == message_id:
                    break
            else:
                raise HTTPException(status_code=400, detail="Message not found in chat history")

            base_title = ((src["title"] or "") or "chat").strip() or "chat"
            fork_title = ("Fork of " + base_title)[:80]

            new_chat = await conn.fetchrow(
                """
                INSERT INTO chats (
                    title, daw_id, mode, model, persona_id,
                    web_search_enabled, rag_enabled, message_count,
                    owner_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id, title, daw_id, mode, persona_id, model, web_search_enabled, rag_enabled,
                    pruning_summary, message_count, is_main_chat, created_at, updated_at
                """,
                fork_title,
                src["daw_id"],
                src["mode"],
                src["model"],
                src["persona_id"],
                src["web_search_enabled"],
                src["rag_enabled"],
                len(copies),
                principal["user_id"],
            )
            assert new_chat is not None
            new_id = new_chat["id"]

            for r in copies:
                mid = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO messages (
                        id, chat_id, role, content, model, tokens_used, sources_used, forked_from
                    )
                    VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid
                    )
                    """,
                    mid,
                    new_id,
                    r["role"],
                    r["content"],
                    r["model"],
                    r["tokens_used"],
                    r["sources_used"],
                    r["id"],
                )

    return _chat_row(new_chat)


@router.post("/{chat_id}/messages")
async def append_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    principal: dict[str, Any] = Depends(get_principal),
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            """
            SELECT id, title, model, pruning_summary, mode, persona_id, web_search_enabled, daw_id,
                message_count, rag_enabled
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")

        daw_row = None
        if chat["daw_id"] is not None:
            daw_row = await conn.fetchrow(
                "SELECT model FROM daws WHERE id = $1::uuid",
                chat["daw_id"],
            )
        daw_pins_model = bool(
            daw_row is not None and daw_row["model"] and str(daw_row["model"]).strip()
        )
        chat_model = (body.model or chat["model"] or "").strip()
        effective_model = str(daw_row["model"]).strip() if daw_pins_model else chat_model
        if not effective_model:
            raise HTTPException(status_code=400, detail="No model set for chat")

        if daw_pins_model or body.model is not None:
            await conn.execute(
                "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                chat_id,
                effective_model,
            )

        first_exchange_for_auto_title = int(chat["message_count"] or 0) == 0

        user_msg_id = uuid.uuid4()
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model)
                VALUES ($1::uuid, $2::uuid, 'user', $3, $4)
                """,
                user_msg_id,
                chat_id,
                body.content.strip(),
                effective_model,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )

        msg_rows = await conn.fetch(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id = $1::uuid
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
        )

        assembled, rag_sse_meta = await _assembled_system_prompt(
            conn,
            chat,
            user_query_for_rag=body.content.strip(),
            include_site_private=True,
            session_skill_ids=body.session_skill_ids,
            boocode_files=body.boocode_files,
        )

        user_profile_block = ""
        try:
            uid = principal.get("user_id")
            if uid:
                prof = await conn.fetchrow(
                    "SELECT display_name, username, bio FROM users WHERE id = $1::uuid",
                    uid,
                )
                if prof:
                    name = (prof["display_name"] or prof["username"] or "").strip()
                    bio = (prof["bio"] or "").strip()
                    if name or bio:
                        lines = ["## About the user you are talking to"]
                        if name:
                            lines.append(f"Name: {name}")
                        if bio:
                            lines.append(f"About: {bio}")
                        user_profile_block = "\n".join(lines)
        except Exception:
            user_profile_block = ""

    summary = chat["pruning_summary"]
    user_message_text = body.content.strip()

    async def gen() -> AsyncIterator[bytes]:
        sources_list: list[dict[str, str]] = []
        extra_search = ""
        if bool(chat["web_search_enabled"]):
            sources_list, extra_search = await searx_search_sources(
                user_message_text,
                mode=str(chat["mode"] or "booops"),
            )
        if sources_list:
            yield _sse(json.dumps({"type": "search_sources", "sources": sources_list}))
        if rag_sse_meta:
            yield _sse(
                json.dumps(
                    {
                        "type": "rag_context",
                        "chunks": rag_sse_meta["chars"],
                        "count": rag_sse_meta["count"],
                    }
                )
            )

        api_messages: list[dict[str, str]] = []
        system_blocks: list[str] = []
        if assembled:
            system_blocks.append(assembled)
        if user_profile_block:
            system_blocks.append(user_profile_block)
        if summary:
            system_blocks.append("Compressed prior conversation summary:\n" + summary)
        if extra_search:
            system_blocks.append(
                "## Web search results (use if relevant; the user enabled web search for this turn):\n" + extra_search
            )
        if system_blocks:
            api_messages.append({"role": "system", "content": "\n\n".join(system_blocks)})
        for r in msg_rows:
            role = r["role"]
            if role not in ("user", "assistant", "system"):
                continue
            api_messages.append({"role": role, "content": r["content"] or ""})

        full: list[str] = []
        had_error = False
        logger.info(
            "chat inference chat_id=%s model=%s daw_id=%s",
            str(chat_id),
            effective_model,
            str(chat["daw_id"]) if chat["daw_id"] else None,
        )
        stream = _stream_ollama(
            effective_model,
            api_messages,
        )
        try:
            async for chunk in stream:
                try:
                    line = chunk.decode("utf-8")
                except Exception:
                    yield chunk
                    continue
                payload_end = ""
                if line.startswith("data: "):
                    payload_end = line[6:].strip()
                defer_done = payload_end == "[DONE]"
                if not defer_done:
                    yield chunk
                if not line.startswith("data: "):
                    continue
                if defer_done:
                    continue
                try:
                    obj = json.loads(payload_end)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    had_error = True
                if obj.get("content"):
                    full.append(obj["content"])
        except Exception as e:
            yield _sse(json.dumps({"error": str(e)}))
            had_error = True

        if had_error:
            return

        assistant_text = "".join(full).strip()
        if not assistant_text:
            return

        assist_id = uuid.uuid4()
        p = await get_pool()
        async with p.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model)
                VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4)
                """,
                assist_id,
                chat_id,
                assistant_text,
                effective_model,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )

        title_emit: str | None = None
        has_custom_title = bool((chat["title"] or "").strip())
        if first_exchange_for_auto_title and assistant_text and not has_custom_title:
            new_title: str | None = None
            try:
                new_title = await _openai_short_chat_title(effective_model, user_message_text)
            except Exception:
                new_title = None
            if not new_title:
                first_line = (user_message_text or "").strip().split("\n")[0].strip()
                new_title = _clean_auto_title(first_line)[:60] if first_line else None
            if not new_title:
                new_title = "New chat"
            try:
                async with p.acquire() as conn_title:
                    await conn_title.execute(
                        "UPDATE chats SET title = $2, updated_at = NOW() WHERE id = $1::uuid",
                        chat_id,
                        new_title,
                    )
                title_emit = new_title
            except Exception:
                pass
        if title_emit:
            yield _sse(json.dumps({"type": "title_update", "title": title_emit}))

        auto_mem = _first_auto_memory_sentence(assistant_text)
        if auto_mem:
            chat_mode = chat["mode"] if chat["mode"] in ("booops", "808notes") else "booops"
            async with p.acquire() as conn_mem:
                mem_row = await conn_mem.fetchrow(
                    """
                    INSERT INTO memory_entries (content, source, mode)
                    VALUES ($1, 'auto', $2)
                    RETURNING id
                    """,
                    auto_mem,
                    chat_mode,
                )
                if mem_row:
                    try:
                        from services.embeddings import embed_text

                        emb = await embed_text(auto_mem)
                        if emb:
                            await conn_mem.execute(
                                """
                                UPDATE memory_entries
                                SET embedding = $1::vector, embedded_at = NOW()
                                WHERE id = $2::uuid
                                """,
                                str(emb),
                                mem_row["id"],
                            )
                    except Exception as e:
                        logger.warning("Failed to embed memory entry: %s", e)

        await summarize_and_compress(str(chat_id), p)

        yield _sse("[DONE]")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
