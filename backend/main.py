"""boolab API — Phase 0: health, CORS, DB pool, schema on startup."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import apply_schema, close_pool, get_pool, init_pool
from seed_assets import seed_default_assets
from seed_users import ensure_super_admin
from services.auto_sync import auto_sync_loop
from routers import (
    auth,
    branding,
    chats,
    custom_instructions,
    daw_context_files,
    daw_memory,
    daws,
    memory,
    ollama,
    personas,
    search,
    searxng,
    settings,
    skills,
)
from routers.boocode import router as boocode_router
from routers.dubdrive import router as dubdrive_router
from routers.dubdrive_sync import router as dubdrive_sync_router
from routers.notes import router as notes_router
from routers.sources import router as sources_router

import logging
logging.basicConfig(level=logging.INFO)

load_dotenv()


def _cors_origins() -> list[str]:
    raw = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "").split(",") if o.strip()]
    host = (os.environ.get("BOOLAB_PUBLIC_HOST") or "").strip()
    if host:
        for port in ("9302", "9303", "9304"):
            u = f"http://{host}:{port}"
            if u not in raw:
                raw.append(u)
    return raw


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    await apply_schema()
    await seed_default_assets()
    await ensure_super_admin()
    auto_sync_task = asyncio.create_task(auto_sync_loop(), name="boocode_auto_sync")
    try:
        yield
    finally:
        auto_sync_task.cancel()
        try:
            await auto_sync_task
        except (asyncio.CancelledError, Exception):
            pass
        await close_pool()


app = FastAPI(title="boolab API", lifespan=lifespan)

from starlette.middleware.base import BaseHTTPMiddleware

class _SizeLimit(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > 55 * 1024 * 1024:
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Request too large", status_code=413)
        return await call_next(request)

app.add_middleware(_SizeLimit)

_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


api = APIRouter(prefix="/api")


@api.get("/health")
async def api_health():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


api.include_router(auth.router, prefix="/auth", tags=["auth"])
api.include_router(ollama.router, prefix="/ollama", tags=["ollama"])
api.include_router(chats.router, prefix="/chats", tags=["chats"])
api.include_router(branding.router, prefix="/branding", tags=["branding"])
api.include_router(personas.router, prefix="/personas", tags=["personas"])
api.include_router(memory.router, prefix="/memory", tags=["memory"])
api.include_router(daws.router, prefix="/daws", tags=["daws"])
api.include_router(daw_memory.router)
api.include_router(daw_context_files.router, prefix="/daw-context-files", tags=["daw-context-files"])
api.include_router(custom_instructions.router, prefix="/custom-instructions", tags=["custom-instructions"])
api.include_router(settings.router, prefix="/settings", tags=["settings"])
api.include_router(search.router, prefix="/search", tags=["search"])
api.include_router(searxng.router, prefix="/searxng", tags=["searxng"])
api.include_router(notes_router, tags=["notes"])
api.include_router(sources_router, tags=["sources"])
api.include_router(dubdrive_router, prefix="/dubdrive", tags=["dubdrive"])
api.include_router(dubdrive_sync_router)
api.include_router(boocode_router)
api.include_router(skills.router, prefix="/skills", tags=["skills"])

app.include_router(api)
