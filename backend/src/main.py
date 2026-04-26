import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.agents.routers import router as agents_router
from src.api.v1.chat import router as chat_router
from src.api.v1.dashboard import router as dashboard_router
from src.api.v1.domains import router as domains_router
from src.auth.routers import router as auth_router
from src.middleware.cache import close_redis
from src.services import queue_worker
from src.tools.routers import router as tools_router

_log = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "change-me":
    raise RuntimeError(
        "SECRET_KEY must be set to a non-default value. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    blank 500 the user can't diagnose. Exception details are logged
    server-side at ERROR level — never leaked to the response.
    """
    _log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": (
                    f"Backend hit an unhandled {type(exc).__name__}. "
                    "Check Render logs for the traceback."
                ),
                "details": {"path": request.url.path},
            }
        },
    )


@app.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(tools_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(domains_router)
