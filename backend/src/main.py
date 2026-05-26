import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.api.v1.dashboard import router as dashboard_router
from src.api.v1.domains import router as domains_router
from src.auth.routers import router as auth_router
from src.middleware.cache import close_redis

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
    yield
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


@app.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(domains_router)
