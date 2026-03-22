"""Ollama proxy: model list + streaming chat (SSE)."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


@router.get("/models")
async def list_models():
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}") from e
    return r.json()


async def _stream_ollama_chat(body: dict[str, Any]) -> AsyncIterator[bytes]:
    base = _ollama_base()
    payload = {**body, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    err = text.decode("utf-8", errors="replace")[:2000]
                    yield _sse(json.dumps({"error": f"Ollama error {resp.status_code}: {err}"}))
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        yield _sse(json.dumps({"error": str(chunk["error"])}))
                        return
                    msg = chunk.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        yield _sse(json.dumps({"content": piece}))
                    if chunk.get("done"):
                        break
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": f"Ollama request failed: {e}"}))
        return
    yield _sse("[DONE]")


@router.post("/chat")
async def chat_proxy(request: Request):
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
        _stream_ollama_chat(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
