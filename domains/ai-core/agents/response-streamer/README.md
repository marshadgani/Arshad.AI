# response-streamer

**Domain:** `ai-core`
**Branch:** `agent/ai-core/response-streamer`

## Purpose

Handles SSE streaming of Claude responses to the frontend

## Structure

```
response-streamer/
├── src/          ← implementation
├── tests/        ← unit and integration tests
├── config/       ← config.yaml and env templates
└── README.md
```

## API Gateway

All inter-agent communication goes exclusively through the API gateway.

```
POST /api/v1/ai-core/response-streamer/<action>
```

No direct agent-to-agent calls permitted.

## Branch Rules

- All code changes for this agent live on `agent/ai-core/response-streamer` only
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
