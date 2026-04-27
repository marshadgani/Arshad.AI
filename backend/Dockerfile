FROM python:3.12-slim

# render-deploy probe — touched 2026-04-25 to confirm auto-deploy fires.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app src/ ./src/
COPY --chown=app:app alembic/ ./alembic/
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app scripts/ ./scripts/

USER app
EXPOSE 8000

# --reload is enabled in docker-compose for local dev; production runs without it.
# Migrations run on every container start so Render free tier (no Pre-Deploy
# Command available) still gets a migrated DB. alembic upgrade is idempotent —
# already-applied revisions are skipped. Seed is idempotent (UPSERT) but
# non-fatal — if it fails (e.g., transient DB hiccup) we still serve traffic.
CMD ["sh", "-c", "alembic upgrade head && (python -m scripts.seed_from_mock || echo '[startup] seed skipped/failed — non-fatal') && exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
