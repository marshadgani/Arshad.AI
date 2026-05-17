FROM python:3.12-slim

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

# Render runs migrations via preDeployCommand before the container goes live.
# docker-compose overrides this CMD with its own `command:` (db-init handles migrations).
# alembic here is a fallback only — non-fatal so uvicorn starts even if it fails
# (e.g. DATABASE_URL points to the Supabase transaction pooler which rejects DDL).
# Set DATABASE_URL_DIRECT on Render to the direct db.*.supabase.co:5432 URL.
CMD ["sh", "-c", "(alembic upgrade head || echo '[startup] WARN: alembic failed — set DATABASE_URL_DIRECT on Render; preDeployCommand should have run migrations') && (python -m scripts.seed_from_mock || echo '[startup] seed skipped/failed — non-fatal') && exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
