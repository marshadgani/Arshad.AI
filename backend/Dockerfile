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
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
