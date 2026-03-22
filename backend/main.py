"""boolab API — Phase 0: health, CORS, DB pool, schema on startup."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import apply_schema, close_pool, get_pool, init_pool
from routers import chats, claude, ollama

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    await apply_schema()
    yield
    await close_pool()


app = FastAPI(title="boolab API", lifespan=lifespan)

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

app.include_router(api)
