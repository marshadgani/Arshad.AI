# code-summarizer

**Domain:** `github`
**Branch:** `agent/github/code-summarizer`

## Purpose

Produces plain-English summaries of commits and code changes

## Structure

```
code-summarizer/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/github/code-summarizer/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/github/code-summarizer` only
- PRs target `domain/github`, never `main` directly
- Merge path: `agent/*` → `domain/github` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
