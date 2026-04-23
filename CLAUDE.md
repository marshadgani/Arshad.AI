# Arshad.AI — Claude Guide

## Project Overview
AI-powered personal assistant with calendar, email, and GitHub integrations. Claude is the AI brain; the backend exposes a chat API that uses tool-calling to take real actions.

## Architecture
```
frontend/   React 18 + TypeScript — chat UI, sidebar with events/emails
backend/    FastAPI — chat endpoint, Claude tool orchestration, REST helpers
postgres    Persistent storage for conversation history and user preferences
redis       Session cache and short-lived tool-call state
```

## Key Conventions
- **Backend**: async everywhere — use `async def` and `await`. Never block the event loop.
- **Frontend**: functional components with hooks only. No class components.
- **Env vars**: never hard-code secrets. Add new vars to `backend/.env.example` when introducing them.
- **AI**: all Claude calls go through `backend/src/services/ai.py`. Tool definitions live in `backend/src/tools/`.

## Running Locally
```bash
cp backend/.env.example backend/.env   # fill in ANTHROPIC_API_KEY
docker compose up --build
```
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Adding a New Tool (Claude integration)
1. Add the tool definition dict to `backend/src/tools/definitions.py`
2. Implement the handler in `backend/src/tools/handlers.py`
3. Register it in the `TOOL_HANDLERS` map

## Environment Variables
| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — required |
| `DATABASE_URL` | Async PostgreSQL DSN |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | App secret for signing sessions |
