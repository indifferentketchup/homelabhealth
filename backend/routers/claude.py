"""Claude API proxy — streaming SSE (unified token format with Ollama proxy)."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

CLAUDE_ALIASES: dict[str, str] = {
    "claude-sonnet": "claude-sonnet-4-20250514",
    "claude-haiku": "claude-3-5-haiku-20241022",
    "claude-opus": "claude-3-opus-20240229",
}


def _resolve_model(model: str) -> str:
    key = (model or "").strip().lower()
    if key in CLAUDE_ALIASES:
        env_key = {
            "claude-sonnet": "ANTHROPIC_MODEL_SONNET",
            "claude-haiku": "ANTHROPIC_MODEL_HAIKU",
            "claude-opus": "ANTHROPIC_MODEL_OPUS",
        }[key]
        return os.environ.get(env_key) or CLAUDE_ALIASES[key]
    return model.strip()


def _sse(data: str) -> bytes:
    return f"data: {data}\n\n".encode("utf-8")


def _split_system_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            else:
                system_parts.append(json.dumps(content))
        else:
            rest.append(m)
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest


@router.post("/chat")
async def claude_chat(request: Request):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    model_in = body.get("model")
    if not model_in:
        raise HTTPException(status_code=400, detail="model is required")
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages is required")

    model = _resolve_model(str(model_in))
    max_tokens = int(body.get("max_tokens", 4096))
    system, api_messages = _split_system_messages(messages)

    async def gen() -> AsyncIterator[bytes]:
        client = AsyncAnthropic(api_key=api_key)
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": api_messages,
            }
            if system:
                kwargs["system"] = system
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield _sse(json.dumps({"content": text}))
        except Exception as e:
            yield _sse(json.dumps({"error": str(e)}))
            return
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
