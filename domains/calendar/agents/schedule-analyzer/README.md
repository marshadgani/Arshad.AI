# schedule-analyzer

**Domain:** `calendar`
**Branch:** `agent/calendar/schedule-analyzer`

## Purpose

Summarises upcoming schedule and identifies conflicts or gaps

## Structure

```
schedule-analyzer/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/calendar/schedule-analyzer/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/calendar/schedule-analyzer` only
- PRs target `domain/calendar`, never `main` directly
- Merge path: `agent/*` → `domain/calendar` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
