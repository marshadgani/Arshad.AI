# Arshad.AI — Permanent Project Memory

> This file is the single source of truth for Claude working on this project.
> Read it fully at the start of every session before touching any code.

## Auto-Trigger Rule — GitHub URLs

**Whenever a GitHub URL (github.com/...) appears in a user prompt, automatically run `/fetch-github-repo <url>` on it.**
No need for the user to type the command — detect the URL and trigger the fetch procedure immediately.

## Model Strategy (Read First)

Three tiers. Pick by **cost-of-being-wrong**, not task length.

| Tier | Model ID | When |
|---|---|---|
| **Cheap** | `claude-haiku-4-5-20251001` | Mechanical, near-deterministic, output verifiable in one read. Classification, intent routing, file lookups, single-line fixes, renames, config tweaks, lint cleanups, structured-extraction agents (BA, process-organiser), grep-style search. |
| **Default** | `claude-sonnet-4-6` | Code writing, normal investigation, agent execution. The workhorse for every task that needs understanding but not deep reasoning. |
| **Premium** | `claude-opus-4-7` | Planning, architecture, quality gates, hard debugging, security audit. Anything where wrong decisions cascade. |

**Routing rule:** Haiku for verifiable mechanical work → Sonnet for default execution → Opus for high-leverage thinking. Most prompts land on Sonnet.

**Planning rule (unchanged):** Before writing a line of code on any non-trivial task, invoke the `planner` agent (Opus) via `/plan <description>`. Opus thinks, Sonnet builds, Haiku tidies.

**Escalation rule:** If a task fails on its assigned tier, **escalate one level** — never retry on the same tier. Haiku confused → Sonnet. Sonnet stuck after 1 attempt → Opus. The escalation path is the real quality guarantee.

**Never skip planning for:**
- New features touching multiple files or layers
- New dependencies or services
- Database schema changes
- Any task where the approach is unclear

**Skip planning (route directly to Haiku) for:**
- Single-line fixes
- Config value changes
- Renames
- Adding a single test
- Status / lookup questions

**Per-call override:** When the orchestrator knows better than an agent's frontmatter default, pass `Task(model="haiku" | "sonnet" | "opus")`. Resolution order: per-call > frontmatter > project default > inherited.

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
backend/         FastAPI — versioned REST API (/api/v1/*), chat (Phase B), Claude tool orchestration (Phase D)
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
| AI SDK | anthropic 0.42.0 (pinned) | Claude tool-calling; all AI calls will be routed through `backend/src/services/ai.py` once that module exists |
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
│   ├── Dockerfile                     ← python:3.12-slim, uvicorn --reload, COPY src + alembic + scripts
│   ├── .env.example                   ← template; copy to .env and fill in secrets
│   ├── requirements.txt               ← fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, redis, anthropic, alembic, httpx
│   ├── alembic.ini
│   ├── alembic/                       ← async-aware env.py, versions/
│   │   └── versions/                  ← initial dashboard schema migration (20 tables)
│   ├── scripts/
│   │   └── seed_from_mock.py          ← idempotent seed run by db-init compose service
│   └── src/
│       ├── main.py                    ← FastAPI app + CORS + /health + custom HTTPException handler
│       ├── api/v1/
│       │   ├── dashboard.py           ← 14 GET endpoints under /api/v1/dashboard/*
│       │   └── domains.py             ← /api/v1/domains, /api/v1/domains/{slug}, /api/v1/nav
│       ├── schemas/                   ← Pydantic v2 response shapes (ORMBase + dashboard.py + domain.py)
│       ├── middleware/
│       │   └── cache.py               ← Redis singleton; get_redis() / close_redis()
│       └── models/
│           ├── __init__.py            ← imports dashboard + domain so Base.metadata sees every table
│           ├── database.py            ← async engine, AsyncSessionLocal, Base, TimestampedMixin, get_db()
│           ├── dashboard.py           ← 14 dashboard widget tables
│           └── domain.py              ← 6 domain catalogue tables (FK → domains.slug)
│
├── frontend/
│   ├── Dockerfile                     ← node:20-alpine, npm start
│   ├── index.html                     ← Vite entry point (root, not public/)
│   ├── vite.config.ts                 ← port 3000, /api proxy → localhost:8000
│   ├── package.json                   ← react 18, react-dom, react-router-dom v6, vite 5, typescript 5
│   ├── tsconfig.json                  ← strict, moduleResolution: bundler, noEmit: true
│   └── src/
│       ├── index.tsx                  ← ReactDOM.createRoot, imports tokens.css + globals.css
│       ├── App.tsx                    ← ErrorBoundary + BrowserRouter + 8 routes (Dashboard + 7 domain pages)
│       ├── components/                ← AppLayout, Sidebar, TopBar, ChatBar, DomainPage
│       ├── pages/                     ← Dashboard.tsx + 7 domain page wrappers
│       ├── hooks/useFetch.ts          ← generic { data, isLoading, error } with AbortController
│       ├── data/mockData.ts           ← TypeScript shape contracts (now type-only — runtime data is in Postgres)
│       └── styles/                    ← tokens.css (Jarvis design tokens) + globals.css
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
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | Phase C+ | Google Cloud OAuth client (web app, redirect `/api/v1/auth/google/callback`) |
| `GITHUB_OAUTH_CLIENT_ID` / `_SECRET` | Phase C+ | GitHub OAuth app (one per environment — GitHub allows only one callback URL per app) |
| `OAUTH_ENCRYPTION_KEY` | Phase C+ | 32-byte URL-safe base64. Encrypts provider tokens at rest. Rotation locks all users out. |
| `JWT_EXPIRY_HOURS` | Phase C+ | JWT lifetime; default 24 |
| `BACKEND_URL` / `FRONTEND_URL` | Phase C+ | Public URLs — used to build provider redirect URIs and post-login frontend redirect |
| `ENABLE_INPROCESS_WORKER` | Phase F+ | `true` to start the queue worker on FastAPI lifespan (Render). Leave `false` in docker-compose where Airflow handles it. |
| `QUEUE_POLL_INTERVAL_SECONDS` | Phase F+ | Worker poll interval; default `5`. |
| `MAX_INGEST_BATCH_SIZE` | Phase F+ | Per-DAG row limit per run; default `100`. |
| `ANTHROPIC_MODEL_DEFAULT` | Phase B+ | Default model name; defaults to `claude-haiku-4-5-20251001`. |
| `CHAT_MAX_TOKENS` | Phase B+ | Max output tokens per chat turn; default `2048`. |
| `CHAT_HISTORY_TOKEN_BUDGET` | Phase B+ | Drop oldest user/assistant pairs once history exceeds this; default `8000`. |

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

### Adding a new Claude tool *(Phase D — implemented)*

Tool layout (per Phase D spec at `docs/superpowers/specs/2026-04-26-backend-phase-d-design.md`):

```
backend/src/tools/
├── base.py            ← Tool ABC + ToolError / ProviderNotLinked / ProviderReauthRequired
├── registry.py        ← TOOL_REGISTRY + @register decorator
├── token_service.py   ← get_access_token + refresh_google_token
├── clients/           ← google_calendar, gmail, github HTTP wrappers
├── calendar/ gmail/ github/   ← one module per tool
└── routers.py         ← POST /api/v1/tools/{name}
```

To add a tool:
1. Pick the provider directory (`tools/<provider>/`).
2. Create a module with `Input` / `Output` Pydantic schemas (output MUST have `data` + `summary`) and a class subclassing `Tool` with `@register` decorator.
3. Import the module in the provider's `__init__.py` so `@register` runs at app startup.
4. The REST endpoint `POST /api/v1/tools/{name}` and the `TOOL_REGISTRY` map both pick it up automatically.

Phase B chat will eventually call tools directly via `TOOL_REGISTRY[name](user=..., db=..., payload=...)` — no HTTP round-trip needed.

### Adding a new domain agent *(Phase E — implemented)*

Agent layout (per Phase E spec at `docs/superpowers/specs/2026-04-26-backend-phase-e-design.md`):

```
backend/src/agents/
├── base.py            ← Agent ABC + AgentError + AgentNotImplemented
├── registry.py        ← AGENT_REGISTRY + @register decorator
├── routers.py         ← POST /api/v1/agents/{domain}/{agent}/run + GET /api/v1/agents
├── calendar/ email/ github/ ai_core/ data_pipeline/ infrastructure/   ← one module per agent

backend/src/services/
└── gateway.py         ← dispatch(domain, agent, user, db, payload) — single in-process entry point
```

To add an agent:
1. Pick the domain directory (`agents/<domain>/`).
2. Create a module with `Input`/`Output` Pydantic schemas (output MUST have `data` + `summary`) and a class subclassing `Agent` with `@register` decorator. Set `domain`, `name`, `description`, `tool_dependencies` (Phase D tool slugs).
3. Import the module in the domain's `__init__.py` so `@register` runs at app startup.
4. The REST endpoint and `AGENT_REGISTRY` map both pick it up automatically. The gateway routes by `(domain, name)` slug.

Inter-agent calls (rule §19.4): never call another agent's `run()` directly — call `gateway.dispatch(...)` so cross-cutting concerns (auth, error mapping) stay in one place.

LLM-bound agents (chat orchestration, summarisation, code review) raise `AgentNotImplemented(slug, owning_phase="Phase B")` from `run()` until Phase B replaces with real Claude calls.

### Adding a new ingestion DAG *(Phase F — implemented)*

Layout (per Phase F spec at `docs/superpowers/specs/2026-04-26-backend-phase-f-design.md`):

```
backend/src/services/ingestion/
├── runner.py            ← run(dag_id, user_id, payload, db) — single dispatch point
├── calendar.py          ← per-DAG ingestion logic (called by runner)
├── email.py
├── github.py
└── analytics.py

backend/src/services/queue_worker.py  ← in-process FastAPI worker (Render)
backend/src/models/dag_trigger.py     ← DagTriggerQueue ORM model
backend/src/models/ingested.py        ← 4 ingested_* tables

data-pipelines/ingestion/
├── _ingestion_helpers.py   ← shared claim_one / run_ingest_for_row / mark_done
├── calendar_dag.py         ← thin Airflow wrapper (sensor → ingest → mark_done)
├── email_dag.py
├── github_dag.py
└── analytics_dag.py
```

To add a new ingestion DAG:
1. Write a new module in `backend/src/services/ingestion/<name>.py` exposing `async def ingest(*, user, db, payload) -> dict`.
2. Wire it into `runner.py`'s dispatch.
3. Replace the corresponding `data_pipeline/<name>_ingestor.py` agent's `AgentNotImplemented` with a real INSERT-queue body.
4. Copy one of the existing `*_dag.py` files in `data-pipelines/ingestion/` and change the `DAG_ID` string.

Both Airflow (docker-compose dev) and the in-process queue worker (Render prod via `ENABLE_INPROCESS_WORKER=true`) consume the same `dag_trigger_queue` table with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`. Same logic, two execution environments.

### Adding chat features *(Phase B — implemented; final phase)*

Layout (per Phase B spec at `docs/superpowers/specs/2026-04-26-backend-phase-b-design.md`):

```
backend/src/
├── services/
│   ├── ai.py                  ← Anthropic SDK wrapper (call + stream)
│   ├── intent_classifier.py   ← stage-1 Haiku call: domain picker
│   └── chat.py                ← agentic loop + SSE event yielding
├── api/v1/chat.py             ← /api/v1/chat sessions + SSE messages
└── models/conversation.py     ← ConversationSession + ConversationMessage
```

Key invariants:
- **All SDK calls go through `services/ai.py`** — never `anthropic.AsyncAnthropic` inline.
- **SSE event protocol** is defined in the `response_streamer` agent — `delta` / `tool_use` / `tool_result` / `intent` / `error` + `[DONE]` terminator.
- **Two-stage routing**: stage-1 keyword fast-path or Haiku classifier picks domain; stage-2 Haiku call gets only that domain's tools (calendar / email / github / general). Tool subset is computed in `services.chat._tool_subset(intent)`.
- **History is reconstructed** from `conversation_messages` rows on every turn so the SDK call sees the canonical Anthropic-API-shaped messages array. Token-budget compression drops oldest user/assistant turns until under `CHAT_HISTORY_TOKEN_BUDGET`.
- **Inter-agent calls inside the agentic loop** still go through the gateway — `services.chat._dispatch_tool` validates input + runs via `Tool()(...)` or `Agent.run(...)`.
- **Claude tool use exposes agents** via `agent_<slug>` prefix; `_dispatch_tool` strips the prefix and dispatches.

To add a new chat-relevant tool or agent:
1. Build it under Phase D (tool) or Phase E (agent) per their existing patterns.
2. Add it to `services.chat._tool_subset` for the appropriate intent so Claude can pick it.

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

### Claude Code lifecycle hooks (in `.claude/settings.json`)

These run automatically on Claude tool calls — separate from the git/editor hooks above.

| Event | Matcher | Script | Purpose |
|---|---|---|---|
| `SessionStart` | `*` | `.claude/hooks/session-start.sh` | Weekly skill / agent / command sync from upstream repos |
| `PreToolUse` | `Bash` | `.claude/hooks/bash-guard.sh` | Block unambiguously destructive commands (`rm -rf /`, `mkfs`, fork bombs) |
| `PostToolUse` | `Edit\|Write\|MultiEdit` | `.claude/hooks/post-edit-format.sh` | Best-effort autoformat: `ruff format` on `.py`, `eslint --fix` on `.ts`/`.tsx` |

`bash-guard.sh` exits 2 to block; the matcher list is conservative — extend it only when a command is genuinely dangerous in this repo.

---

## 9b. Personal overrides — `CLAUDE.local.md` + `settings.local.json`

Both are gitignored. Templates committed as `CLAUDE.local.md.example` and `.claude/settings.local.json.example`.

| File | Purpose |
|---|---|
| `CLAUDE.local.md` | Personal paths, "when I say X" shortcuts, current focus — anything that shouldn't enter the shared repo. Loaded alongside `CLAUDE.md` every session. |
| `.claude/settings.local.json` | Per-machine model override, env vars, and Bash allowlist (`permissions.allow`) to reduce permission prompts. Overlays `.claude/settings.json`. |

To start using either:
```bash
cp CLAUDE.local.md.example CLAUDE.local.md
cp .claude/settings.local.json.example .claude/settings.local.json
```

---

## 10. Git

- **Source branches:** any non-main branch (e.g. `claude/ai-personal-assistant-develop-AION`, `feat/<x>`, `fix/<y>`). The `auto-pr.yml` workflow triggers on push to any branch except the merge target.
- **Merge target:** `claude/ai-personal-assistant-main` (see §20)
- **Remote:** `origin` → `marshadgani/Arshad.AI`
- **Push command:** `git push -u origin "$(git branch --show-current)"`
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

## 13b. Skill / Agent Routing — read this before picking a tool

The repo carries 77 skills (across 6 sources) and 49 agents (across 4 sources). Most overlap. The default routing is:

**Agents — prefer first-party.** Reach for vendored agents only for these specific niches:
- `deployment-engineer` (n8n-mcp) — new CI/CD, Dockerfiles, Kubernetes
- `mcp-backend-engineer` (n8n-mcp) — anything in `mcp/` or MCP protocol changes
- `technical-researcher` (n8n-mcp) — multi-source framework / vuln evaluation
- `context-manager` (n8n-mcp) — coordinating ≥3 agents across a long task
- `docs-researcher` (context7) — single-library doc fetch with isolated context
- `gsd-*` agents — **only** when running their orchestrating slash command (e.g. `/gsd-plan-phase`). Do not spawn individually.

**Skills — most are nested two levels deep and not auto-surfaced.** Check `.claude/skills/INDEX.md` for the full map. For a skill that the `Skill` tool doesn't list, you can still `Read` the SKILL.md at the path shown in the index and apply its workflow.

Detailed routing tables:
- `.claude/agents/INDEX.md` — task-type → agent
- `.claude/skills/INDEX.md` — task-type → skill, plus inventory by source

When a skill or agent is genuinely useful but invisible, **promote it** by copying the SKILL.md (or agent .md) one directory up so Claude Code discovers it.

---

## 14. Task Management

1. **Plan First** — Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan** — Check in with user before starting work on large tasks
3. **Track Progress** — Mark items complete as you go, not in a batch at the end
4. **Explain Changes** — One-sentence high-level summary at each meaningful step
5. **Document Results** — Add a review section to `tasks/todo.md` when done
6. **Capture Lessons** — Update `tasks/lessons.md` after every correction

### Session lifecycle — `/session-end` + `tasks/handoff.md` + `tasks/dev-log.md`

The repo runs a session-end cycle that keeps Claude productive across sessions:

| File | Behaviour | Read when |
|---|---|---|
| `tasks/handoff.md` | **Overwritten** every session by `/session-end`. Single tight "where we are / what's next / watch out for" snapshot, kept under 60 lines. | Auto-surfaced by `.claude/hooks/session-start.sh` so every new session starts with it in context. |
| `tasks/dev-log.md` | **Append-only** chronological history. New entries go at the top. Past entries are immutable — corrections become new entries. | On demand when historical context is needed (decisions, pivots, skipped work). |
| `tasks/lessons.md` | **Append-only** corrections + rules-going-forward. | Reviewed at session start; durable across sessions. |
| `tasks/last-gate-report.md` | Most-recent gate verdict. Drives the auto-pr workflow's squash-merge. | Read before any "Merge to Main" trigger. |

**At session end, run `/session-end`** (slash command at `.claude/commands/session-end.md`). It writes the handoff, appends the dev log entry, commits both files, and asks before pushing (private by default per the original pattern). **At session start**, the SessionStart hook prints `tasks/handoff.md` so whichever Claude is loaded sees it without being told.

---

## 15. External Skill Sources (Auto-Updated Weekly)

Skills from these GitHub repos are synced into `.claude/skills/` every 7 days.
The update runs **async in the background** at session start — no delay to your first prompt.
A git commit is created automatically when any skill file changes.

### Active Sources — Skills

| Slug | Repo | Skills |
|---|---|---|
| `superpowers` | https://github.com/obra/superpowers.git | brainstorming, dispatching-parallel-agents, executing-plans, finishing-a-development-branch, receiving-code-review, requesting-code-review, subagent-driven-development, systematic-debugging, test-driven-development, using-git-worktrees, verification-before-completion, writing-plans, writing-skills (13) |
| `ui-ux-pro-max` | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git | banner-design, brand, design-system, design, slides, ui-styling, ui-ux-pro-max (7) |
| `claude-mem` | https://github.com/thedotmack/claude-mem.git | do, knowledge-agent, make-plan, mem-search, smart-explore, timeline-report, version-bump (7) |
| `obsidian-skills` | https://github.com/kepano/obsidian-skills.git | defuddle, json-canvas, obsidian-bases, obsidian-cli, obsidian-markdown (5) |
| `context7` | https://github.com/upstash/context7.git | context7-cli, context7-mcp, find-docs (3) |
| `everything-claude-code` | https://github.com/affaan-m/everything-claude-code.git | agent-introspection-debugging, agent-sort, api-design, article-writing, backend-patterns, brand-voice, bun-runtime, claude-api, coding-standards, content-engine, crosspost, deep-research, dmux-workflows, documentation-lookup, e2e-testing, eval-harness, exa-search, fal-ai-media, frontend-design, frontend-patterns, frontend-slides, investor-materials, investor-outreach, market-research, mcp-server-patterns, nextjs-turbopack, product-capability, security-review, strategic-compact, tdd-workflow, verification-loop, video-editing, x-api (34) |
| `gstack` | https://github.com/garrytan/gstack.git | gstack (root meta-skill), browse, qa, review, ship, careful, guard, freeze, unfreeze, learn, codex, retro, canary, scrape, autoplan, skillify, investigate, health, pair-agent, plan-tune, plan-design-review, plan-eng-review, plan-ceo-review, plan-devex-review, devex-review, design-review, design-shotgun, design-html, design-consultation, document-release, gstack-upgrade, land-and-deploy, landing-report, setup-deploy, setup-browser-cookies, setup-gbrain, open-gstack-browser, office-hours, context-save, context-restore, qa-only, cso, make-pdf, benchmark, benchmark-models, hackernews-frontpage, gstack-openclaw-ceo-review, gstack-openclaw-investigate, gstack-openclaw-retro, gstack-openclaw-office-hours (50) |

### Active Sources — Agents

| Slug | Repo | Agents |
|---|---|---|
| `n8n-mcp` | https://github.com/czlonkowski/n8n-mcp.git | code-reviewer, context-manager, debugger, deployment-engineer, mcp-backend-engineer, n8n-mcp-tester, technical-researcher, test-automator (8) |
| `get-shit-done` | https://github.com/gsd-build/get-shit-done.git | gsd-planner, gsd-debugger, gsd-code-reviewer, gsd-executor, gsd-roadmapper, gsd-security-auditor, gsd-verifier + 26 more (33 total) |
| `context7` | https://github.com/upstash/context7.git | docs-researcher (1) |

### Active Sources — Commands

| Slug | Repo | Commands |
|---|---|---|
| `awesome-claude-code` | https://github.com/hesreallyhim/awesome-claude-code.git | evaluate-repository (1) |
| `context7` | https://github.com/upstash/context7.git | docs — `/context7:docs <library> [query]` (1) |

### How It Works

1. `.claude/hooks/session-start.sh` runs at session start (async, background)
2. It reads `.claude/skills/.last-updated` — if < 7 days old, exits silently
3. If 7+ days old, spawns `scripts/update-skills.sh` in the background
4. `update-skills.sh` clones each repo, diffs against current skills, copies changes
5. If any file changed, auto-commits and pushes with message `chore: weekly skill update [YYYY-MM-DD]`
6. Progress is logged to `.claude/skills/.update-log`

### Adding a New Skill Source

Edit **two lines** in `scripts/update-skills.sh`:
```bash
# 1. Add the repo URL
SKILL_SOURCES["my-slug"]="https://github.com/author/repo.git"

# 2. Add the path inside the repo where SKILL.md files live
SKILL_PATHS["my-slug"]="path/to/skills"
```
That's it — it will be cloned, diffed, and committed on the next weekly run.

### Directory Layout

```
.claude/
├── skills/
│   ├── .last-updated          ← Unix timestamp of last successful update
│   ├── .update-log            ← Running log of all update runs
│   ├── superpowers/           ← obra/superpowers — 13 skills
│   ├── ui-ux-pro-max/         ← nextlevelbuilder — 7 skills
│   ├── claude-mem/            ← thedotmack — 7 skills
│   ├── obsidian-skills/       ← kepano — 5 skills
│   ├── context7/              ← upstash/context7 — 3 skills
│   └── everything-claude-code/ ← affaan-m — 34 skills
│
└── agents/
    ├── (project agents)       ← code-reviewer, debugger, planner, etc.
    ├── n8n-mcp/               ← czlonkowski/n8n-mcp — 8 agents
    ├── get-shit-done/         ← gsd-build/get-shit-done — 33 agents
    └── context7/              ← upstash/context7 — 1 agent (docs-researcher)
```

## 16. Core Principles

- **Simplicity First** — Make every change as simple as possible. Minimal code impact.
- **No Laziness** — Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact** — Only touch what is necessary. Avoid introducing bugs in unrelated code.
- **No Comments on the Obvious** — Only comment the WHY when it's non-obvious. Never describe WHAT.
- **No Unused Code** — Don't leave dead imports, commented-out blocks, or unused variables.
- **Security by Default** — Validate at system boundaries. Never trust user input. Secrets in env vars only.

## 17. /fetch-github-repo Command

Fetch and integrate any external GitHub repo into the project. Runs automatically
when a GitHub URL appears in a prompt. Re-fetches all saved repos weekly.

### Trigger
- **Manual:** `/fetch-github-repo <github-url>`
- **Auto:** Any `github.com/...` URL in a user message
- **Weekly:** Every 7 days via `session-start.sh` (Monday 00:00 UTC target)

### What It Extracts

| Component | Detection pattern | Integrated to |
|---|---|---|
| Skills | `SKILL.md` files, `skills/` dirs | `.claude/skills/<slug>/` |
| Agents | `agents/*.md`, `.claude/agents/*.md` | `backend/src/agents/<slug>_*.md` |
| Commands | `commands/*.md`, `.claude/commands/*.md` | `backend/src/commands/<slug>_*.md` |
| Hooks | `hooks/*.sh`, `.claude/hooks/*.sh` | `backend/src/hooks/<slug>_*.sh` |
| Token optimisation | keyword scan in `.md`, `.py`, `.ts` | logged in registry |

### Files Involved
- `scripts/fetch-github-repo.sh` — the integration script
- `.claude/github-repos.json` — persistent URL registry
- `.claude/hooks/session-start.sh` — weekly re-fetch trigger
- `.claude/commands/fetch-github-repo.md` — slash command definition

### Commit Format
```
Integrated external repo: <REPO_NAME> on <DATE>
```

---

## 18. GitHub Repo Registry

All repos fetched via `/fetch-github-repo` are saved in `.claude/github-repos.json`.
This registry is the source of truth for weekly auto-updates.

**To add a new repo:** just paste a GitHub URL in any prompt — it auto-fetches.
**To view registry:** `cat .claude/github-repos.json`
**To force re-fetch all:** restart session (triggers session-start.sh)

### Registered Repos

| Slug | URL | Type | Components | Last Fetched |
|---|---|---|---|---|
| `superpowers` | https://github.com/obra/superpowers.git | skills | 13 skills | 2026-04-25 |
| `ui-ux-pro-max` | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git | skills | 7 skills | 2026-04-25 |
| `claude-mem` | https://github.com/thedotmack/claude-mem.git | skills | 7 skills | 2026-04-25 |
| `obsidian-skills` | https://github.com/kepano/obsidian-skills.git | skills | 5 skills | 2026-04-25 |
| `n8n-mcp` | https://github.com/czlonkowski/n8n-mcp.git | agents | 8 agents | 2026-04-25 |
| `get-shit-done` | https://github.com/gsd-build/get-shit-done.git | agents | 33 agents | 2026-04-25 |
| `awesome-claude-code` | https://github.com/hesreallyhim/awesome-claude-code.git | commands | 1 command | 2026-04-25 |
| `context7` | https://github.com/upstash/context7.git | skills+agents+commands | 3 skills, 1 agent, 1 command | 2026-04-25 |
| `everything-claude-code` | https://github.com/affaan-m/everything-claude-code.git | skills | 34 skills | 2026-04-25 |
| `browser-use` | https://github.com/browser-use/browser-use.git | skills | 4 skills | 2026-04-26 |
| `marketingskills` | https://github.com/coreyhaines31/marketingskills.git | skills | 40 skills | 2026-04-26 |
| `web-asset-generator` | https://github.com/alonw0/web-asset-generator.git | skills | 1 skill (favicons + OG images) | 2026-04-26 |
| `Deep-Research-skills` | https://github.com/Weizhena/Deep-Research-skills.git | skills+agents | 24 skills, 7 agents (slug `-eep--esearch-skills` due to fetcher bug) | 2026-04-26 |
| `andrej-karpathy-skills` | https://github.com/forrestchang/andrej-karpathy-skills.git | skills | 1 skill (karpathy-guidelines: anti-overcomplication, surgical changes, surface assumptions) | 2026-04-28 |
| `gstack` | https://github.com/garrytan/gstack.git | skills | 50 skills (browser dogfooding, design/eng/ceo/devex review tracks, plan-tune, ship, careful, guard, freeze/unfreeze, openclaw variants — see §15 for full list). gstack uses a **flat layout** (skills at repo root); fetch script handles this since 2026-05-02 + a 5MB-per-file cap and a `test/`/`tests/`/`node_modules/`/`dist/`/`build/` prune so test fixtures don't bloat the vendored copy. | 2026-05-01 |

> This table should be updated alongside `scripts/fetch-github-repo.sh` runs. Keep in sync with `.claude/github-repos.json`.

---

## 19. Repository Architecture — Domains, Agents & Branch Strategy

### Project
- **Name:** Arshad.AI
- **Type:** Personal AI Operating System
- **Client / Owner:** Arshad

### Root Branches

| Branch | Purpose |
|---|---|
| `main` | Production-ready code only. Never commit directly. |
| `develop` | Integration and testing. All domain branches merge here before `main`. |

### Merge Path

```
agent/<domain>/<agent-name>
        ↓
  domain/<domain>
        ↓
      develop
        ↓
       main
```

### Branch Naming Conventions

| Type | Pattern | Example |
|---|---|---|
| Domain branch | `domain/<domain>` | `domain/calendar` |
| Agent branch | `agent/<domain>/<agent>` | `agent/calendar/event-creator` |
| Feature branch | `feat/<domain>/<short-desc>` | `feat/email/thread-summary` |
| Fix branch | `fix/<domain>/<short-desc>` | `fix/github/pr-diff-parser` |
| Release branch | `release/v<semver>` | `release/v1.0.0` |
| Hotfix branch | `hotfix/<short-desc>` | `hotfix/auth-token-refresh` |

---

### Business Domains (6)

| Domain | Slug | Purpose |
|---|---|---|
| Calendar | `calendar` | Google Calendar integration — events, scheduling, meeting suggestions |
| Email | `email` | Gmail integration — search, drafting, labelling, summarisation |
| GitHub | `github` | GitHub integration — issues, PRs, code review, repo monitoring |
| AI Core | `ai-core` | Claude AI orchestration — tool dispatch, context, streaming |
| Data Pipeline | `data-pipeline` | Airflow ETL — ingest Calendar, Gmail, GitHub into Postgres |
| Infrastructure | `infrastructure` | API gateway, auth, cache, health monitoring |

---

### Agents (24 total — 4 per domain)

#### calendar domain
| Agent | Branch | Purpose |
|---|---|---|
| `event-creator` | `agent/calendar/event-creator` | Creates Calendar events from natural language |
| `event-updater` | `agent/calendar/event-updater` | Updates, reschedules, or cancels events |
| `meeting-suggester` | `agent/calendar/meeting-suggester` | Analyses availability and suggests meeting slots |
| `schedule-analyzer` | `agent/calendar/schedule-analyzer` | Summarises upcoming schedule and flags conflicts |

#### email domain
| Agent | Branch | Purpose |
|---|---|---|
| `email-searcher` | `agent/email/email-searcher` | Searches Gmail threads by query, date, sender, label |
| `email-drafter` | `agent/email/email-drafter` | Composes and saves email drafts from user intent |
| `email-labeler` | `agent/email/email-labeler` | Applies, removes, or creates Gmail labels |
| `email-summarizer` | `agent/email/email-summarizer` | Condenses long threads into concise action points |

#### github domain
| Agent | Branch | Purpose |
|---|---|---|
| `issue-manager` | `agent/github/issue-manager` | Creates, updates, and triages GitHub issues |
| `pr-reviewer` | `agent/github/pr-reviewer` | Summarises PR diffs and generates code review output |
| `code-summarizer` | `agent/github/code-summarizer` | Plain-English summaries of commits and code changes |
| `repo-monitor` | `agent/github/repo-monitor` | Watches repo events and alerts Arshad |

#### ai-core domain
| Agent | Branch | Purpose |
|---|---|---|
| `chat-orchestrator` | `agent/ai-core/chat-orchestrator` | Routes user messages to domain agents via API gateway |
| `tool-dispatcher` | `agent/ai-core/tool-dispatcher` | Resolves and invokes Claude tool calls |
| `context-manager` | `agent/ai-core/context-manager` | Manages conversation history and context compression |
| `response-streamer` | `agent/ai-core/response-streamer` | Handles SSE streaming of Claude responses to frontend |
| `council-chairman` | (in-process, no branch) | Multi-model LLM panel: 3 Claude models answer in parallel, anonymously rank each other, chairman synthesises. Wired to `general` chat intent + REST `POST /api/v1/agents/ai_core/council_chairman/run`. |

#### data-pipeline domain
| Agent | Branch | Purpose |
|---|---|---|
| `calendar-ingestor` | `agent/data-pipeline/calendar-ingestor` | Airflow DAG: pulls Calendar events into Postgres daily |
| `email-ingestor` | `agent/data-pipeline/email-ingestor` | Airflow DAG: pulls Gmail threads into Postgres daily |
| `github-ingestor` | `agent/data-pipeline/github-ingestor` | Airflow DAG: pulls GitHub activity into Postgres daily |
| `analytics-processor` | `agent/data-pipeline/analytics-processor` | Aggregates ingested data into summary tables |

#### infrastructure domain
| Agent | Branch | Purpose |
|---|---|---|
| `api-gateway` | `agent/infrastructure/api-gateway` | Central routing, auth enforcement, rate limiting |
| `auth-manager` | `agent/infrastructure/auth-manager` | OAuth2 flows for Google and GitHub; token refresh |
| `cache-manager` | `agent/infrastructure/cache-manager` | Redis-backed cache for tool responses and sessions |
| `health-monitor` | `agent/infrastructure/health-monitor` | Polls all services; surfaces health to dashboard |

---

### Core Infrastructure

```
infrastructure/
├── api-gateway/    ← All inter-agent traffic passes here. No direct agent-to-agent calls.
├── message-bus/    ← Async event bus for domain notifications
└── monitoring/     ← Health checks, metrics, alerting

shared/
├── auth/           ← OAuth2 helpers, token storage, dependency injectors
├── models/         ← Shared Pydantic / SQLAlchemy models
├── utils/          ← Logging, pagination, error formatting
└── types/          ← TypeScript types shared across frontend apps
```

### Folder Layout (per domain)

```
domains/<domain>/
├── README.md
├── agents/
│   └── <agent-name>/
│       ├── src/        ← implementation code
│       ├── tests/      ← unit + integration tests
│       ├── config/     ← config.yaml, env templates
│       └── README.md
└── applications/
    ├── src/            ← React components / FastAPI routes
    ├── tests/
    ├── config/
    └── README.md
```

---

### Agent Communication Rules

1. **API gateway only** — no agent may call another agent directly. All traffic goes through `infrastructure/api-gateway`.
2. **Isolated branches** — all code changes for an agent stay on its own `agent/<domain>/<name>` branch. Never commit agent logic to `develop` or `main` directly.
3. **Standard internal interface** — every agent exposes `POST /api/v1/<domain>/<agent>/<action>`.
4. **Async events** — domain-level notifications (e.g. "email received") travel via the message bus, not direct HTTP calls.
5. **No shared mutable state** — agents do not share in-memory state. Shared state lives in Postgres or Redis only.


---

## 20. Quality Gate — Auto-Trigger Rules (PERMANENT)

> These rules are ALWAYS active. They override any default behaviour.
> Read them at the start of every session.

### Target Branch (PERMANENT)

**The merge target for "Merge to Main" is `claude/ai-personal-assistant-main`** — NOT `main`.
- Source: whatever branch is currently active (e.g. `claude/dev-branch-setup-6RgtJ`)
- Target: `claude/ai-personal-assistant-main`
- Method: PR-gated merge (never direct push)

This applies to every "Merge to Main" trigger below.

### Trigger 1 — PR Creation / Review Request

**Whenever the user says any of the following (exact or near-match):**
- "create PR", "open PR", "make a PR", "raise a PR"
- "PR to main", "pull request to main", "pull request"
- "commit to main", "push to main"
- `/gate`, `/pr-review`

→ **Immediately run the full quality gate** (`/gate` protocol in `.claude/commands/gate.md`):
1. Resolve open PR (base = `claude/ai-personal-assistant-main`, head = current active branch) or create one
2. Launch all 6 agents in parallel (code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer)
3. Compile the master gate report
4. **Post the full report as a comment on the GitHub PR**
5. Present PASS / WARN / FAIL verdict to user
6. If PASS or WARN → prompt: *"Say 'Merge to Main' to merge"*
7. If FAIL → list blockers and stop. Do NOT merge.

---

### Trigger 2 — "Merge to Main"

**Whenever the user says "Merge to Main"** (case-insensitive), execute this loop:

> **Source branch is dynamic.** This trigger works from ANY branch except the merge target itself. In each step below, "the current branch" means whatever `git branch --show-current` returns. Capture it once at the top:
>
> ```bash
> CURRENT_BRANCH=$(git branch --show-current)
> ```

**Step 0 — Squash-divergence repair (mandatory).**
Squash-merging to main creates a divergent history: the source branch keeps its individual commits, main gets a single squash commit. On the next push to the source branch, the auto-pr workflow's merge call returns **HTTP 405 "Pull Request has merge conflicts"** because git's 3-way merge can't reconcile the squash with the original individual commits.

**Always check before Step 1:**
```bash
git fetch origin
if ! git merge-base --is-ancestor origin/claude/ai-personal-assistant-main HEAD; then
  git merge origin/claude/ai-personal-assistant-main --strategy=ours \
    -m "merge: keep ${CURRENT_BRANCH} aligned with main (squash-divergence repair)"
fi
```
`--strategy=ours` adds main as an ancestor of the current branch without changing any file. With main in the source branch's history, the next squash-merge has a clean diff to apply.

**Symptom if you skip this step:** the workflow's `Auto-merge result` PR comment will show:
```
HTTP 405
"message": "Pull Request has merge conflicts"
```
That message is unambiguous — when you see it, run Step 0 manually and re-trigger.

**Step 1 — Run `/gate` (mandatory, no skipping, no shortcuts).**
Spawn **all 6 agents** (`code-reviewer`, `security-auditor`, `debugger`, `test-writer`, `refactorer`, `doc-writer`) on the diff between the **current branch** and `claude/ai-personal-assistant-main`:
```bash
git diff origin/claude/ai-personal-assistant-main..HEAD
```
Compile the master report from their actual outputs.

**No focused-verification mode. No "trivial diff" exception. No "I authored this so reviewing is pointless" rationalisation.** Even one-line changes go through the 6-agent panel — that is the whole point of the gate. The user explicitly mandated this; do not relitigate.

**Step 2 — If the gate has any Critical finding or FAIL gate → auto-fix loop.**
- For each Critical finding, apply the smallest fix that resolves it.
- Commit each fix atomically (one commit per finding).
- Push to **`${CURRENT_BRANCH}`** (the source branch you're working in).
- Re-run `/gate`.
- Repeat up to **3 iterations**. If criticals still remain, stop and present what's left to the user — do NOT proceed to merge.

WARN-level findings are **not** auto-fixed. They go into the PR body as a checklist; the user decides whether to address before merging.

**Step 3 — Write the gate report to `tasks/last-gate-report.md`.**
The full master gate report (the same markdown that would otherwise be a PR comment) MUST be written to `tasks/last-gate-report.md` and committed in the same push as the final fixes. The `auto-pr.yml` workflow reads this file and uses its contents as the PR description, so the gate report is **embedded directly in the PR body** — not posted as a comment.

If no fixes were needed, still write `tasks/last-gate-report.md` so the PR description reflects the gate verdict.

**Step 4 — Push to the current branch.**
- Push the final state: `git push origin "${CURRENT_BRANCH}"`.
- The `.github/workflows/auto-pr.yml` workflow opens (or updates) a PR from `${CURRENT_BRANCH}` → `claude/ai-personal-assistant-main` and uses `tasks/last-gate-report.md` as the body.
- Report the PR URL and the gate verdict to the user. Example:
  > "✅ Gate passed. PR auto-opened and auto-merged: <URL>."

**Step 5 — Auto-merge happens in the workflow.**
The `auto-pr.yml` workflow squash-merges the PR automatically **only when the push contains a fresh `tasks/last-gate-report.md` whose verdict is not BLOCKED**. That file is the auto-merge signal: its presence in the HEAD commit says "this push was gated and is safe to merge." Pushes without a fresh gate report only update the PR — they never auto-merge.

Failure modes:
- Gate verdict is **BLOCKED** → workflow opens/updates the PR and stops; manual review and fix required.
- The push is intermediate (no fresh gate report) → workflow opens/updates the PR and stops; the next "Merge to Main" run finishes it.

Claude itself never invokes the merge directly. The auto-merge is a property of the workflow + the gate-report contract, which means:
- The user can still inspect the PR before it merges if they're fast (workflow takes ~10 s).
- Disabling auto-merge is a one-line workflow change (drop the `Auto-merge` step).
- An accidental push from outside Claude Code (manual edit, dependabot, etc.) cannot auto-merge — it lacks the gate-report signal.

**This phrase ("Merge to Main") is the ONLY trigger for the gate-and-merge flow. The merge target is always `claude/ai-personal-assistant-main`. Never push directly to `main`.**

---

### Gate Agents (all 6 must pass)

| Agent | File | What it checks |
|---|---|---|
| `code-reviewer` | `.claude/agents/code-reviewer.md` | Bugs, logic errors, performance |
| `security-auditor` | `.claude/agents/security-auditor.md` | OWASP Top 10, secrets, injection |
| `debugger` | `.claude/agents/debugger.md` | Unhandled errors, runtime failures |
| `test-writer` | `.claude/agents/test-writer.md` | Coverage < 70% = FAIL |
| `refactorer` | `.claude/agents/refactorer.md` | Complexity, duplication |
| `doc-writer` | `.claude/agents/doc-writer.md` | Undocumented public APIs |

### Gate Verdicts

| Verdict | Condition | Merge allowed? |
|---|---|---|
| ✅ PASS | All 6 agents: no FAIL, no Critical | Yes — on "Merge to Main" |
| ⚠️ WARN | Some WARN, zero FAIL, zero Critical | Yes — on "Merge to Main" |
| ❌ BLOCKED | Any FAIL gate OR any Critical issue | No — fix first |

**Security exception:** any security finding (even WARN-level) automatically upgrades to FAIL and blocks the merge.

### Gate Report

The full report is **always posted to the GitHub PR as a comment**, regardless of outcome.
Format: see `.claude/commands/gate.md § Step 2`.
The report includes: agent-by-agent results table, detailed findings per agent, and a prioritised action-item checklist.


---

## 21. AI Dev Team Auto-Trigger (PERMANENT)

**Whenever the user prompt is a feature requirement** — phrased as 'build / add / implement / create / develop X', or describes new functionality with multi-step nature — automatically invoke the `/dev-team` slash command.

### Cost model

The dev-team is a Claude-Code-native agent set. Each role lives at `.claude/agents/dev-team/<role>.md` and runs as a `Task()` subagent in this session. **No `ANTHROPIC_API_KEY` consumption.** Same billing model as `code-reviewer`, `debugger`, etc.

### Trigger detection (heuristics — done in your own context)

Treat the prompt as a feature requirement if:
- Starts with build / add / implement / create / develop / design / make
- Length ≥ 6 words
- Not in the do-NOT-trigger list below

User escape hatches:
- Prefix `@build` → force trigger
- Prefix `@chat` → force skip (always treat as conversation)

### Do NOT trigger on

- Diagnostic prompts ("why is X failing", "investigate Y", "the deploy is broken")
- Questions ("how does X work", "what are my options")
- Single-line edits / typos
- Conversational chatter ("yes", "ok", "continue", "stop", "cancel")
- Ambiguous one-word prompts
- Explicit `@chat` prefix

### Flow when triggered

1. **Confirm interpretation**. Reflect back: requirement summary, the next `FEAT-NNN`, ask "Confirm or correct?"
2. **On confirmation**, invoke the orchestrator: follow the recipe in `.claude/commands/dev-team.md`. Each agent stage is a `Task(subagent_type="<role>", ...)` call where `<role>` ∈ `business-analyst | enterprise-architect | solution-architect | developer | process-organiser | test-script-writer | tester | bug-fixer`.
3. **Stream stage completions** to the user — one short line per agent (`▸ BA: 4 reqs, domain=Workspace ✅`).
4. **On completion**, report: Feature ID, generated branch name, bug-fix iterations used, EA post-build decision, paths to each artifact.
5. **On halt**, report the halt reason and the last successful stage.

### Pipeline guarantees

- 9 stages: BA → EA-pre → SA → Dev → PO → TSW → Tester → [BugFixer ↔ Tester loop, cap 5] → EA-post (always runs, even after cap)
- Path denylist enforced before any Write (`backend/src/main.py`, `backend/src/auth/*`, `backend/alembic/env.py`, `.github/workflows/*`, `render.yaml`, `vercel.json`, `Dockerfile*`, `CLAUDE.md`, `tasks/process-hierarchy.md`, `tasks/last-gate-report.md`, `tasks/lessons.md`, `tasks/.feature-counter`, any `..` paths)
- Live writes go to a fresh `dev-team/<feat-id>-<slug>` branch — never `develop-AION` or `main` directly
- `tasks/process-hierarchy.md` updated via Edit (or atomic Write+mv) — never recreated
- Every agent output written to `tasks/agent-outputs/<role>/<FEAT-NNN>_<ts>.json`
- One row appended to `tasks/pipeline-runs.md` per invocation

### Cancellation

If the user says "stop" / "cancel" between stages, halt the pipeline at the last completed stage. Partial artifacts persist; the run logs as `halted`.

---

## 22. Orchestrator Agent (PERMANENT)

`/dev-team` runs a fixed 9-stage feature pipeline. Everything else multi-agent goes through the **Orchestrator** at `.claude/agents/orchestrator.md` (Opus-tier planner + executor).

### When to use

| Use | Why |
|---|---|
| `/dev-team <feature>` | New feature — deterministic 9-stage pipeline |
| `/orchestrate <objective>` | Audit / refactor / multi-agent investigation / hybrid plan |
| `Task(subagent_type="orchestrator", ...)` | Direct invocation from another agent / slash command |

### Lifecycle

Plan → Dispatch → (Reflect / Replan) → Quality Gate → Report. Each run gets a fresh `tasks/orchestrator-runs/ORCH-NNN/` directory containing `plan.json`, `progress.md`, `artifacts/`, `gate-report.md`, `final.md`.

### Universe

The orchestrator dispatches ONLY the 15 project + dev-team agents (Option B):
`planner, code-reviewer, debugger, doc-writer, refactorer, security-auditor, test-writer, business-analyst, enterprise-architect, solution-architect, developer, process-organiser, test-script-writer, tester, bug-fixer`.

It does NOT dispatch vendored agents, backend Python agents, or harness built-ins. If the objective needs those, that's an orchestrator-out-of-scope signal — surface to the user.

### Caps

- 25 `Task()` calls per run
- 3 replans per run
- 30 min wall clock (soft)
- Always runs the 6-agent gate at the end (Option 3A)
- Always interactive on ambiguous prompts (Option 2A — uses `AskUserQuestion`)

### Persistence

`tasks/orchestrator-runs/` is committed to git. Every run is auditable from disk alone. Counter at `tasks/.orchestrator-counter`.

### Gate-report contract

Each run writes BOTH `tasks/orchestrator-runs/<RUN-ID>/gate-report.md` (run-local) AND `tasks/last-gate-report.md` (the auto-pr workflow's merge signal per §20). A non-BLOCKED gate verdict from an orchestrator run can satisfy "Merge to Main" without re-running `/gate`.

