"""homelabhealth API: health, CORS, DB pool, schema on startup."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import apply_schema, close_pool, get_pool, init_pool
from seed_assets import seed_default_assets
from seed_users import ensure_super_admin
from routers import (
    chats,
    custom_instructions,
    workspace_context_files,
    workspace_memory,
    workspaces,
    memory,
    inference,
    models,
    personas,
    profile,
    providers,
    search,
    searxng,
    settings,
    system,
)
from services import bundled_providers, model_puller
from routers.history import router as history_router
from routers.notes import router as notes_router
from routers.sources import router as sources_router

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


_DEPRECATED_ENV_VARS = (
    "OPENAI_API_KEY",
    "INFERENCE_URL",
    "EMBEDDING_URL",
    "RERANKER_URL",
    "DEFAULT_MODEL",
)


def _warn_deprecated_env_vars() -> None:
    """One-shot startup warning when any of the deprecated env vars are still
    set after the 2026-05-21 providers cutover. Provider config now lives in
    the DB; these env vars are ignored. Spec §7."""
    set_vars = [v for v in _DEPRECATED_ENV_VARS if (os.environ.get(v) or "").strip()]
    if set_vars:
        logger.warning(
            "Deprecated env vars set and ignored: %s. "
            "Provider config now lives in Settings → Providers. "
            "Remove these from your .env to silence this warning.",
            ", ".join(set_vars),
        )


def _cors_origins() -> list[str]:
    raw = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "").split(",") if o.strip()]
    host = (os.environ.get("HLH_PUBLIC_HOST") or "").strip()
    if host:
        port = os.environ.get("HLH_PORT_UI", "9604")
        u = f"http://{host}:{port}"
        if u not in raw:
            raw.append(u)
    return raw


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warn_deprecated_env_vars()
    await init_pool()
    await apply_schema()
    await seed_default_assets()
    await ensure_super_admin()
    # Phase 1: seed bundled_models from MODEL_REGISTRY. Idempotent — safe on every boot.
    pool = await get_pool()
    async with pool.acquire() as conn:
        seeded = await model_puller.seed_registry(conn)
        # If setup_complete=true AND tier != external, ensure the bundled-chat
        # provider row exists. No-op otherwise (silent).
        await bundled_providers.ensure_bundled_chat_provider(conn)
    logger.info("model_puller: seeded %d bundled_models rows", seeded)
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(title="homelabhealth API", lifespan=lifespan)

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


api.include_router(profile.router, prefix="/profile", tags=["profile"])
api.include_router(providers.router, prefix="/providers", tags=["providers"])
api.include_router(system.router, prefix="/system", tags=["system"])
api.include_router(models.router, prefix="/models", tags=["models"])
api.include_router(inference.router, prefix="/inference", tags=["inference"])
api.include_router(chats.router, prefix="/chats", tags=["chats"])
api.include_router(personas.router, prefix="/personas", tags=["personas"])
api.include_router(memory.router, prefix="/memory", tags=["memory"])
api.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api.include_router(workspace_memory.router)
api.include_router(workspace_context_files.router, prefix="/workspace-context-files", tags=["workspace-context-files"])
api.include_router(custom_instructions.router, prefix="/custom-instructions", tags=["custom-instructions"])
api.include_router(settings.router, prefix="/settings", tags=["settings"])
api.include_router(search.router, prefix="/search", tags=["search"])
api.include_router(searxng.router, prefix="/searxng", tags=["searxng"])
api.include_router(notes_router, tags=["notes"])
api.include_router(sources_router, tags=["sources"])
api.include_router(history_router, prefix="/history", tags=["history"])


app.include_router(api)
