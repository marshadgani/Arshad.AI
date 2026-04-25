import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.v1.dashboard import router as dashboard_router
from src.api.v1.domains import router as domains_router
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


@app.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok"}


app.include_router(dashboard_router)
app.include_router(domains_router)
