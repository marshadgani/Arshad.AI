# Arshad.AI — Permanent Project Memory

> This file is the single source of truth for Claude working on this project.
> Read it fully at the start of every session before touching any code.

---

## 1. What This Project Is

Arshad.AI is a personal AI assistant powered by Claude. It lets the user manage their calendar, email, and GitHub through a natural-language chat interface. Claude is the AI brain; the backend orchestrates tool-calling to take real actions — not just describe them.

**Target user:** The project owner (Arshad) — single-user, personal productivity focus.

**Core integrations planned:**
- Google Calendar — create, update, query events; suggest meeting times
- Gmail — search threads, draft replies, label and organise
- GitHub — issues, PRs, code review summaries

---

## 2. Architecture

```
frontend/        React 18 + TypeScript (Vite 5) — chat UI + sidebar
backend/         FastAPI — chat API, Claude tool orchestration, REST helpers
postgres         Persistent storage: conversation history, user preferences
redis            Session cache + short-lived tool-call state
airflow          Data pipeline scheduler (Apache Airflow 2.9)
```

All services start with `docker compose up --build`.

---

## 3. Tech Stack — Decisions & Rationale

| Layer | Choice | Why |
|---|---|---|
| Frontend framework | React 18 + TypeScript | Functional components, hooks, strict typing |
| Frontend bundler | **Vite 5** (not CRA) | CRA / react-scripts caps at TypeScript ≤4; Vite supports TS5 natively |
| TypeScript version | 5.x | Latest; requires `moduleResolution: "bundler"` in tsconfig |
| Backend | FastAPI (Python) | Async-native, automatic OpenAPI docs, Pydantic v2 |
| ORM | SQLAlchemy 2.x async | `AsyncSession`, `async_sessionmaker`, non-blocking DB access |
| DB driver | asyncpg | Only async-compatible Postgres driver for SQLAlchemy |
| Cache | Redis 7 (redis-py async) | Lazy singleton via `get_redis()`; used for sessions and tool state |
| AI SDK | anthropic >= 0.25.0 | Claude tool-calling; all AI calls go through `backend/src/services/ai.py` |
| Migrations | Alembic | Never edit existing migrations; always generate new ones |
| Pipelines | Apache Airflow 2.9 | LocalExecutor, postgres backend, DAGs volume-mounted from `data-pipelines/ingestion/` |

---

## 4. Services & Ports

| Service     | Port | URL |
|-------------|------|-----|
| Frontend    | 3000 | http://localhost:3000 |
| Backend API | 8000 | http://localhost:8000 |
| API Docs    | 8000 | http://localhost:8000/docs |
| Airflow UI  | 8080 | http://localhost:8080 (admin / admin) |
| PostgreSQL  | 5432 | — |
| Redis       | 6379 | — |

---

## 5. Project File Map

```
Arshad.AI/
├── CLAUDE.md                          ← YOU ARE HERE — permanent project memory
├── README.md                          ← public-facing overview, services table, workflow rules
├── .gitignore
├── docker-compose.yml                 ← all 5 services with healthchecks
│
├── .claude/
│   ├── settings.json                  ← model: claude-sonnet-4-6, memory: project
│   ├── agents/
│   │   ├── code-reviewer.md           ← bugs, security, perf; outputs Critical/Warning/Suggestion
│   │   ├── debugger.md                ← 6-step root-cause protocol (reproduce → isolate → hypothesize → verify → fix → confirm)
│   │   ├── doc-writer.md              ← docstrings, JSDoc, README, API ref; never documents the obvious
│   │   ├── refactorer.md              ← named refactoring patterns; always runs tests before and after
│   │   ├── security-auditor.md        ← OWASP checklist, secrets, auth, injection, deps
│   │   └── test-writer.md             ← pytest (backend) + RTL (frontend); AAA pattern; one assertion per test
│   ├── commands/
│   │   ├── fix-issue.md               ← /fix-issue <number> — 8-step end-to-end
│   │   ├── deploy.md                  ← /deploy [staging|production] — 5 pre-checks before deploy
│   │   └── pr-review.md               ← /pr-review <number> — runs code-reviewer + security-auditor
│   ├── hooks/
│   │   ├── pre-commit.sh  (chmod+x)   ← tsc → eslint (with prefix strip) → ruff → secret scan
│   │   └── lint-on-save.sh (chmod+x)  ← dispatches by extension: ts/tsx → eslint, py → ruff, sh → shellcheck
│   ├── rules/
│   │   ├── api.md                     ← REST design, status codes, error shape, pagination, streaming
│   │   ├── database.md                ← models, queries, Alembic, indexes, naming conventions
│   │   └── frontend.md                ← components, TypeScript, hooks, CSS Modules, performance
│   └── skills/                        ← empty; ready for future skills
│
├── backend/
│   ├── Dockerfile                     ← python:3.12-slim, uvicorn --reload
│   ├── .env.example                   ← template; copy to .env and fill in secrets
│   ├── requirements.txt               ← fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, redis, anthropic, alembic, httpx
│   └── src/
│       ├── main.py                    ← FastAPI app + CORS (localhost:3000) + /health
│       ├── middleware/
│       │   └── cache.py               ← Redis singleton; get_redis() / close_redis()
│       └── models/
│           ├── __init__.py
│           └── database.py            ← async engine, AsyncSessionLocal, Base, get_db()
│
├── frontend/
│   ├── Dockerfile                     ← node:20-alpine, npm start
│   ├── index.html                     ← Vite entry point (root, not public/)
│   ├── vite.config.ts                 ← port 3000, /api proxy → localhost:8000
│   ├── package.json                   ← react 18, react-dom, react-router-dom v6, vite 5, typescript 5
│   ├── tsconfig.json                  ← strict, moduleResolution: bundler, noEmit: true
│   └── src/
│       ├── index.tsx                  ← ReactDOM.createRoot
│       └── App.tsx                    ← BrowserRouter + Route "/" → Dashboard placeholder
│
├── data-pipelines/
│   ├── requirements.txt               ← apache-airflow==2.9.3, providers (postgres, redis, http), anthropic, pandas
│   ├── config/
│   │   └── airflow.cfg                ← LocalExecutor, postgres backend, logs, webserver port 8080
│   └── ingestion/
│       └── example_dag.py             ← DAG: arshad_ai_data_ingestion (@daily, stub ingest_data task, 2 retries)
│
└── tasks/
    ├── todo.md                        ← task plans with checkable items; add review section when done
    └── lessons.md                     ← lessons captured after every correction; review at session start
```

---

## 6. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Claude API key |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://postgres:postgres@localhost:5432/arshad_ai` |
| `REDIS_URL` | Yes | `redis://localhost:6379` |
| `SECRET_KEY` | Yes | App secret — must not be `change-me` in production |

Never hard-code secrets. Always add new vars to `backend/.env.example`.

---

## 7. Running Locally

```bash
# First time
cp backend/.env.example backend/.env
# Set ANTHROPIC_API_KEY in backend/.env

# Every time
docker compose up --build

# Frontend only (fast iteration)
cd frontend && npm run start

# Backend only
cd backend && uvicorn src.main:app --reload --port 8000
```

---

## 8. Key Code Patterns

### Adding a new Claude tool
1. Define the tool schema in `backend/src/tools/definitions.py`
2. Implement the handler in `backend/src/tools/handlers.py`
3. Register it in the `TOOL_HANDLERS` map
4. All Claude calls go through `backend/src/services/ai.py` — never inline

### Adding a new API endpoint
Follow `.claude/rules/api.md`:
- Plural noun resource names, kebab-case URLs
- Pydantic v2 request/response models (`<Action><Resource>Request`, `<Resource>Response`)
- Consistent response shape: `{"data": {...}}` or `{"data": [...], "total": N}`
- Error shape: `{"error": {"code": "snake_case", "message": "Human readable", "details": {}}}`
- Auth dependency via `Depends()` — never inline

### Adding a new database model
Follow `.claude/rules/database.md`:
- Inherit from `Base`
- UUID primary key (`default=uuid.uuid4`)
- `created_at` + `updated_at` timestamps
- Never use string interpolation in queries
- Generate Alembic migration: `alembic revision --autogenerate -m "description"`

### Adding a new React component
Follow `.claude/rules/frontend.md`:
- Functional component, one per file, file name = component name
- Props interface named `<Component>Props`, exported
- CSS Modules for styles (`.module.css`)
- No hardcoded colours — use CSS variables from `index.css`

### Adding a new Airflow DAG
- Place in `data-pipelines/ingestion/`
- Use `@daily` schedule unless specified otherwise
- `catchup=False` always
- Tag with `["arshad-ai", "<category>"]`
- `retries=2`, `retry_delay=timedelta(minutes=5)`

---

## 9. Pre-commit Hook

The hook lives at `.claude/hooks/pre-commit.sh` and is installed at `.git/hooks/pre-commit`.

**To re-install after a fresh clone:**
```bash
cp .claude/hooks/pre-commit.sh .git/hooks/pre-commit
```

**What it checks (in order):**
1. `npx tsc --noEmit` — TypeScript type check (blocks on error)
2. ESLint on staged `.ts`/`.tsx` files — strips `frontend/` prefix before passing to ESLint
3. Ruff on staged `.py` files
4. Secret scan on staged diff — blocks if API keys or passwords detected

**Known behaviour:** ESLint step skips gracefully if no ESLint config is present.

---

## 10. Git

- **Active branch:** `claude/ai-personal-assistant-CcA11`
- **Remote:** `origin` → `marshadgani/Arshad.AI`
- **Push command:** `git push -u origin claude/ai-personal-assistant-CcA11`
- Commit message format: `type: short description` (feat / fix / docs / refactor / test)
- Every commit message ends with the session URL

---

## 11. Setup Decisions Made (Never Revisit Without Good Reason)

| Decision | Reason |
|---|---|
| Vite 5 instead of Create React App | CRA (react-scripts 5) only supports TypeScript ≤4; peer dep conflict with TS5 |
| `moduleResolution: "bundler"` | Required by TypeScript 5; `"node"` is deprecated and blocked in TS7 |
| Async SQLAlchemy throughout | Blocking DB calls on an async event loop cause deadlocks and performance collapse |
| Redis singleton (lazy init) | Avoids connection at import time; safe for testing and cold starts |
| LocalExecutor for Airflow | Single-machine setup; CeleryExecutor adds complexity not yet needed |
| Airflow DB in same Postgres | Dev convenience; in production, use a separate Airflow database |
| UUID primary keys | Avoids enumeration attacks and distributed ID conflicts |
| No Redux | Overkill for current scale; Context API sufficient |

---

## 12. Lessons Learned During Setup

**Lesson 1 — CRA + TypeScript 5 peer conflict**
`react-scripts@5.0.1` declares `peerOptional typescript@"^3.2.1 || ^4"` and fails to install with TypeScript 5. Fix: replace CRA with Vite 5.

**Lesson 2 — `moduleResolution: "node"` deprecated**
TypeScript 5 treats `moduleResolution: "node"` (node10) as deprecated and will remove it in TS7. Always use `"bundler"` for Vite projects.

**Lesson 3 — Pre-commit hook path handling**
`git diff --cached --name-only` returns repo-relative paths (`frontend/App.tsx`). ESLint is run from inside `frontend/`, so the `frontend/` prefix must be stripped before passing paths to ESLint. Without this, ESLint reports "no files found" and blocks every commit.

---

## 13. Workflow Orchestration

### Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review `tasks/lessons.md` at the start of every session

### Verification Before Done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## 14. Task Management

1. **Plan First** — Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan** — Check in with user before starting work on large tasks
3. **Track Progress** — Mark items complete as you go, not in a batch at the end
4. **Explain Changes** — One-sentence high-level summary at each meaningful step
5. **Document Results** — Add a review section to `tasks/todo.md` when done
6. **Capture Lessons** — Update `tasks/lessons.md` after every correction

---

## 15. Core Principles

- **Simplicity First** — Make every change as simple as possible. Minimal code impact.
- **No Laziness** — Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact** — Only touch what is necessary. Avoid introducing bugs in unrelated code.
- **No Comments on the Obvious** — Only comment the WHY when it's non-obvious. Never describe WHAT.
- **No Unused Code** — Don't leave dead imports, commented-out blocks, or unused variables.
- **Security by Default** — Validate at system boundaries. Never trust user input. Secrets in env vars only.
