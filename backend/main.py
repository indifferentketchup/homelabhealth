"""homelabhealth API: health, CORS, DB pool, schema on startup."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import apply_schema, close_pool, get_pool, init_pool
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
    profile,
    providers,
    search,
    searxng,
    settings,
    system,
)
from services import bundled_providers, model_puller
from services.key_manager import ensure_keys
from services.log_redactor import install_redactor
from routers.history import router as history_router
from routers.notes import router as notes_router
from routers.sources import router as sources_router
from routers.audit import router as audit_router
from routers.auth import router as auth_router
from routers.demo import router as demo_router

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from services.startup_report import install_access_log_filter, log_startup_banner
install_access_log_filter()  # drop 2s-poll access-log spam; quiet httpx INFO

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


async def _streaming_sweeper() -> None:
    """Mark streaming messages older than 5 minutes as failed (orphan cleanup)."""
    from db import get_pool
    from services.chat_jobs import job_registry
    while True:
        await asyncio.sleep(60)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                swept = await conn.fetch(
                    """
                    UPDATE messages
                    SET status = 'failed', finished_at = NOW(), error_message = 'inference timed out'
                    WHERE status = 'streaming'
                      AND COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes'
                    RETURNING chat_id
                    """,
                )
            if swept:
                logger.info("sweeper: marked %d stale streaming rows as failed", len(swept))
                for row in swept:
                    await job_registry.cancel(row["chat_id"], timeout=2.0)
        except Exception as exc:
            logger.warning("sweeper error: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        ensure_keys()       # first: ensure encryption keys are in os.environ
        from services.key_manager import ensure_orchestra_token
        ensure_orchestra_token()
        install_redactor()
        _warn_deprecated_env_vars()
        await init_pool()
        await apply_schema()
        await ensure_super_admin()
        # Phase 1: seed bundled_models from MODEL_REGISTRY. Idempotent — safe on every boot.
        pool = await get_pool()
        # v1.1.4→v1.1.5 chat-path flattening: best-effort, harmless if no legacy files.
        bundled_providers.migrate_legacy_chat_paths()
        async with pool.acquire() as conn:
            seeded = await model_puller.seed_registry(conn)
            orphaned = await model_puller.reset_orphaned_pulls(conn)
            profile_row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
            if profile_row is not None:
                await bundled_providers.apply_bundled_bindings(conn, profile_row["tier"] or "external")
            await log_startup_banner(conn, seeded=seeded, orphaned=orphaned)
    except Exception as exc:
        # Loud, unmissable failure summary so the root cause isn't buried in
        # the restart-loop noise that follows (uvicorn re-execs on exit).
        logger.critical("=" * 64)
        logger.critical("STARTUP FAILED — the API cannot start.")
        logger.critical("  cause: %s: %s", type(exc).__name__, exc)
        logger.critical("  full traceback below; fix this, then the container will recover.")
        logger.critical("=" * 64)
        logger.exception("startup traceback")
        raise
    sweeper_task = asyncio.create_task(_streaming_sweeper())
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
        await close_pool()


app = FastAPI(title="homelabhealth API", lifespan=lifespan)

from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


@app.exception_handler(Exception)
async def _global_exception_handler(request: StarletteRequest, exc: Exception):
    """Return sanitized error to client; log scrubbed trace server-side."""
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    logger.exception(
        "unhandled exception on %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "request_id": str(request_id) if request_id else None,
        },
    )


import uuid as _uuid
from starlette.middleware.base import BaseHTTPMiddleware

class _SizeLimit(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > 55 * 1024 * 1024:
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Request too large", status_code=413)
        return await call_next(request)

app.add_middleware(_SizeLimit)


class _NoCacheAPIMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(_NoCacheAPIMiddleware)


_AUTH_WHITELIST = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/needs-setup",
    "/api/auth/setup",
    "/api/health",
    "/health",
}


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        # Allow whitelisted paths
        if path in _AUTH_WHITELIST:
            return await call_next(request)
        # Allow non-API paths (frontend static assets)
        if not path.startswith("/api/"):
            return await call_next(request)
        # Check session cookie
        from services.auth import validate_session
        token = request.cookies.get("hlh_session")
        if not token:
            # Check if setup is needed — if so, allow through (the frontend
            # will redirect to setup)
            from services.auth import needs_setup as _needs_setup
            pool = await get_pool()
            async with pool.acquire() as conn:
                if await _needs_setup(conn):
                    return await call_next(request)
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "not_authenticated"})
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await validate_session(conn, token)
        if user is None:
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "session_expired"})
        return await call_next(request)


app.add_middleware(_AuthMiddleware)


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.request_id = _uuid.uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        request.state.response_status_code = response.status_code
        return response

app.add_middleware(_RequestIDMiddleware)

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


api.include_router(auth_router, prefix="/auth", tags=["auth"])
api.include_router(profile.router, prefix="/profile", tags=["profile"])
api.include_router(providers.router, prefix="/providers", tags=["providers"])
api.include_router(system.router, prefix="/system", tags=["system"])
api.include_router(models.router, prefix="/models", tags=["models"])
api.include_router(inference.router, prefix="/inference", tags=["inference"])
api.include_router(chats.router, prefix="/chats", tags=["chats"])
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
api.include_router(audit_router, prefix="/audit", tags=["audit"])
api.include_router(demo_router, prefix="/demo", tags=["demo"])


app.include_router(api)
