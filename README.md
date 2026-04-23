# Arshad.AI

Personal AI assistant powered by Claude. Manages your calendar, email, and GitHub through a natural-language chat interface.

## Stack
- **Frontend**: React 18 + TypeScript + React Router v6
- **Backend**: FastAPI (Python) + Anthropic SDK
- **Database**: PostgreSQL 16 (async via SQLAlchemy)
- **Cache**: Redis 7
- **AI**: Claude (tool use for calendar / email / GitHub actions)

## Quick Start

```bash
# 1. Clone and configure
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY at minimum

# 2. Start all services
docker compose up --build

# 3. Open the app
open http://localhost:3000
```

## Services

| Service  | Port | Description                  |
|----------|------|------------------------------|
| frontend | 3000 | React chat UI                |
| backend  | 8000 | FastAPI + Claude tool runner |
| postgres | 5432 | Persistent storage           |
| redis    | 6379 | Session / response cache     |

## API Docs
Interactive Swagger UI at http://localhost:8000/docs when backend is running.

## Project Structure
```
backend/src/
  main.py          FastAPI app entry point
  middleware/
    cache.py       Redis singleton
  models/
    database.py    Async SQLAlchemy engine + session

frontend/src/
  index.tsx        React entry point
  App.tsx          Router + root component
```
