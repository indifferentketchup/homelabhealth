"""Background inference job — runs detached from the HTTP connection.

The router creates an asyncio.Task calling run_inference_job(). The job:
1. Streams inference from the LLM provider
2. Flushes accumulated content to DB every 500ms (encrypted, chained writes)
3. On completion: runs output guard, auto-title, auto-memory, compaction, pruning
4. On cancel/error: marks the message row accordingly
5. In finally: marks the registration completed and removes from registry

Design: docs/superpowers/specs/2026-05-26-durable-streaming-inference-design.md
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from services.chat_jobs import InferenceRegistration, job_registry

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_S = 0.5


async def run_inference_job(
    registration: InferenceRegistration,
    chat_id: UUID,
    assistant_id: UUID,
    *,
    provider: object,
    effective_model: str,
    chat_record: dict,
    msg_rows: list,
    user_message_text: str,
    user_profile_block: str,
    provider_is_bundled: bool,
    first_exchange_for_auto_title: bool,
    request_id: str | None = None,
    principal_username: str = "unknown",
) -> None:
    """Run a complete inference cycle in a background task.

    This function is fire-and-forget from the router's perspective.
    All errors are caught, logged, and persisted to the message row.
    """
    from db import get_pool

    pool = await get_pool()

    try:
        # 1. Mark started_at on the assistant message row
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE messages SET started_at = NOW(), status = 'streaming' WHERE id = $1::uuid",
                assistant_id,
            )

        # 2. Assemble system prompt (RAG, search, etc.)
        #    Import inside function to avoid circular imports with routers/chats.py
        from routers.chats import (
            _assembled_system_prompt,
            _stream_inference,
            _openai_short_chat_title,
            _first_auto_memory_sentence,
        )
        from services.searx import searx_search_sources
        from services.crypto import encrypt_column, decrypt_column
        from services.guard import scan_output
        from services.safeguards import current_version
        from services.reasoning_strip import ThinkingStreamFilter
        from services.deid import is_enabled as deid_enabled, redact_text
        from services.provider_client import build_headers
        from services.sysinfo import chat_ctx_for_tier
        from services.audit import AuditRecord, insert_audit_event

        # Web search (if enabled)
        extra_search = ""
        if bool(chat_record.get("web_search_enabled")):
            try:
                _sources_list, extra_search = await searx_search_sources(
                    user_message_text,
                )
            except Exception as exc:
                logger.warning("inference_job: web search failed: %s", exc)
                extra_search = ""

        # Check for cancellation before expensive RAG assembly
        if registration.cancel_event.is_set():
            await _mark_cancelled(pool, assistant_id)
            return

        # Assemble system prompt via RAG pipeline
        assembled = ""
        rag_sse_meta = None
        try:
            async with pool.acquire() as rag_conn:
                # _assembled_system_prompt expects an asyncpg.Record-like object
                # but chat_record is a dict. Build a minimal record adapter.
                assembled, rag_sse_meta = await _assembled_system_prompt(
                    rag_conn,
                    chat_record,
                    user_query_for_rag=user_message_text,
                    include_site_private=True,
                )
        except Exception as exc:
            logger.error("inference_job: RAG assembly failed chat_id=%s: %s", chat_id, exc)
            await _mark_failed(pool, assistant_id, f"Document retrieval failed: {type(exc).__name__}")
            return

        # Check for cancellation after RAG
        if registration.cancel_event.is_set():
            await _mark_cancelled(pool, assistant_id)
            return

        # 3. Build message list for inference
        summary = chat_record.get("pruning_summary")
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
                "## Web search results (use if relevant; the user enabled web search for this turn):\n"
                + extra_search
            )
        if system_blocks:
            api_messages.append({"role": "system", "content": "\n\n".join(system_blocks)})

        for r in msg_rows:
            role = r.get("role") if isinstance(r, dict) else r["role"]
            status = r.get("status", "complete") if isinstance(r, dict) else r.get("status", "complete")
            # Skip rows that are still streaming (the assistant placeholder)
            if status == "streaming":
                continue
            if role not in ("user", "assistant", "system"):
                continue
            raw = r.get("content") or r["content"] if isinstance(r, dict) else r["content"]
            raw = raw or ""
            rid = str(r.get("id") or r["id"]) if isinstance(r, dict) else str(r["id"])
            api_messages.append({
                "role": role,
                "content": decrypt_column(raw, rid) if raw else raw,
            })

        # De-identify user messages for external providers
        if deid_enabled() and not provider_is_bundled:
            for msg in api_messages:
                if msg["role"] == "user":
                    r_result = redact_text(msg["content"])
                    if r_result.had_phi:
                        logger.info(
                            "deid: redacted %d findings in user message before external inference",
                            len(r_result.findings),
                        )
                    msg["content"] = r_result.text

        # 4. Stream inference with periodic DB flushes
        filt = ThinkingStreamFilter()
        accumulated = ""
        full_raw: list[str] = []
        had_error = False
        error_detail = ""
        prompt_tokens_val: int | None = None
        completion_tokens_val: int | None = None

        last_flush_task: asyncio.Task | None = None
        accumulated_at_last_flush = 0

        async def _do_flush(content_snapshot: str, prev_task: asyncio.Task | None) -> None:
            if prev_task is not None:
                try:
                    await prev_task
                except Exception:
                    pass
            try:
                encrypted = encrypt_column(content_snapshot, str(assistant_id))
                async with pool.acquire() as flush_conn:
                    await flush_conn.execute(
                        "UPDATE messages SET content = $2 WHERE id = $1::uuid",
                        assistant_id,
                        encrypted,
                    )
            except Exception as exc:
                logger.warning("inference_job: flush failed assistant_id=%s: %s", assistant_id, exc)

        logger.info(
            "inference_job: starting inference chat_id=%s model=%s",
            str(chat_id), effective_model,
        )

        stream = _stream_inference(provider, effective_model, api_messages)
        flush_timer_start = asyncio.get_event_loop().time()

        try:
            async for chunk in stream:
                if registration.cancel_event.is_set():
                    break

                try:
                    line = chunk.decode("utf-8")
                except Exception:
                    continue

                if not line.startswith("data: "):
                    continue

                payload = line[6:].strip()
                if payload == "[DONE]":
                    break

                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if obj.get("error"):
                    had_error = True
                    error_detail = str(obj["error"])
                    break

                content_piece = obj.get("content")
                if content_piece:
                    full_raw.append(content_piece)
                    for visible in filt.feed(content_piece):
                        accumulated += visible

                usage = obj.get("usage")
                if usage:
                    prompt_tokens_val = usage.get("prompt_tokens")
                    completion_tokens_val = usage.get("completion_tokens")

                now = asyncio.get_event_loop().time()
                if now - flush_timer_start >= _FLUSH_INTERVAL_S and len(accumulated) > accumulated_at_last_flush:
                    accumulated_at_last_flush = len(accumulated)
                    last_flush_task = asyncio.create_task(
                        _do_flush(accumulated, last_flush_task)
                    )
                    flush_timer_start = now

            for tail in filt.flush():
                accumulated += tail

        except Exception as exc:
            had_error = True
            error_detail = f"Inference stream error: {type(exc).__name__}: {exc}"
            logger.error("inference_job: stream error chat_id=%s: %s", chat_id, exc)

        # Final flush of accumulated content
        if len(accumulated) > accumulated_at_last_flush:
            last_flush_task = asyncio.create_task(
                _do_flush(accumulated, last_flush_task)
            )
        if last_flush_task is not None:
            try:
                await last_flush_task
            except Exception:
                pass

        # Handle cancellation
        if registration.cancel_event.is_set():
            partial = accumulated.strip()
            await _mark_cancelled(pool, assistant_id, content=partial if partial else None)
            return

        # Handle error
        if had_error:
            await _mark_failed(pool, assistant_id, error_detail)
            return

        # 5. Finalize successful completion
        from services.reasoning_strip import strip_thinking_text

        assistant_text = strip_thinking_text("".join(full_raw).strip())

        if not assistant_text:
            await _mark_failed(
                pool, assistant_id,
                "The model returned no response -- the connection may have dropped or "
                "inference was interrupted.",
            )
            return

        # Output guard scan
        output_scan = scan_output(assistant_text)
        guard_flags_json = output_scan.to_json() if output_scan.flags else None

        # Final DB write: encrypted content, status=complete, token counts, guard flags
        encrypted_final = encrypt_column(assistant_text, str(assistant_id))
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET content = $2,
                    status = 'complete',
                    finished_at = NOW(),
                    safeguard_version = $3,
                    ai_generated = TRUE,
                    guard_flags = $4,
                    prompt_tokens = $5,
                    completion_tokens = $6,
                    tokens_used = $6
                WHERE id = $1::uuid
                """,
                assistant_id,
                encrypted_final,
                current_version(),
                json.dumps(guard_flags_json) if guard_flags_json else None,
                prompt_tokens_val,
                completion_tokens_val,
            )
            await conn.execute(
                "UPDATE chats SET message_count = message_count + 1, updated_at = NOW() WHERE id = $1::uuid",
                chat_id,
            )

            # ctx_max
            tier_row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
            ctx_max = chat_ctx_for_tier(tier_row["tier"] if tier_row else None)
            await conn.execute(
                "UPDATE chats SET ctx_max = $2 WHERE id = $1::uuid AND ctx_max IS NULL",
                chat_id,
                ctx_max,
            )

            # Audit output guard flags
            if output_scan.flags:
                try:
                    flags_bytes = json.dumps(guard_flags_json).encode("utf-8")
                    await insert_audit_event(conn, AuditRecord(
                        request_id=uuid.UUID(request_id) if request_id else uuid.uuid4(),
                        actor="system",
                        action="safeguard.flag.output",
                        target_type="message",
                        target_id=str(assistant_id),
                        status_code=200,
                        payload_hash=hashlib.sha256(flags_bytes).digest(),
                    ))
                except Exception:
                    logger.warning("audit insert failed for output guard flags", exc_info=True)

        # 6. Post-completion: auto-title
        has_custom_title = bool((chat_record.get("title") or "").strip())
        if first_exchange_for_auto_title and assistant_text and not has_custom_title:
            new_title: str | None = None
            try:
                new_title = await _openai_short_chat_title(provider, effective_model, assistant_text)
            except Exception:
                new_title = None
            if not new_title:
                new_title = "New chat"
            try:
                async with pool.acquire() as conn_title:
                    await conn_title.execute(
                        "UPDATE chats SET title = $2, updated_at = NOW() WHERE id = $1::uuid",
                        chat_id,
                        new_title,
                    )
            except Exception:
                logger.warning("inference_job: auto-title update failed", exc_info=True)

        # 7. Auto-memory
        auto_mem = _first_auto_memory_sentence(assistant_text)
        if auto_mem:
            try:
                async with pool.acquire() as conn_mem:
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
            except Exception:
                logger.warning("inference_job: auto-memory insert failed", exc_info=True)

        # 8. Compaction
        try:
            from services.compaction import maybe_compact
            await maybe_compact(chat_id, prompt_tokens_val, ctx_max)
        except Exception as exc:
            logger.error("inference_job: compaction failed: %s", exc)

        # 9. Pruning
        try:
            from services.pruning import summarize_and_compress
            await summarize_and_compress(str(chat_id), pool)
        except Exception as exc:
            logger.error("inference_job: pruning failed: %s", exc)

        logger.info(
            "inference_job: complete chat_id=%s assistant_id=%s tokens=%s",
            str(chat_id), str(assistant_id), completion_tokens_val,
        )

    except asyncio.CancelledError:
        logger.info("inference_job: task cancelled chat_id=%s", str(chat_id))
        try:
            await _mark_cancelled(pool, assistant_id)
        except Exception:
            pass
        raise

    except Exception as exc:
        logger.error(
            "inference_job: unhandled error chat_id=%s: %s: %s",
            str(chat_id), type(exc).__name__, exc,
        )
        try:
            await _mark_failed(pool, assistant_id, f"{type(exc).__name__}: {exc}")
        except Exception:
            logger.error("inference_job: failed to mark error status", exc_info=True)

    finally:
        job_registry.mark_completed(chat_id, registration)
        job_registry.remove_if_current(chat_id, registration)


async def _mark_cancelled(
    pool, assistant_id: UUID, *, content: str | None = None
) -> None:
    """Mark the assistant message as cancelled."""
    from services.crypto import encrypt_column

    async with pool.acquire() as conn:
        if content:
            encrypted = encrypt_column(content, str(assistant_id))
            await conn.execute(
                """
                UPDATE messages
                SET status = 'cancelled', finished_at = NOW(), content = $2
                WHERE id = $1::uuid
                """,
                assistant_id,
                encrypted,
            )
        else:
            await conn.execute(
                "UPDATE messages SET status = 'cancelled', finished_at = NOW() WHERE id = $1::uuid",
                assistant_id,
            )


async def _mark_failed(pool, assistant_id: UUID, error_detail: str) -> None:
    """Mark the assistant message as failed with a redacted error message."""
    from services.log_redactor import PHIRedactorFilter

    # Redact PHI from the error message before storing
    redactor = PHIRedactorFilter()
    safe_error = redactor._scrub(error_detail)
    # Truncate to reasonable length
    safe_error = safe_error[:500]

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE messages
            SET status = 'failed', finished_at = NOW(), error_message = $2
            WHERE id = $1::uuid
            """,
            assistant_id,
            safe_error,
        )
