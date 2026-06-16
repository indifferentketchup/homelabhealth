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
from routers.analytics import router as analytics_router
from routers.eval import router as eval_router
from routers.chats_crud import router as chats_crud_router

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
    """Retry or fail streaming messages older than 5 minutes (orphan cleanup).

    Liveness-aware logic (lift-durable-orchestration E1, 2026-06-13):
    - Job still active in the registry (slow but alive) with retry budget left
      -> increment retry_count, leave streaming so the client can keep resuming.
    - Job active but retry budget exhausted -> fail and cancel.
    - No active job (orphaned: the job died, the client is gone) -> fail at the
      5-minute mark regardless of retry budget, matching pre-E1 behavior. The
      empty-registry case after a process restart is handled by the lifespan
      startup sweep, not here.
    """
    from db import get_pool
    from services.chat_jobs import job_registry
    while True:
        await asyncio.sleep(60)
        try:
            pool = await get_pool()
            to_increment: list = []          # alive + budget remaining
            to_fail: list[tuple] = []        # no active job (orphaned)
            to_exhaust: list[tuple] = []     # alive but budget exhausted
            async with pool.acquire() as conn:
                candidates = await conn.fetch(
                    """
                    SELECT id, chat_id, retry_count, max_retries
                    FROM messages
                    WHERE status = 'streaming'
                      AND COALESCE(started_at, created_at) < NOW() - INTERVAL '5 minutes'
                    """,
                )
                for row in candidates:
                    if job_registry.has_active(row["chat_id"]):
                        if row["retry_count"] < row["max_retries"]:
                            to_increment.append(row["id"])
                        else:
                            to_exhaust.append((row["id"], row["chat_id"]))
                    else:
                        to_fail.append((row["id"], row["chat_id"]))

                if to_increment:
                    await conn.execute(
                        "UPDATE messages SET retry_count = retry_count + 1 "
                        "WHERE id = ANY($1::uuid[]) AND status = 'streaming'",
                        to_increment,
                    )
                if to_fail:
                    await conn.execute(
                        "UPDATE messages SET status = 'failed', finished_at = NOW(), "
                        "error_message = 'inference orphaned (no active job)' "
                        "WHERE id = ANY($1::uuid[]) AND status = 'streaming'",
                        [r[0] for r in to_fail],
                    )
                if to_exhaust:
                    await conn.execute(
                        "UPDATE messages SET status = 'failed', finished_at = NOW(), "
                        "error_message = 'inference timed out (retry budget exhausted)' "
                        "WHERE id = ANY($1::uuid[]) AND status = 'streaming'",
                        [r[0] for r in to_exhaust],
                    )
            # Cancel any lingering job for failed rows (no-op when not in registry).
            for _id, chat_id in to_fail + to_exhaust:
                await job_registry.cancel(chat_id, timeout=2.0)
            if to_increment:
                logger.info("sweeper: incremented retry_count on %d stale streaming rows (alive, budget remaining)", len(to_increment))
            if to_fail:
                logger.info("sweeper: failed %d orphaned streaming rows (no active job)", len(to_fail))
            if to_exhaust:
                logger.info("sweeper: failed %d streaming rows (retry budget exhausted)", len(to_exhaust))
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
        pool = await get_pool()
        # Sweep stale streaming rows left behind by a prior process crash/OOM.
        # 10-minute threshold is conservative vs the running sweeper's 5 minutes.
        # Two-branch logic (lift-durable-orchestration E1, 2026-06-13):
        # Branch 1: retry_count >= max_retries -> fail. Branch 2: increment retry_count.
        async with pool.acquire() as sweep_conn:
            # Branch 1: budget exhausted -> fail permanently
            swept = await sweep_conn.fetch(
                """
                UPDATE messages
                SET status = 'failed',
                    finished_at = NOW(),
                    error_message = 'process restart: inference interrupted (retry budget exhausted)'
                WHERE status = 'streaming'
                  AND COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'
                  AND retry_count >= max_retries
                RETURNING chat_id
                """,
            )
            # Branch 2: budget remaining -> increment retry_count, leave as streaming
            retried = await sweep_conn.fetch(
                """
                UPDATE messages
                SET retry_count = retry_count + 1
                WHERE status = 'streaming'
                  AND COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'
                  AND retry_count < max_retries
                RETURNING chat_id
                """,
            )
            if swept:
                logger.info(
                    "lifespan: failed %d stale streaming rows from prior process run (retry budget exhausted)",
                    len(swept),
                )
            if retried:
                logger.info(
                    "lifespan: incremented retry_count on %d stale streaming rows from prior process run (budget remaining)",
                    len(retried),
                )
            stale_sources = await sweep_conn.fetch(
                """
                UPDATE sources
                SET embedding_status = 'error',
                    error_message = 'ingest interrupted: source left in processing across restart',
                    updated_at = NOW()
                WHERE embedding_status = 'processing'
                  AND updated_at < NOW() - INTERVAL '5 minutes'
                RETURNING id
                """,
            )
            if stale_sources:
                logger.info(
                    "lifespan: swept %d stale 'processing' sources to 'error'",
                    len(stale_sources),
                )
        # v1.1.4→v1.1.5 chat-path flattening: best-effort, harmless if no legacy files.
        bundled_providers.migrate_legacy_chat_paths()
        async with pool.acquire() as conn:
            seeded = await model_puller.seed_registry(conn)
            orphaned = await model_puller.reset_orphaned_pulls(conn)
            profile_row = await conn.fetchrow("SELECT tier FROM system_profile WHERE id = 1")
            if profile_row is not None:
                await bundled_providers.apply_bundled_bindings(conn, profile_row["tier"] or "external")
            await log_startup_banner(conn, seeded=seeded, orphaned=orphaned)
        # One-shot embed-cutover reingest: after bindings (front-door base_url)
        # and seed_registry, fire reingest-all once when the boofinity embed
        # backend is ready (idempotent; guarded by a global_settings sentinel).
        from services.embed_cutover import run_embed_cutover
        await run_embed_cutover(pool)
        from services.memory_hooks import register_memory_hooks
        register_memory_hooks()
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
    allow_origins=_origins or ["http://localhost:9604"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
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
api.include_router(chats_crud_router, prefix="/chats", tags=["chats"])
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
api.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
api.include_router(demo_router, prefix="/demo", tags=["demo"])
api.include_router(eval_router, prefix="/eval", tags=["eval"])


app.include_router(api)
