"""OpenAI-compatible inference proxy (Bifrost): model list, streaming chat (SSE), settings."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth_deps import require_admin
from db import get_pool

router = APIRouter()


def _default_ollama_model() -> str:
    for key in ("OLLAMA_MODEL", "DEFAULT_MODEL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return "llama-gpu/qwen3.5-9b-exl3"


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _openai_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("BIFROST_API_KEY") or "").strip()
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


def _ollama_settings_keys(mode: str) -> tuple[str, str]:
    if mode == "808notes":
        return "default_model_808notes", "ollama_hidden_models_808notes"
    return "default_model", "ollama_hidden_models"


async def _ollama_settings_payload(conn: Any, mode: str = "booops") -> dict[str, Any]:
    dk, hk = _ollama_settings_keys(mode)
    default_row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", dk)
    hidden_row = await conn.fetchrow("SELECT value FROM global_settings WHERE key = $1", hk)
    raw = (default_row["value"] if default_row else None) or ""
    default_model = str(raw).strip() or _default_ollama_model()
    hidden_models = _parse_hidden_models(hidden_row["value"] if hidden_row else "[]")
    return {"default_model": default_model, "hidden_models": hidden_models}


class OllamaSettingsPatch(BaseModel):
    default_model: str | None = None
    hidden_models: list[str] | None = None


@router.get("/models")
async def list_models():
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{base}/v1/models", headers=_openai_headers())
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Inference backend unreachable: {e}") from e
    data = r.json()
    # Bifrost returns empty data[] for custom providers — fall back to env-configured model list
    if not data.get("data"):
        raw = os.environ.get("BIFROST_MODELS", "")
        models = [m.strip() for m in raw.split(",") if m.strip()]
        data = {"data": [{"id": m, "object": "model"} for m in models]}
    return data


@router.get("/settings")
async def get_ollama_settings(mode: str = Query("booops")):
    m = mode if mode in ("booops", "808notes") else "booops"
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _ollama_settings_payload(conn, m)


@router.patch("/settings")
async def patch_ollama_settings(
    body: OllamaSettingsPatch,
    mode: str = Query("booops"),
    _owner: dict = Depends(require_admin),
):
    m = mode if mode in ("booops", "808notes") else "booops"
    dk, hk = _ollama_settings_keys(m)
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.default_model is not None:
            await _upsert_setting(conn, dk, body.default_model)
        if body.hidden_models is not None:
            await _upsert_setting(conn, hk, json.dumps(body.hidden_models))
        return await _ollama_settings_payload(conn, m)


async def _stream_openai_chat_completions(body: dict[str, Any]) -> AsyncIterator[bytes]:
    base = _ollama_base()
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
