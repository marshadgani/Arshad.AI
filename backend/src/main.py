import asyncio
import logging
import os
from contextlib import asynccontextmanager

import src.integrations  # noqa: F401 — package __init__ triggers @register side-effects
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from src.agents.routers import router as agents_router
from src.api.v1.ai_ecosystem import router as ai_ecosystem_router
from src.api.v1.chat import router as chat_router
from src.api.v1.dashboard import router as dashboard_router
from src.api.v1.domains import router as domains_router
from src.api.v1.obsidian import router as obsidian_router
from src.auth.routers import router as auth_router
from src.middleware.cache import close_redis
from src.models.database import AsyncSessionLocal
from src.services import queue_worker
from src.tools.routers import router as tools_router

# `import src.integrations` (line 6) triggers @register side-effects.
# `integrations_router` is consumed below in app.include_router().

_log = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "change-me":
    raise RuntimeError(
        "SECRET_KEY must be set to a non-default value. Generate one with: "
        "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]


async def _probe_db() -> None:
    """Verify the database is reachable. Raises on any connection failure."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if the database is unreachable so Render marks the service
    # unhealthy immediately rather than letting every request explode.
    # Common cause: Supabase free-tier project paused (supabase.com → resume),
    # or DATABASE_URL pointing at a pooler that rejects the connection.
    try:
        await _probe_db()
        _log.info("Database connectivity: OK")
    except Exception as exc:
        _log.critical(
            "Database unreachable at startup — service will not handle requests. "
            "If using Supabase, check the project is not paused at supabase.com. "
            "Error: %s",
            exc,
        )
        raise

    # Phase F: optional in-process queue worker. Gated on
    # ENABLE_INPROCESS_WORKER=true so docker-compose-Airflow setups don't
    # double-process; SELECT...FOR UPDATE SKIP LOCKED makes simultaneous
    # operation safe-but-wasteful even if both are accidentally enabled.
    worker_task: asyncio.Task | None = None
    stop_event: asyncio.Event | None = None
    if queue_worker.is_enabled():
        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(queue_worker.run_worker(stop_event))
        _log.info("ENABLE_INPROCESS_WORKER=true; queue worker started")

    try:
        yield
    finally:
        if worker_task is not None and stop_event is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(worker_task, timeout=10.0)
            except asyncio.TimeoutError:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
        await close_redis()


app = FastAPI(title="Arshad.AI Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Unwrap the FastAPI ``{"detail": ...}`` envelope when handlers
    already raise with the project's error shape ``{"error": {...}}``
    (per .claude/rules/api.md). Plain-string details fall back to the
    standard envelope so 401/403/422 from FastAPI's own machinery still
    work.
    """
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so a misconfigured backend (missing Redis, missing env var,
    DB unreachable, etc.) returns a readable JSON envelope instead of a
    blank 500 the user can't diagnose. Full traceback is logged server-side
    at ERROR level. The response includes a truncated str(exc) so connection
    failures (host:port) are visible without needing log access — acceptable
    for the single-user MVP; revisit if/when multi-tenant.
    """
    _log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": f"Backend hit an unhandled {type(exc).__name__}.",
                "details": {
                    "path": request.url.path,
                    "exception": str(exc)[:300],
                },
            }
        },
    )


@app.get("/health", summary="Readiness check")
async def health():
    """Readiness probe — verifies the database is reachable.

    Render routes traffic based on this endpoint. Returning 200 while the DB
    is down causes every subsequent request to 500; verifying here surfaces
    the outage immediately in Render's dashboard and stops routing.
    """
    try:
        await _probe_db()
    except Exception as exc:
        # Log full exception server-side (visible in Render logs) but never
        # expose DSN details — asyncpg exceptions embed connection strings.
        _log.warning("Health probe: database unreachable — %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "detail": (
                    "Database unreachable. "
                    "If using Supabase, check supabase.com — project may be paused."
                ),
            },
        )
    return {"status": "ok"}


from src.integrations.routers import router as integrations_router  # noqa: E402

app.include_router(auth_router)
app.include_router(tools_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(domains_router)
app.include_router(ai_ecosystem_router)
app.include_router(ai_ecosystem_skills_router)
app.include_router(obsidian_router)
app.include_router(integrations_router)
