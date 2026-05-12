"""OpenAI-compatible inference proxy: model list, streaming chat (SSE), settings."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deps import require_admin
from db import get_pool

router = APIRouter()


def _default_model() -> str:
    v = (os.environ.get("DEFAULT_MODEL") or "").strip()
    if not v:
        raise RuntimeError("DEFAULT_MODEL env var is required")
    return v


def _inference_base() -> str:
    return os.environ.get("INFERENCE_URL", "http://localhost:8080").rstrip("/")


def _openai_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


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
    default_model = str(raw).strip() or _default_model()
    hidden_models = _parse_hidden_models(hidden_row["value"] if hidden_row else "[]")
    return {"default_model": default_model, "hidden_models": hidden_models}


class ModelSettingsPatch(BaseModel):
    default_model: str | None = None
    hidden_models: list[str] | None = None


@router.get("/models")
async def list_models():
    base = _inference_base()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{base}/v1/models", headers=_openai_headers())
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Inference backend unreachable: {e}") from e
    return r.json()


@router.get("/settings")
async def get_model_settings():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _model_settings_payload(conn)


@router.patch("/settings")
async def patch_model_settings(
    body: ModelSettingsPatch,
    _owner: dict = Depends(require_admin),
):
    dk, hk = _model_settings_keys()
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.default_model is not None:
            await _upsert_setting(conn, dk, body.default_model)
        if body.hidden_models is not None:
            await _upsert_setting(conn, hk, json.dumps(body.hidden_models))
        return await _model_settings_payload(conn)


async def _stream_openai_chat_completions(body: dict[str, Any]) -> AsyncIterator[bytes]:
    base = _inference_base()
    model = body.get("model")
    messages = body.get("messages")
    if not model or not isinstance(messages, list):
        yield _sse(json.dumps({"error": "model and messages are required"}))
        yield _sse("[DONE]")
        return
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
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
                                yield _sse(json.dumps({"content": piece}))
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Inference request failed: {e}"}))
        return
    yield _sse("[DONE]")


@router.post("/chat")
async def chat_proxy(request: Request, _owner: dict = Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    if not body.get("model"):
        raise HTTPException(status_code=400, detail="model is required")
    if not body.get("messages"):
        raise HTTPException(status_code=400, detail="messages is required")

    return StreamingResponse(
        _stream_openai_chat_completions(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
