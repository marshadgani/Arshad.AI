# email-searcher

**Domain:** `email`
**Branch:** `agent/email/email-searcher`

## Purpose

Searches Gmail threads by query, date range, sender, or label

## Structure

```
email-searcher/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/email/email-searcher/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/email/email-searcher` only
- PRs target `domain/email`, never `main` directly
- Merge path: `agent/*` → `domain/email` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
