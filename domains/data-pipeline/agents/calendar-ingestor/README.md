# calendar-ingestor

**Domain:** `data-pipeline`
**Branch:** `agent/data-pipeline/calendar-ingestor`

## Purpose

Airflow DAG: pulls calendar events into Postgres daily

## Structure

```
calendar-ingestor/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/data-pipeline/calendar-ingestor/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/data-pipeline/calendar-ingestor` only
- PRs target `domain/data-pipeline`, never `main` directly
- Merge path: `agent/*` → `domain/data-pipeline` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
