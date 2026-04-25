# api-gateway

**Domain:** `infrastructure`
**Branch:** `agent/infrastructure/api-gateway`

## Purpose

Central API gateway — routes, authenticates, and rate-limits all requests

## Structure

```
api-gateway/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/infrastructure/api-gateway/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/infrastructure/api-gateway` only
- PRs target `domain/infrastructure`, never `main` directly
- Merge path: `agent/*` → `domain/infrastructure` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
