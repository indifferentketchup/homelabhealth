"""Chat CRUD, message listing, and streaming sends (OpenAI-compatible local inference or Claude)."""

import asyncio
import hashlib
import os
import pathlib
import time
import uuid

import json
import logging
from typing import Any, AsyncIterator

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from deps import (
    assert_workspace_usable,
    get_principal,
)
from db import get_pool
from services.audit import AuditEventHandle, AuditRecord, audit_event, insert_audit_event
from services.deid import is_enabled as deid_enabled, redact_text
from services.provider_client import (
    Provider,
    build_headers,
    resolve_provider_for_workspace,
)
from services.pruning import summarize_and_compress
from services.crypto import encrypt_column, decrypt_column
from services.supervisor_worker import is_complex_query, run_supervisor_worker
from services.reasoning_strip import strip_thinking_text
from services.hooks import (
    HookContext,
    HookResult,
    fire_on_stop,
    fire_on_user_prompt,
    fire_post_tool_execution,
    fire_pre_tool_execution,
    set_hook_context,
    reset_hook_context,
)
from services.safeguards import current_version
from services.searx import searx_search_sources
from services.chat_jobs import job_registry
from services.prompt_assembly import (
    _assembled_system_prompt,
    _stream_inference,
    _openai_short_chat_title,
    _first_auto_memory_sentence,
    _normalize_messages_for_inference,
    _clean_auto_title,
)
from services.eval_judge import maybe_fire_groundedness_eval

router = APIRouter()
logger = logging.getLogger(__name__)


async def _durable_streaming_enabled() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM global_settings WHERE key = 'durable_streaming_enabled'"
        )
        return row is not None and (row["value"] or "").lower() in ("true", "1", "yes")


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    model: str | None = None
    attached_source_ids: list[str] | None = None
    retry_last: bool = False


def _scrub_pg_text(value: str) -> str:
    """Strip null bytes from a string before INSERT into a Postgres TEXT
    column. asyncpg + Postgres reject 0x00 in TEXT with
    `CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8"`.

    The frontend gates image attachments out at the input layer, but this
    is defense-in-depth -- a stray null byte from any other binary that
    slipped past the MIME check (zip dropped as octet-stream, etc.) would
    otherwise 500 the messages endpoint.
    """
    if not value:
        return value
    return value.replace("\x00", "")


class ApprovalResponseBody(BaseModel):
    action: str = Field(
        ..., pattern=r"^(accept|reject|edit)$",
        description="User's decision: accept, reject, or edit",
    )
    edited_content: str | None = Field(
        default=None,
        description="Revised user message (required when action=edit)",
    )


class DeepResearchBody(BaseModel):
    query: str


@router.post("/{chat_id}/messages")
async def append_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            """
            SELECT id, title, model, pruning_summary, web_search_enabled, workspace_id,
                message_count, rag_enabled
            FROM chats
            WHERE id = $1::uuid
            """,
            chat_id,
        )
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")

        audit._target_type = "chat"
        audit._target_id = str(chat_id)

        # Provider resolution: every chat send must go through the workspace's
        # configured provider. Workspaces without a provider raise the exact
        # spec message. Chats without a workspace can't have a provider either.
        if chat["workspace_id"] is None:
            raise HTTPException(
                status_code=400,
                detail="No provider configured for this workspace. Open Settings → Workspace to pick one.",
            )
        provider, ws_model = await resolve_provider_for_workspace(chat["workspace_id"])
        # The workspace pins (provider_id, model) together via CHECK constraint,
        # so ws_model is always non-empty here. body.model and chat.model are
        # ignored once we're past the resolver — workspace owns the truth.
        effective_model = ws_model

        # Fetch is_bundled so the gen() closure knows whether data leaves the
        # operator's network. Bundled providers (hlh_chat) stay on-box; external
        # providers require de-identification of user messages before send.
        provider_is_bundled_row = await conn.fetchval(
            "SELECT is_bundled FROM providers WHERE id = $1::uuid",
            provider.id,
        )
        provider_is_bundled: bool = bool(provider_is_bundled_row or False)

        # Keep chat.model in sync with the resolved model (purely informational;
        # send-time always re-resolves via the workspace).
        if (chat["model"] or "") != effective_model:
            await conn.execute(
                "UPDATE chats SET model = $2, updated_at = NOW() WHERE id = $1::uuid",
                chat_id,
                effective_model,
            )

        first_exchange_for_auto_title = int(chat["message_count"] or 0) == 0

        scrubbed_user_content = _scrub_pg_text(body.content.strip())
        skip_user_insert = False
        if body.retry_last:
            last_row = await conn.fetchrow(
                """
                SELECT id, role FROM messages
                WHERE chat_id = $1::uuid AND compacted_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                chat_id,
            )
            if last_row and last_row["role"] == "user":
                skip_user_insert = True
                user_msg_id = last_row["id"]

        if not skip_user_insert:
            user_msg_id = uuid.uuid4()
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO messages (id, chat_id, role, content, model, ai_generated)
                    VALUES ($1::uuid, $2::uuid, 'user', $3, $4, $5)
                    """,
                    user_msg_id,
                    chat_id,
                    encrypt_column(scrubbed_user_content, str(user_msg_id)),
                    effective_model,
                    False,
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
            SELECT id, role, content
            FROM messages
            WHERE chat_id = $1::uuid AND compacted_at IS NULL
            ORDER BY created_at ASC, id ASC
            """,
            chat_id,
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
        except Exception as exc:
            logger.warning("user profile fetch failed: %s", exc)
            user_profile_block = ""

    summary = chat["pruning_summary"]
    user_message_text = scrubbed_user_content

    from services.guard import scan_input, scan_output
    input_scan = scan_input(user_message_text)
    if not input_scan.passed:
        try:
            _pool = await get_pool()
            async with _pool.acquire() as _aconn:
                await insert_audit_event(_aconn, AuditRecord(
                    request_id=request.state.request_id,
                    actor=principal.get("username", "unknown"),
                    action="safeguard.refuse.input",
                    target_type="chat",
                    target_id=str(chat_id),
                    status_code=422,
                    payload_hash=hashlib.sha256(user_message_text.encode("utf-8")).digest(),
                ))
        except Exception:
            logger.warning("audit insert failed for input guard refusal", exc_info=True)
        return JSONResponse(
            status_code=422,
            content={
                "error": "input_blocked",
                "guard_flags": input_scan.to_json(),
                "message": "Your message was blocked by the input guard. Please rephrase.",
            },
        )

    hook_ctx = HookContext(
        chat_id=str(chat_id),
        message_id=str(user_msg_id),
        user_id=str(principal.get("user_id", "")),
        workspace_id=str(chat["workspace_id"]) if chat["workspace_id"] else None,
        request_id=getattr(getattr(request, 'state', None), 'request_id', None),
    )
    set_hook_context(hook_ctx)
    await fire_on_user_prompt(user_message_text)

    from services.approval_gate import (
        ApprovalAction as _ApprovalAction,
        get_gate,
        should_request_approval,
    )
    from services.safeguards_engine import get_engine as _get_safeguard_engine

    _safeguard_engine = _get_safeguard_engine()
    _safeguard_matches = _safeguard_engine.get_cached_result()
    if _safeguard_matches:
        _needs_approval, _approval_reason = should_request_approval(_safeguard_matches)
        if _needs_approval:
            _gate = get_gate()
            _req = _gate.request_approval(
                str(chat_id),
                reason=_approval_reason,
                prompt=_approval_reason,
            )
            if await _durable_streaming_enabled():
                _approval_assist_id = uuid.uuid4()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO messages (id, chat_id, role, content, model, ai_generated, status)
                        VALUES ($1::uuid, $2::uuid, 'assistant', '', $3, TRUE, 'approval_pending')
                        """,
                        _approval_assist_id, chat_id, effective_model,
                    )
                return JSONResponse(
                    status_code=202,
                    content={
                        "user_message_id": str(user_msg_id),
                        "assistant_message_id": str(_approval_assist_id),
                        "status": "approval_pending",
                        "approval": {
                            "reason": _req.reason,
                            "prompt": _req.prompt,
                            "options": _req.options,
                            "timeout_s": _req.timeout_s,
                        },
                    },
                )
            # For non-durable (SSE): gen() handles the approval event inline

    if await _durable_streaming_enabled():
        # 409 if another streaming or approval-pending assistant row exists
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM messages WHERE chat_id = $1::uuid AND role = 'assistant' AND status IN ('streaming', 'approval_pending')",
                chat_id,
            )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Another response is still streaming. Stop it first or wait for it to finish.",
            )

        # Insert assistant placeholder row
        assist_id = uuid.uuid4()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model, ai_generated, status)
                VALUES ($1::uuid, $2::uuid, 'assistant', '', $3, TRUE, 'streaming')
                """,
                assist_id, chat_id, effective_model,
            )

        # Fetch messages for inference context (exclude streaming rows)
        async with pool.acquire() as conn:
            job_msg_rows = await conn.fetch(
                """
                SELECT id, role, content, status
                FROM messages
                WHERE chat_id = $1::uuid AND compacted_at IS NULL AND status != 'streaming'
                ORDER BY created_at ASC, id ASC
                """,
                chat_id,
            )

        chat_dict = {
            "id": chat["id"],
            "title": chat["title"],
            "model": chat["model"],
            "pruning_summary": chat["pruning_summary"],
            "web_search_enabled": chat["web_search_enabled"],
            "workspace_id": chat["workspace_id"],
            "message_count": chat["message_count"],
            "rag_enabled": chat["rag_enabled"],
        }

        import services.inference_job as ij

        # _reg_cell is populated synchronously after registration — asyncio won't
        # yield between create_task and append so _run_job always sees the cell filled.
        _reg_cell: list = []

        async def _run_job():
            reg = _reg_cell[0] if _reg_cell else None
            if reg is None:
                logger.error(
                    "inference job has no registration: chat_id=%s assist_id=%s",
                    chat_id, assist_id,
                )
                return
            await ij.run_inference_job(
                registration=reg,
                chat_id=chat_id,
                assistant_id=assist_id,
                provider=provider,
                effective_model=effective_model,
                chat_record=chat_dict,
                msg_rows=[dict(r) for r in job_msg_rows],
                user_message_text=user_message_text,
                user_profile_block=user_profile_block,
                provider_is_bundled=provider_is_bundled,
                first_exchange_for_auto_title=first_exchange_for_auto_title,
                request_id=getattr(getattr(request, 'state', None), 'request_id', None),
                principal_username=principal.get("username", "unknown"),
                attached_source_ids=body.attached_source_ids,
            )

        task = asyncio.create_task(_run_job())
        reg = job_registry.register(chat_id, assist_id, task)
        _reg_cell.append(reg)

        async with audit.targeting("chat", chat_id):
            pass
        return JSONResponse(
            status_code=202,
            content={
                "user_message_id": str(user_msg_id),
                "assistant_message_id": str(assist_id),
                "status": "streaming",
            },
        )

    async def gen() -> AsyncIterator[bytes]:
        from services.pipeline_status import stage, model_is_loaded

        yield _sse(json.dumps({"type": "phase", "phase": "preparing"}))
        sources_list: list[dict[str, str]] = []
        extra_search = ""
        search_degraded = False
        if bool(chat["web_search_enabled"]):
            sources_list, extra_search, search_degraded = await searx_search_sources(
                user_message_text,
            )
        if sources_list:
            yield _sse(json.dumps({"type": "phase", "phase": "search"}))
            yield _sse(json.dumps({"type": "search_sources", "sources": sources_list}))
        elif search_degraded:
            yield _sse(json.dumps({
                "type": "warning",
                "message": "Web search failed; answering without web results.",
            }))

        async with pool.acquire() as status_conn:
            embed_model = await status_conn.fetchval(
                "SELECT value FROM global_settings WHERE key = 'embedding_model'"
            ) or "qwen3-embed"
            if not await model_is_loaded(embed_model):
                async with stage(status_conn, "loading", model=embed_model) as frame:
                    yield _sse(json.dumps(frame))
                    from services.embeddings import embed_text as _warm_embed
                    try:
                        await _warm_embed("warmup")
                    except Exception:
                        pass
                yield _sse(json.dumps({"type": "phase", "phase": "ready", "model": embed_model}))

        yield _sse(json.dumps({"type": "phase", "phase": "rag"}))
        assembled = ""
        rag_sse_meta: dict[str, int | bool] | None = None
        rag_block_text = ""
        try:
            async with pool.acquire() as rag_conn:
                assembled, rag_sse_meta, rag_block_text = await _assembled_system_prompt(
                    rag_conn,
                    chat,
                    user_query_for_rag=user_message_text,
                    include_site_private=True,
                )
        except Exception as exc:
            logger.error("RAG assembly failed chat_id=%s: %s", chat_id, exc)
            yield _sse(json.dumps({"error": "Document retrieval failed. Try again or start a fresh chat."}))
            yield _sse("[DONE]")
            return

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

        if rag_sse_meta and rag_sse_meta.get("degraded"):
            yield _sse(json.dumps({
                "type": "warning",
                "message": "Document retrieval failed; answering without your sources.",
            }))

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
        if body.attached_source_ids:
            attached_docs: list[str] = []
            for sid in body.attached_source_ids:
                try:
                    src_path = pathlib.Path(f"/data/uploads")
                    async with pool.acquire() as aconn:
                        srow = await aconn.fetchrow(
                            "SELECT name, mime_type, file_url FROM sources WHERE id = $1::uuid", uuid.UUID(sid)
                        )
                    if srow and srow["file_url"]:
                        fp = pathlib.Path(srow["file_url"])
                        if fp.exists():
                            file_raw = fp.read_bytes()
                            smime = (srow["mime_type"] or "text/plain").lower().split(";")[0].strip()
                            txt = None
                            if smime == "application/pdf":
                                from services.vision import extract_pdf_via_vision
                                txt = await extract_pdf_via_vision(file_raw)
                            elif smime.startswith("image/"):
                                from services.vision import extract_image_via_vision
                                txt = await extract_image_via_vision(file_raw, smime)
                            if not txt:
                                from services.chunking import parse_source_bytes as _parse
                                txt = _parse(file_raw, srow["mime_type"] or "text/plain")
                            if deid_enabled():
                                txt = redact_text(txt).text
                            attached_docs.append(f"[DOCUMENT: {srow['name']}]\n{txt}")
                except Exception as exc:
                    logger.warning("attached source %s read failed: %s", sid, exc)
            if attached_docs:
                system_blocks.append(
                    "### Attached documents (the user explicitly sent these to chat — read them fully):\n\n"
                    + "\n\n---\n\n".join(attached_docs)
                )
        if system_blocks:
            api_messages.append({"role": "system", "content": "\n\n".join(system_blocks)})
        for r in msg_rows:
            role = r["role"]
            if role not in ("user", "assistant", "system"):
                continue
            raw = r["content"] or ""
            api_messages.append({"role": role, "content": decrypt_column(raw, str(r["id"])) if raw else raw})

        # Mark last user message for approval-gate edit replacement
        for _i in range(len(api_messages) - 1, -1, -1):
            if api_messages[_i]["role"] == "user":
                api_messages[_i]["is_last_user"] = True
                break

        # De-identify user messages before sending to external providers.
        # Bundled providers (is_bundled=True) run on-box — no redaction needed.
        # System and assistant messages are not redacted (safeguard preamble +
        # historical assistant responses; see C5 Task B rationale).
        if deid_enabled() and not provider_is_bundled:
            for msg in api_messages:
                if msg["role"] == "user":
                    r = redact_text(msg["content"])
                    if r.had_phi:
                        logger.info(
                            "deid: redacted %d findings in user message before external inference",
                            len(r.findings),
                        )
                    msg["content"] = r.text

        full: list[str] = []
        had_error = False
        prompt_tokens_val: int | None = None
        completion_tokens_val: int | None = None
        logger.info(
            "chat inference chat_id=%s model=%s workspace_id=%s",
            str(chat_id),
            effective_model,
            str(chat["workspace_id"]) if chat["workspace_id"] else None,
        )
        async with pool.acquire() as status_conn:
            if not await model_is_loaded(effective_model):
                from services.model_inventory import get_inventory, MODEL_RAM_MIB
                tier_row = await status_conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
                _tier = tier_row["tier"] if tier_row else "cpu-std"
                inv = await get_inventory(_tier)
                target_ram = MODEL_RAM_MIB.get(effective_model, 0)
                if inv["loaded_ram_mib"] + target_ram > inv["budget_mib"]:
                    loaded = [m for m in inv["models"] if m["state"] == "loaded" and m["provider"] == "router" and m["id"] != effective_model]
                    if loaded:
                        lru = min(loaded, key=lambda m: m.get("last_used_ms") or 0)
                        async with stage(status_conn, "unloading", model=lru["id"]) as uframe:
                            yield _sse(json.dumps(uframe))
                async with stage(status_conn, "loading", model=effective_model) as frame:
                    yield _sse(json.dumps(frame))
                    try:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as warm_client:
                            await warm_client.post(
                                f"{provider.base_url}/v1/chat/completions",
                                json={"model": effective_model, "messages": [{"role": "user", "content": "."}], "max_tokens": 1, "stream": False},
                                headers=build_headers(provider),
                            )
                    except Exception as exc:
                        logger.warning("model warm-up failed for %s: %s", effective_model, exc)
                        yield _sse(json.dumps({"type": "warning", "message": f"Model warm-up failed for {effective_model}. Inference will still be attempted."}))
                yield _sse(json.dumps({"type": "phase", "phase": "ready", "model": effective_model}))

        # Bound here so the post_tool_execution timing read below is always defined,
        # including on the complex-query path (which does not reach the else branch's
        # reassignment). The else branch resets it just before the inference hook fires.
        _hook_start = time.monotonic()

        # Complexity heuristic: route complex queries through supervisor-worker
        # decomposition for parallel sub-answer synthesis.
        if is_complex_query(user_message_text):
            yield _sse(json.dumps({"type": "phase", "phase": "decomposing"}))
            try:
                sw_result = await run_supervisor_worker(
                    user_message_text, provider, effective_model,
                    source_context=assembled,
                )
                full = [sw_result.merged]
                assistant_text = sw_result.merged
                if sw_result.contradictions:
                    yield _sse(json.dumps({
                        "type": "contradictions",
                        "contradictions": sw_result.contradictions,
                    }))
            except Exception as exc:
                logger.error("supervisor_worker failed: %s", exc)
                yield _sse(json.dumps({"error": "Analysis failed. Check server logs for details."}))
                yield _sse("[DONE]")
                return
        else:
            yield _sse(json.dumps({"type": "phase", "phase": "generating"}))

            # Approval gate: if a pending request exists (from the check above
            # or from an explicit request_approval call), yield an SSE event
            # and wait for the user's decision.
            _approval_gate = get_gate()
            if _approval_gate.is_pending(str(chat_id)):
                _pending_req = _approval_gate.get_pending(str(chat_id))
                if _pending_req:
                    yield _sse(json.dumps(_pending_req.to_sse_event()))
                _approval_result = await _approval_gate.wait_for_result(
                    str(chat_id),
                )
                if _approval_result.action == _ApprovalAction.REJECT:
                    yield _sse(json.dumps({
                        "error": "Inference was rejected by user.",
                    }))
                    yield _sse("[DONE]")
                    return
                if _approval_result.action == _ApprovalAction.EDIT:
                    # Re-emit phase because we're retrying with edited content
                    yield _sse(json.dumps({
                        "type": "phase", "phase": "editing",
                    }))
                    # Rebuild messages with edited user content
                    api_messages = [
                        (
                            {"role": m["role"], "content": _approval_result.edited_content}
                            if m["role"] == "user" and m.get("is_last_user", False)
                            else m
                        )
                        for m in api_messages
                    ]
                    yield _sse(json.dumps({
                        "type": "phase", "phase": "generating",
                    }))

            # Hook: pre_tool_execution
            _hook_start = time.monotonic()
            hook_input = {"model": effective_model, "messages": api_messages}
            hook_result = await fire_pre_tool_execution("inference", hook_input)
            if hook_result.blocked:
                yield _sse(json.dumps({
                    "error": f"Tool execution blocked by hook: {hook_result.reason or 'blocked'}",
                }))
                yield _sse("[DONE]")
                return

            stream = _stream_inference(
                provider,
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
                    usage = obj.get("usage")
                    if usage:
                        prompt_tokens_val = usage.get("prompt_tokens")
                        completion_tokens_val = usage.get("completion_tokens")
            except Exception as e:
                logger.error("stream error: %s", e)
                yield _sse(json.dumps({"error": "Inference failed. Check server logs for details."}))
                had_error = True

            if had_error:
                yield _sse("[DONE]")
                return

        assistant_text = strip_thinking_text("".join(full).strip())
        if not assistant_text:
            yield _sse(json.dumps({
                "error": (
                    "The model returned no response — the connection may have dropped or "
                    "inference was interrupted. On CPU, wait 1–2 minutes before Retry, "
                    "or start a fresh chat if this keeps happening."
                ),
            }))
            yield _sse("[DONE]")
            return

        output_scan = scan_output(assistant_text)
        guard_flags_json = output_scan.to_json() if output_scan.flags else None

        assist_id = uuid.uuid4()
        p = await get_pool()
        async with p.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, model, safeguard_version, ai_generated, guard_flags, prompt_tokens, completion_tokens, tokens_used)
                VALUES ($1::uuid, $2::uuid, 'assistant', $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                assist_id,
                chat_id,
                encrypt_column(assistant_text, str(assist_id)),
                effective_model,
                current_version(),
                True,
                json.dumps(guard_flags_json) if guard_flags_json else None,
                prompt_tokens_val,
                completion_tokens_val,
                completion_tokens_val,
            )
            await conn.execute(
                """
                UPDATE chats
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                chat_id,
            )
            tier_row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
            from services.sysinfo import chat_ctx_for_tier

            ctx_max = chat_ctx_for_tier(tier_row["tier"] if tier_row else None)
            await conn.execute(
                "UPDATE chats SET ctx_max = $2 WHERE id = $1::uuid AND ctx_max IS NULL",
                chat_id,
                ctx_max,
            )
            if output_scan.flags:
                try:
                    flags_bytes = json.dumps(guard_flags_json).encode("utf-8")
                    await insert_audit_event(conn, AuditRecord(
                        request_id=request.state.request_id,
                        actor="system",
                        action="safeguard.flag.output",
                        target_type="message",
                        target_id=str(assist_id),
                        status_code=200,
                        payload_hash=hashlib.sha256(flags_bytes).digest(),
                    ))
                except Exception:
                    logger.warning("audit insert failed for output guard flags", exc_info=True)

        # Hook: post_tool_execution
        _hook_duration_ms = (time.monotonic() - _hook_start) * 1000
        await fire_post_tool_execution(
            "inference",
            {"model": effective_model},
            {"text": assistant_text, "guard_flags": guard_flags_json, "assistant_id": str(assist_id)},
            duration_ms=_hook_duration_ms,
        )

        # Auto-compaction: summarize older messages when context usage is high.
        # Best-effort — failures log and continue, never block the chat.
        try:
            from services.compaction import maybe_compact
            await maybe_compact(chat_id, prompt_tokens_val, ctx_max)
        except Exception as exc:
            logger.error("compaction call failed: %s", exc)

        title_emit: str | None = None
        has_custom_title = bool((chat["title"] or "").strip())
        if first_exchange_for_auto_title and assistant_text and not has_custom_title:
            new_title: str | None = None
            try:
                new_title = await _openai_short_chat_title(provider, effective_model, assistant_text)
            except Exception as exc:
                logger.warning("auto-title generation failed: %s", exc)
                new_title = None
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
            except Exception as exc:
                logger.warning("auto-title DB write failed chat_id=%s: %s", chat_id, exc)
        if title_emit:
            yield _sse(json.dumps({"type": "title_update", "title": title_emit}))

        auto_mem = _first_auto_memory_sentence(assistant_text)
        if auto_mem:
            async with p.acquire() as conn_mem:
                mem_row = await conn_mem.fetchrow(
                    """
                    INSERT INTO memory_entries (content, source)
                    VALUES ($1, 'auto')
                    RETURNING id
                    """,
                    auto_mem,
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

        # Groundedness eval -- async background task, never inline.
        # Fires after all pool.acquire() blocks in gen() are closed.
        # Durable streaming path is explicitly excluded (see design.md deferred scope).
        if chat.get("workspace_id"):
            await maybe_fire_groundedness_eval(
                message_id=assist_id,
                workspace_id=chat["workspace_id"],
                assistant_text=assistant_text,
                context_text=rag_block_text,
            )

        if not output_scan.passed:
            yield _sse(json.dumps({
                "type": "guard_alert",
                "flags": output_scan.to_json(),
                "message": "The assistant's response was flagged by the output guard.",
            }))
        if output_scan.flags and output_scan.passed:
            yield _sse(json.dumps({
                "type": "guard_info",
                "flags": output_scan.to_json(),
            }))

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


@router.post("/{chat_id}/stop")
async def stop_chat_inference(
    chat_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    cancelled = await job_registry.cancel(chat_id)
    if not cancelled:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages SET status = 'cancelled', finished_at = NOW()
                WHERE chat_id = $1::uuid AND role = 'assistant' AND status = 'streaming'
                """,
                chat_id,
            )
    async with audit.targeting("chat", chat_id):
        pass
    # Fire on_stop hook
    stop_ctx = HookContext(
        chat_id=str(chat_id),
        user_id=str(principal.get("user_id", "")),
    )
    await fire_on_stop("user_cancelled", ctx=stop_ctx)
    return {"ok": True}


@router.post("/{chat_id}/approval-response")
async def submit_approval_response(
    chat_id: uuid.UUID,
    body: ApprovalResponseBody,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    """Submit the user's decision for a pending approval gate request.

    Accept, reject, or edit the pending action.  On ``edit`` the caller must
    provide ``edited_content`` (the revised user message).  The inference
    pipeline (if waiting) will resume or stop accordingly.

    Returns 404 if no request is pending for this chat.
    """
    from services.approval_gate import ApprovalAction, get_gate

    action = ApprovalAction(body.action)
    gate = get_gate()

    submitted = gate.submit_response(
        str(chat_id),
        action,
        edited_content=body.edited_content,
    )
    if not submitted:
        raise HTTPException(status_code=404, detail="No pending approval for this chat")

    async with audit.targeting("chat", str(chat_id)):
        pass

    return {"ok": True, "action": body.action}


@router.post("/{chat_id}/messages/{message_id}/discard-stale")
async def discard_stale_message(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status, created_at, started_at
            FROM messages
            WHERE id = $1::uuid AND chat_id = $2::uuid AND role = 'assistant'
            """,
            message_id, chat_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Message not found")
        if row["status"] != "streaming":
            raise HTTPException(status_code=409, detail="Message is not streaming")
        from datetime import datetime, timezone
        anchor = row["started_at"] or row["created_at"]
        age_s = (datetime.now(timezone.utc) - anchor).total_seconds()
        if age_s < 60:
            raise HTTPException(
                status_code=409,
                detail=f"Message is only {int(age_s)}s old — must be at least 60s to discard.",
            )
        await job_registry.cancel(chat_id, timeout=3.0)
        await conn.execute(
            "UPDATE messages SET status = 'failed', finished_at = NOW(), error_message = 'discarded as stale' WHERE id = $1::uuid",
            message_id,
        )
    async with audit.targeting("chat", chat_id):
        pass
    return {"ok": True}


@router.post("/{chat_id}/deep_research")
async def post_deep_research(
    chat_id: uuid.UUID,
    body: DeepResearchBody,
    principal: dict[str, Any] = Depends(get_principal),
    audit: AuditEventHandle = Depends(audit_event),
):
    from services.deep_research import run_deep_research

    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    if len(q) > 2000:
        raise HTTPException(status_code=400, detail="query too long (max 2000 chars)")

    pool = await get_pool()
    async with pool.acquire() as conn:
        chat = await conn.fetchrow(
            "SELECT id, workspace_id FROM chats WHERE id = $1::uuid",
            chat_id,
        )
    if not chat:
        raise HTTPException(status_code=404, detail="chat not found")

    workspace_id = str(chat["workspace_id"])

    async with audit.targeting("chat", chat_id):
        pass

    async def gen():
        try:
            async for event in run_deep_research(q, workspace_id, str(chat_id)):
                yield _sse(json.dumps(event))
        except Exception as exc:
            logger.error("deep_research stream error chat_id=%s: %s", chat_id, exc)
            yield _sse(json.dumps({"type": "dr_error", "error": str(exc)}))
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
