# event-updater

**Domain:** `calendar`
**Branch:** `agent/calendar/event-updater`

## Purpose

Updates, reschedules, or cancels existing calendar events

## Structure

```
event-updater/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/calendar/event-updater/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/calendar/event-updater` only
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
