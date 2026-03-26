"""boolab API — Phase 0: health, CORS, DB pool, schema on startup."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import apply_schema, close_pool, get_pool, init_chroma, init_pool
from routers import (
    branding,
    chats,
    claude,
    custom_instructions,
    daw_context_files,
    daws,
    memory,
    ollama,
    personas,
    search,
    searxng,
    settings,
)
from routers.sources import router as sources_router

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    await apply_schema()
    init_chroma()
    yield
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

_origins = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "").split(",") if o.strip()]
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


api.include_router(ollama.router, prefix="/ollama", tags=["ollama"])
api.include_router(claude.router, prefix="/claude", tags=["claude"])
api.include_router(chats.router, prefix="/chats", tags=["chats"])
api.include_router(branding.router, prefix="/branding", tags=["branding"])
api.include_router(personas.router, prefix="/personas", tags=["personas"])
api.include_router(memory.router, prefix="/memory", tags=["memory"])
api.include_router(daws.router, prefix="/daws", tags=["daws"])
api.include_router(daw_context_files.router, prefix="/daw-context-files", tags=["daw-context-files"])
api.include_router(custom_instructions.router, prefix="/custom-instructions", tags=["custom-instructions"])
api.include_router(settings.router, prefix="/settings", tags=["settings"])
api.include_router(search.router, prefix="/search", tags=["search"])
api.include_router(searxng.router, prefix="/searxng", tags=["searxng"])
api.include_router(sources_router, tags=["sources"])

app.include_router(api)
