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

# Generate a 32-byte OAUTH_ENCRYPTION_KEY (Phase C+ — encrypts OAuth tokens at rest):
python3 -c 'import secrets, base64; print("OAUTH_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())' >> backend/.env

# Phase C+: register OAuth apps and paste IDs/secrets into backend/.env
#   Google: https://console.cloud.google.com (Credentials → Web app, redirect: /api/v1/auth/google/callback)
#   GitHub: https://github.com/settings/developers (OAuth Apps, callback: /api/v1/auth/github/callback)

# 2. Start all services
docker compose up --build

# 3. Open the app — you'll be redirected to /login
open http://localhost:3000
```

The first run takes a minute longer than subsequent ones — a one-shot
`db-init` service runs Alembic migrations and seeds the dashboard mock
data into Postgres before the backend starts. The backend won't begin
serving until that completes successfully, so the dashboard always
sees a populated DB.

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
│   ├── alembic/               ← migrations (versions/ contains the initial schema)
│   ├── alembic.ini
│   ├── scripts/
│   │   └── seed_from_mock.py  ← idempotent seed; run by db-init compose service
│   └── src/
│       ├── main.py
│       ├── api/v1/            ← versioned REST endpoints (dashboard.py, domains.py)
│       ├── schemas/           ← Pydantic v2 response shapes
│       ├── middleware/cache.py
│       └── models/            ← SQLAlchemy models (database.py + dashboard.py + domain.py)
│
├── frontend/                  ← React 18 + TypeScript + Vite
│   └── src/
│       ├── index.tsx
│       ├── App.tsx
│       ├── components/        ← AppLayout, Sidebar, TopBar, ChatBar, DomainPage
│       ├── pages/             ← Dashboard + 7 domain pages
│       ├── hooks/useFetch.ts  ← generic { data, isLoading, error } hook
│       ├── data/mockData.ts   ← TypeScript shape contracts (now type-only)
│       └── styles/            ← Jarvis design tokens + globals
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

### Tools (Phase D)
Twelve OAuth-backed tools live under `/api/v1/tools/{name}`:

| Provider | Tools |
|---|---|
| Calendar | `calendar_list_events` · `calendar_create_event` · `calendar_update_event` · `calendar_find_free_slots` |
| Gmail | `gmail_search_threads` · `gmail_get_thread` · `gmail_create_draft` · `gmail_apply_label` |
| GitHub | `github_list_issues` · `github_create_issue` · `github_update_issue` · `github_list_prs` |

Discovery: `GET /api/v1/tools` returns each tool's name, description, and input JSON-schema.
Each tool returns `{data: <raw provider JSON>, summary: <normalized fields>}`. Auth-gated by JWT bearer.

### Agents (Phase E)
24 domain agents compose Phase D tools through the in-process gateway at `services/gateway.py`. Endpoint: `POST /api/v1/agents/{domain}/{agent}/run`.

| Domain | Agents |
|---|---|
| `calendar` | `event_creator` · `event_updater` · `meeting_suggester` · `schedule_analyzer` |
| `email` | `email_searcher` · `email_drafter` · `email_labeler` · `email_summarizer` (heuristic) |
| `github` | `issue_manager` (verb-routed) · `pr_reviewer` (heuristic) · `code_summarizer` (placeholder) · `repo_monitor` |
| `ai_core` | `chat_orchestrator` (placeholder) · `tool_dispatcher` · `context_manager` (placeholder) · `response_streamer` (placeholder) |
| `data_pipeline` | `calendar_ingestor` · `email_ingestor` · `github_ingestor` · `analytics_processor` (Phase F — real ingestion via DB queue + Airflow / in-process worker) |
| `infrastructure` | `api_gateway` (self-ref) · `auth_manager` · `cache_manager` · `health_monitor` |

Discovery: `GET /api/v1/agents` returns each agent's domain/name/description/input_schema/tool_dependencies.
Placeholder agents return 501 `not_yet_implemented` with the owning_phase (B or F) so the frontend knows which roadmap item lights them up.

### Ingestion (Phase F)
The 4 `data_pipeline` agents are now real INSERT-queue triggers. Each call inserts a row into `dag_trigger_queue` and returns a `run_id`; the actual ingestion happens in either Airflow (local docker-compose) or an in-process FastAPI worker (Render prod) — same `services/ingestion/runner.py` code path either way.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/agents/data_pipeline/{calendar_ingestor,email_ingestor,github_ingestor,analytics_processor}/run` | Enqueues an ingestion run; returns `run_id` |
| `GET /api/v1/agents/data_pipeline/runs/{run_id}` | Status of a single run (pending / picked / completed / failed) |
| `GET /api/v1/agents/data_pipeline/runs?status=...&limit=20` | Recent runs for the calling user |

Ingested data lands in `ingested_calendar_events`, `ingested_gmail_threads`, `ingested_github_activity`, `ingested_analytics_summary` — hybrid storage with typed `user_id` / `occurred_at` / `provider_id` columns + `raw jsonb`. Ingestors publish `events.<provider>.ingested` to Redis pub/sub on each successful run.

**Render prod**: set `ENABLE_INPROCESS_WORKER=true` to start the queue worker alongside FastAPI (no Airflow needed). **Local docker-compose**: leave it `false` — Airflow handles the queue.

## Airflow UI
Dashboard at http://localhost:8080 — login: `admin` / `admin`.
