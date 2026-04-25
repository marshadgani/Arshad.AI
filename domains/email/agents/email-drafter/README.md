# email-drafter

**Domain:** `email`
**Branch:** `agent/email/email-drafter`

## Purpose

Composes and saves email drafts based on user intent

## Structure

```
email-drafter/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/email/email-drafter/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/email/email-drafter` only
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
