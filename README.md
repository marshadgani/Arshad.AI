# Arshad.AI

Personal AI assistant powered by Claude. Manages your calendar, email, and GitHub through a natural-language chat interface.

## Stack
- **Frontend**: React 18 + TypeScript + Vite 5
- **Backend**: FastAPI (Python) + Anthropic SDK
- **Database**: PostgreSQL 16 (async via SQLAlchemy)
- **Cache**: Redis 7
- **Pipelines**: Apache Airflow 2.9
- **AI**: Claude (tool use for calendar / email / GitHub actions)

## Quick Start

```bash
# 1. Configure environment (two .env files — both are gitignored)
cp .env.example .env                   # docker-compose vars: Postgres + Airflow credentials
cp backend/.env.example backend/.env   # backend app vars: DATABASE_URL, REDIS_URL, SECRET_KEY, ANTHROPIC_API_KEY

# Generate a non-default SECRET_KEY (startup refuses the literal "change-me"):
python3 -c 'import secrets; print("SECRET_KEY=" + secrets.token_urlsafe(32))' >> backend/.env

# 2. Start all services
docker compose up --build

# 3. Open the app
open http://localhost:3000
```

## Services at a Glance

| Service      | Port | Tech                          |
|--------------|------|-------------------------------|
| Frontend     | 3000 | React 18 + TypeScript         |
| Backend API  | 8000 | FastAPI + PostgreSQL + Redis  |
| Airflow      | 8080 | Apache Airflow 2.9            |
| PostgreSQL   | 5432 | Postgres 16                   |
| Redis        | 6379 | Redis 7                       |

Everything runs via `docker compose up`. The codebase is a clean scaffold — business logic, data models, UI components, and pipeline tasks are ready to be built on top.

## Workflow Rules (from CLAUDE.md)

| #  | Rule                    | Key Point                                                        |
|----|-------------------------|------------------------------------------------------------------|
| 1  | **Plan Mode Default**   | Enter plan mode for any 3+ step task; re-plan if stuck           |
| 2  | **Subagent Strategy**   | Offload research & parallel work; one task per subagent          |
| 3  | **Self-Improvement Loop** | Log corrections to `tasks/lessons.md`; review each session    |
| 4  | **Verification Before Done** | Prove it works — tests, logs, correctness check            |
| 5  | **Demand Elegance**     | Ask "is there a more elegant way?" for non-trivial changes       |
| 6  | **Autonomous Bug Fixing** | Given a bug → just fix it, no hand-holding needed              |

**Task Management flow:** Plan → Verify → Track → Explain → Document → Capture lessons

**Core Principles:** Simplicity first · No laziness · Minimal impact

## Project Structure

```
Arshad.AI/
├── CLAUDE.md                  ← workflow rules + project conventions
├── docker-compose.yml         ← all 5 services wired together
│
├── backend/                   ← FastAPI + SQLAlchemy + Redis + Anthropic SDK
│   └── src/
│       ├── main.py
│       ├── middleware/cache.py
│       └── models/database.py
│
├── frontend/                  ← React 18 + TypeScript + Vite
│   └── src/
│       ├── index.tsx
│       └── App.tsx
│
├── data-pipelines/            ← Apache Airflow 2.9
│   ├── config/airflow.cfg
│   └── ingestion/
│       └── example_dag.py    ← DAG: arshad_ai_data_ingestion (@daily)
│
├── .claude/                   ← Claude Code configuration
│   ├── agents/               ← 6 specialist agents
│   ├── commands/             ← /fix-issue /deploy /pr-review
│   ├── hooks/                ← pre-commit + lint-on-save
│   └── rules/                ← frontend / database / api conventions
│
└── tasks/
    ├── todo.md               ← task plans with checkable items
    └── lessons.md            ← lessons captured after corrections
```

## API Docs
Interactive Swagger UI at http://localhost:8000/docs when backend is running.

## Airflow UI
Dashboard at http://localhost:8080 — login: `admin` / `admin`.
