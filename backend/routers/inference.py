"""OpenAI-compatible inference proxy: model list, streaming chat (SSE), settings.

Post-providers: every chat goes through the workspace's configured provider.
`/api/inference/models` proxies a chosen provider's `/v1/models`; `/api/inference/chat`
requires a workspace_id and resolves the provider/headers via the resolver.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deps import require_admin
from db import get_pool
from services.audit import AuditEventHandle, audit_event
from services.provider_client import (
    Provider,
    build_headers,
    resolve_provider,
    resolve_provider_for_workspace,
)
from services.reasoning_strip import ThinkingStreamFilter

router = APIRouter()

import time as _time
_state_cache: dict[str, Any] = {"data": None, "ts": 0.0}


@router.get("/state")
async def inference_state(_: dict[str, Any] = Depends(require_admin)):
    now = _time.monotonic()
    if _state_cache["data"] and (now - _state_cache["ts"]) < 1.0:
        return _state_cache["data"]
    from services.model_inventory import get_inventory
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
    tier = row["tier"] if row else "cpu-std"
    data = await get_inventory(tier)
    _state_cache["data"] = data
    _state_cache["ts"] = now
    return data


import logging as _logging
_inference_logger = _logging.getLogger(__name__)


@router.post("/vision/stop")
async def force_stop_vision(_: dict[str, Any] = Depends(require_admin)):
    try:
        from services.vision_lifecycle import stop_vision
        await stop_vision()
        _state_cache["data"] = None
        return {"status": "stopped"}
    except Exception as e:
        _inference_logger.exception("force stop vision failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


async def _upsert_setting(conn: Any, key: str, value: str) -> None:
    await conn.execute(
        """
        INSERT INTO global_settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key,
        value,
    )


def _parse_hidden_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, str)]


def _model_settings_keys() -> tuple[str, str]:
    return "default_model", "ollama_hidden_models"


async def _model_settings_payload(conn: Any) -> dict[str, Any]:
    dk, hk = _model_settings_keys()
    default_row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", dk)
    hidden_row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", hk)
    raw = (default_row["value"] if default_row else None) or ""
    default_model = str(raw).strip()  # empty string = no global default; UI shows "unset"
    hidden_models = _parse_hidden_models(hidden_row["value"] if hidden_row else "[]")
    return {"default_model": default_model, "hidden_models": hidden_models}


class ModelSettingsPatch(BaseModel):
    default_model: str | None = None
    hidden_models: list[str] | None = None


@router.get("/models")
async def list_models(
    provider_id: uuid.UUID = Query(..., description="Provider whose /v1/models to proxy"),
    _: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    provider = await resolve_provider(provider_id)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(
                f"{provider.base_url}/v1/models",
                headers=build_headers(provider),
            )
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Inference backend unreachable: {e}") from e
    async with audit.targeting("inference", None):
        pass
    return r.json()


@router.get("/settings")
async def get_model_settings(audit: AuditEventHandle = Depends(audit_event)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await _model_settings_payload(conn)
    async with audit.targeting("inference", None):
        pass
    return result


@router.patch("/settings")
async def patch_model_settings(
    body: ModelSettingsPatch,
    _owner: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    dk, hk = _model_settings_keys()
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.default_model is not None:
            await _upsert_setting(conn, dk, body.default_model)
        if body.hidden_models is not None:
            await _upsert_setting(conn, hk, json.dumps(body.hidden_models))
        result = await _model_settings_payload(conn)
    async with audit.targeting("inference", None):
        pass
    return result


async def _stream_openai_chat_completions(
    provider: Provider,
    body: dict[str, Any],
) -> AsyncIterator[bytes]:
    model = body.get("model")
    messages = body.get("messages")
    if not model or not isinstance(messages, list):
        yield _sse(json.dumps({"error": "model and messages are required"}))
        yield _sse("[DONE]")
        return
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    filt = ThinkingStreamFilter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{provider.base_url}/v1/chat/completions",
                json=payload,
                headers=build_headers(provider),
            ) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(
                        json.dumps({"error": f"Inference error {resp.status_code}: {err}"}),
                    )
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
                                for out in filt.feed(piece):
                                    yield _sse(json.dumps({"content": out}))
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    for out in filt.flush():
        yield _sse(json.dumps({"content": out}))
    yield _sse("[DONE]")


@router.post("/chat")
async def chat_proxy(
    request: Request,
    workspace_id: uuid.UUID = Query(
        ..., description="Workspace whose provider routes this chat"
    ),
    _owner: dict = Depends(require_admin),
    audit: AuditEventHandle = Depends(audit_event),
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    if not body.get("messages"):
        raise HTTPException(status_code=400, detail="messages is required")

    # Resolve provider via the workspace; spec error string propagates from the resolver.
    provider, ws_model = await resolve_provider_for_workspace(workspace_id)
    # Caller may override the model (e.g. UI picks a different model from the
    # same provider). If absent, fall back to the workspace pin.
    if not body.get("model"):
        body["model"] = ws_model

    audit._target_type = "inference"
    audit._target_id = str(workspace_id)

    return StreamingResponse(
        _stream_openai_chat_completions(provider, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
