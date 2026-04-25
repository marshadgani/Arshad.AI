# tool-dispatcher

**Domain:** `ai-core`
**Branch:** `agent/ai-core/tool-dispatcher`

## Purpose

Resolves and invokes Claude tool calls against registered handlers

## Structure

```
tool-dispatcher/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/ai-core/tool-dispatcher/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/ai-core/tool-dispatcher` only
- PRs target `domain/ai-core`, never `main` directly
- Merge path: `agent/*` → `domain/ai-core` → `develop` → `main`

## Development

```bash
# Install dependencies
pip install -r src/requirements.txt

# Run tests
pytest tests/ -v

# Start agent (dev mode)
uvicorn src.main:app --reload --port 8001
```
