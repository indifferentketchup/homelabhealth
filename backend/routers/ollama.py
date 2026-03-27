"""Ollama proxy: model list + streaming chat (SSE) + settings / pull / delete."""

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
    return "qwen3.5:9b"


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


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


class PullBody(BaseModel):
    model: str


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


async def _stream_ollama_pull(model: str) -> AsyncIterator[bytes]:
    base = _ollama_base()
    payload = {"model": model, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            async with client.stream("POST", f"{base}/api/pull", json=payload) as resp:
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
                    yield _sse(json.dumps(chunk))
                    if chunk.get("status") == "success":
                        yield _sse("[DONE]")
                        return
    except httpx.HTTPError as e:
        yield _sse(json.dumps({"error": str(e)}))


@router.post("/pull")
async def pull_model(body: PullBody, _owner: dict = Depends(require_admin)):
    if not body.model or not body.model.strip():
        raise HTTPException(status_code=400, detail="model is required")
    return StreamingResponse(
        _stream_ollama_pull(body.model.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/models/{model_name:path}")
async def delete_ollama_model(model_name: str, _owner: dict = Depends(require_admin)):
    if not model_name.strip():
        raise HTTPException(status_code=400, detail="model name is required")
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            r = await client.request(
                "DELETE",
                f"{base}/api/delete",
                json={"name": model_name},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}") from e
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Model not found")
    if r.status_code >= 400:
        detail = r.text[:2000] if r.text else r.status_text
        raise HTTPException(status_code=502, detail=f"Ollama error: {detail}")
    return {"ok": True}


@router.post("/unload-all")
async def unload_all_models(_owner: dict = Depends(require_admin)):
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{base}/api/ps")
            r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Ollama unreachable") from None
    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Ollama unreachable") from None

    models = data.get("models")
    if not isinstance(models, list) or len(models) == 0:
        return {"unloaded": []}

    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        raw = item.get("name") or item.get("model")
        if isinstance(raw, str) and raw.strip():
            names.append(raw.strip())

    if not names:
        return {"unloaded": []}

    unloaded: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for name in names:
            try:
                await client.post(
                    f"{base}/api/generate",
                    json={"model": name, "keep_alive": 0, "stream": False},
                )
            except httpx.HTTPError:
                pass
            unloaded.append(name)

    return {"unloaded": unloaded}


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
        _stream_ollama_chat(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
