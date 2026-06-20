# Arshad.AI — Permanent Project Memory

> This file is the single source of truth for Claude working on this project.
> Read it fully at the start of every session before touching any code.

## 🚨 DEVELOPMENT STRATEGY — READ THIS FIRST, EVERY SESSION

> **This is the non-negotiable rule for ALL feature development on this project.**
> Every new feature, every non-trivial change, goes through the dev-team pipeline.
> No exceptions. No shortcuts. No writing code directly.

### Auto-Trigger — No command needed

**Arshad will NEVER type `/dev-team`. He gives prompts directly.**

**You must analyse every prompt and decide: is this a development request?**
If yes → immediately invoke the dev-team orchestrator with his prompt. Do NOT ask for confirmation. Do NOT write code yourself. Just dispatch.

```
Task(subagent_type="dev-team-orchestrator", prompt=<arshad's exact prompt>)
```

### Trigger Detection — Read the intent, not the words

Route to dev-team orchestrator when the prompt contains ANY of these intents:

| Intent | Example prompts |
|---|---|
| Build something new | "Add a dark mode", "Create a settings page", "I want users to be able to…" |
| Implement a feature | "Implement real-time notifications", "Build the chat interface" |
| Add functionality | "Add search to the sidebar", "Let me filter by date" |
| Create an endpoint | "I need an API for…", "Expose a route that…" |
| New UI / component | "Design a dashboard widget", "Build a modal for…" |
| Schema / data change | "Store user preferences", "Track conversation history" |
| Integration | "Connect to Google Calendar", "Add GitHub webhook support" |
| Refactor (multi-file) | "Clean up the auth flow", "Restructure the agent system" |

### Do NOT route to dev-team — handle directly

| Situation | Handle as |
|---|---|
| Single-line bug fix | Direct edit |
| Config / env var change | Direct edit |
| Rename / move file | Direct edit |
| Typo / comment fix | Direct edit |
| Explanation / question | Answer directly |
| Fixing a broken test | Direct debugger agent |
| Deployment issue | Direct fix |

**When in doubt → route to dev-team.**

### The 28-Agent Pipeline (30 Steps)

The orchestrator runs these agents in strict sequence. Every agent output feeds the next.

| Stage | Agent | Model | What It Does |
|---|---|---|---|
| 0.5 | `code-explorer` | Sonnet | Maps codebase patterns, module boundaries, naming idioms — context fed to all subsequent agents |
| 1 | `business-analyst` | Haiku | Extracts requirements → RTM + BPDD |
| 2 | `enterprise-architect` *(pre)* | Sonnet | Enterprise architecture review — rejects bad ideas before any code |
| 2.5 | `ai-engineer` | **Opus** | Tech lead — challenges decisions, flags scaling risks, sets architecture direction SA must follow |
| 3 | `solution-architect` | Sonnet | Produces Solution Design Document (SDD) constrained by Tech Lead |
| 3.1 | `architecture-critic` | **Opus** | Adversarially reviews the SDD — flags over-engineering, coupling risks, convention deviations; blocking findings halt the pipeline |
| 3.3 | `system-engineer` | **Opus** | Designs system architecture, component structure, data flow, DB schema, caching strategy |
| 3.5 | `engineer` | Sonnet | Builds production-ready MVP from SDD + system design |
| 4 | `developer` | Sonnet | Generates complete feature code |
| 4.15 | `database-specialist` | Sonnet | Deep SQL/ORM/migration audit — N+1, missing indexes, unsafe queries, Alembic correctness |
| 4.16 | `python-specialist` | Sonnet | Python/FastAPI audit — async correctness, Pydantic v2, dependency injection, type annotations |
| 4.2 | `code-reviewer` | **Opus** | Project-conventions review — checks all code against CLAUDE.md rules (api.md, database.md, frontend.md) |
| 4.3 | `frontend-engineer` | Sonnet | Production-grade UI with bold aesthetic direction (frontend-design skill) — all 4 states, accessible, responsive, reusable |
| 4.4 | `type-design-analyzer` | Sonnet | TypeScript type system audit — weak types, missing invariant encoding, illegal-state prevention |
| 4.5 | `senior-engineer` | **Opus** | Code quality audit — finds N+1, bad patterns, scalability risks. No functionality changes. |
| 4.6 | `software-architect` | **Opus** | Architecture restructuring — separates concerns, reduces coupling, increases modularity |
| 4.7 | `silent-failure-hunter` | Sonnet | Error handling audit — swallowed exceptions, HTTP 200 masking errors, missing propagation |
| 4.8 | `code-simplifier` | **Opus** | Code clarity refinement — eliminates unnecessary abstraction, over-engineering, verbose constructs |
| 5 | `process-organiser` | Haiku | Logs feature in process hierarchy |
| 5.9 | `test-architect` | Sonnet | Designs test architecture — unit vs integration boundaries, mock strategy, coverage plan |
| 6 | `test-script-writer` | Sonnet | Writes test scripts following Test Architect's plan |
| 6.1 | `pr-test-analyzer` | Sonnet | Test quality review — coverage of happy/error/edge paths, negative tests, behaviour vs implementation |
| 7 | `tester` | Sonnet | Executes tests, reports defects |
| 8 | `bug-fixer` ↔ `tester` | Sonnet | Fix + re-test loop (max 5 iterations) |
| 8.5 | `debugger` | **Opus** | Root cause analysis — production outage mode, 3 levels deep |
| 8.6 | `performance-optimisation-engineer` | Sonnet | Eliminates bottlenecks — N+1, missing indexes, async gaps, memory leaks |
| 8.7 | `security-auditor` | **Opus** | OWASP Top 10 — attack scenarios, secure implementation fixes |
| 8.8 | `devops-engineer` | Sonnet | Deployment architecture, monitoring, scaling, production checklist |
| 8.9 | `production-validator` | Sonnet | Final production-readiness check — no stubs, no TODOs, all endpoints functional, no debug code |
| 9 | `enterprise-architect` *(post)* | Sonnet | Final architectural verdict — always runs |

**Orchestrator model: `claude-fable-5`** — it controls all 28 agents.

### Model Tiers

| Tier | Agents | Purpose |
|---|---|---|
| **Opus** (10 agents) | ai-engineer, architecture-critic, system-engineer, code-reviewer, senior-engineer, software-architect, code-simplifier, debugger, security-auditor | Deep reasoning — architectural decisions, audits, root cause, security |
| **Sonnet** (16 agents) | code-explorer, engineer, developer, database-specialist, python-specialist, frontend-engineer, type-design-analyzer, silent-failure-hunter, perf-opt, devops, production-validator, solution-architect, enterprise-architect, test-architect, test-writer, tester, bug-fixer, pr-test-analyzer | Execution — code generation, testing, optimization |
| **Haiku** (2 agents) | business-analyst, process-organiser | Simple extraction and formatting |

### Three Invariants (never break these)

1. **Code accumulates forward** — one `code` object from Step 3.5 onward; each agent improves it in-place
2. **Steps 8.5 → 9 always run** — even if the bug-fix loop exhausted 5 iterations; code is always hardened, secured, and signed off
3. **Path denylist is checked after every code-generating step** — forbidden file path = immediate pipeline halt

### Agent files location

All agent definitions live in `.claude/agents/dev-team/`:
- `orchestrator.md` — the controlling agent
- One `.md` file per specialist agent listed above

---

## Auto-Trigger Rule — GitHub URLs

**Whenever a GitHub URL (github.com/...) appears in a user prompt, automatically run `/fetch-github-repo <url>` on it.**
No need for the user to type the command — detect the URL and trigger the fetch procedure immediately.

## Model Strategy (Read First)

| Phase | Model | When |
|---|---|---|
| **Planning** | `claude-opus-4-7` | Any task with 3+ steps, architectural decisions, ambiguous requirements |
| **Execution** | `claude-sonnet-4-6` | All regular prompts, all agent runs, all code writing |

**Rule:** Before writing a single line of code on any non-trivial task, invoke the `planner` agent (Opus) via `/plan <description>`. Opus thinks, Sonnet builds.

**Never skip planning for:**
- New features touching multiple files or layers
- New dependencies or services
- Database schema changes
- Any task where the approach is unclear

**Skip planning for:**
- Single-line fixes
- Config value changes
- Renames
- Adding a single test

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

### Adding a new Claude tool *(planned — module not yet created)*
1. Define the tool schema in `backend/src/tools/definitions.py`
2. Implement the handler in `backend/src/tools/handlers.py`
3. Register it in the `TOOL_HANDLERS` map
4. All Claude calls go through `backend/src/services/ai.py` — never inline

> The `backend/src/tools/` and `backend/src/services/` packages do not yet exist;
> create them when the first tool is implemented. The pattern above is the target
> design, not the current state of the codebase.

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
│   ├── everything-claude-code/ ← affaan-m — 34 skills
│   └── ruflo/                 ← ruvnet — 134 swarm/agent skills
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
| `ruflo` | https://github.com/ruvnet/ruflo.git | skills+agents | 134 skills, 107 agents | 2026-06-07 |
| `agent-skills` | https://github.com/addyosmani/agent-skills | skills+agents+commands+hooks | 24 skills, 4 agents, 8 commands, 4 hooks | 2026-06-13 |
| `agent-browser` | https://github.com/vercel-labs/agent-browser | skills | 7 skills (core + 6 specialized) | 2026-06-20 |

> This table is updated automatically by `scripts/fetch-github-repo.sh` when a new repo is integrated.

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

### Gate Agents (all 8 must pass)

| Agent | File | What it checks |
|---|---|---|
| `code-reviewer` | `.claude/agents/code-reviewer.md` | Bugs, logic errors, performance |
| `security-auditor` | `.claude/agents/security-auditor.md` | OWASP Top 10, secrets, injection |
| `debugger` | `.claude/agents/debugger.md` | Unhandled errors, runtime failures |
| `test-writer` | `.claude/agents/test-writer.md` | Coverage < 70% = FAIL |
| `refactorer` | `.claude/agents/refactorer.md` | Complexity, duplication |
| `doc-writer` | `.claude/agents/doc-writer.md` | Undocumented public APIs |
| `silent-failure-hunter` | `.claude/agents/claude-plugins-official/silent-failure-hunter.md` | Swallowed exceptions, HTTP 200 masking errors |
| `pr-test-analyzer` | `.claude/agents/claude-plugins-official/pr-test-analyzer.md` | Test quality, negative coverage, behaviour vs implementation |

### Gate Verdicts

| Verdict | Condition | Merge allowed? |
|---|---|---|
| ✅ PASS | All 8 agents: no FAIL, no Critical | Yes — on "Merge to Main" |
| ⚠️ WARN | Some WARN, zero FAIL, zero Critical | Yes — on "Merge to Main" |
| ❌ BLOCKED | Any FAIL gate OR any Critical issue | No — fix first |

**Security exception:** any security finding (even WARN-level) automatically upgrades to FAIL and blocks the merge.

### Gate Report

The full report is **always posted to the GitHub PR as a comment**, regardless of outcome.
Format: see `.claude/commands/gate.md § Step 2`.
The report includes: agent-by-agent results table, detailed findings per agent, and a prioritised action-item checklist.

---

## 21. Agent Auto-Registration — AI Ecosystem Sync (PERMANENT)

> This rule is ALWAYS active. Every agent installation triggers it — no exceptions.

**Trigger:** Immediately after any agent `.md` file is added to `.claude/agents/` (or any subdirectory), whether via `/fetch-github-repo`, manual file creation, or the weekly skill sync.

### What to extract from the `.md` file

| Field | Source |
|---|---|
| `agent_name` | Filename without `.md` (e.g. `code-reviewer.md` → `code-reviewer`) |
| `display_name` | First `# Heading` in the file; fallback: title-case of `agent_name` |
| `purpose` | First non-empty, non-heading paragraph (strip markdown, truncate to 250 chars) |
| `model` | Scan content for `opus` → `claude-opus-4-8`; `haiku` → `claude-haiku-4-5-20251001`; default `claude-sonnet-4-6` |
| `category` | `development_team` if in `.claude/agents/dev-team/`; else `other` |
| `pipeline_stage` | `null` for all non-dev-team agents |

### Section mapping on the AI Ecosystem page

| `category` value | Section shown |
|---|---|
| `development_team` | "Development Team" (sorted by pipeline_stage) |
| `other` | "Other Agents" (sorted by display_name) |

### How to register (two methods — use whichever applies)

**Method A — CLI script (when Docker is running):**
```bash
# Auto-parse from the .md file:
docker compose exec backend python -m scripts.register_agent \
  --file /app/.claude/agents/<slug>/<filename>.md \
  --category other

# Or pass fields explicitly:
docker compose exec backend python -m scripts.register_agent \
  --name <agent_name> \
  --display "<Display Name>" \
  --purpose "<One-sentence purpose>" \
  --model claude-sonnet-4-6 \
  --category other
```

**Method B — API endpoint (when backend is running locally):**
```bash
curl -s -X POST http://localhost:8000/api/v1/ai-ecosystem/agents/register \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "<slug>",
    "display_name": "<Display Name>",
    "purpose": "<purpose>",
    "model": "claude-sonnet-4-6",
    "category": "other"
  }'
```

### When this rule fires

1. **After `/fetch-github-repo`** — register every new agent `.md` file that was copied into `.claude/agents/`.
2. **After any manual agent file creation** — register the new file immediately.
3. **After the weekly skill sync** (`session-start.sh`) — if any agent files changed, re-register them (Method A or B).
4. **After the dev-team pipeline adds a new dev-team agent** — register it with `category=development_team` and the correct `pipeline_stage`.

### Idempotency

The endpoint and script both **upsert** — calling them on an already-registered agent updates its metadata. Safe to re-run at any time.

---

## 22. Autonomous Backlog System (PERMANENT)

> Keep incomplete work alive across session limits.
> This rule is ALWAYS active — it fires at the end of every session.

### How it works

1. **Backlog file:** `tasks/backlog.md` — structured list of pending tasks.
2. **Executor script:** `scripts/backlog_run.py` — calls Claude claude-sonnet-4-6 via the Anthropic API with file-manipulation tools to execute one task per run.
3. **Scheduled workflow:** `.github/workflows/autonomous-backlog.yml` — fires every 2 hours, picks the next autonomous pending task, commits changes directly to `claude/ai-personal-assistant-CcA11` (the active dev branch), and opens/updates a rolling PR from that branch → `claude/ai-personal-assistant-main`. All autonomous commits accumulate on the dev branch so they are visible to Claude when a session resumes.
4. **Session-end hook:** `/session-end` (step 3b) queues every incomplete item before closing out.

### Adding tasks to the backlog

```bash
# Autonomous (bot can execute without asking you):
python scripts/backlog_add.py \
  --title "Add error state to AiEcosystem page" \
  --description "When useFetch returns an error, show a red banner instead of silently keeping stale data." \
  --context "frontend/src/pages/AiEcosystem/AiEcosystem.tsx" \
  --autonomous yes

# Requires human input (bot skips, Arshad decides):
python scripts/backlog_add.py \
  --title "Choose rate-limiting strategy" \
  --description "Decide between token-bucket and sliding-window for /api/v1/chat." \
  --autonomous no
```

### Autonomy filter — the hard rule

**NEVER auto-execute a task that requires a human decision.**

A task `requires_human: yes` means: it involves architectural decisions, user-facing behaviour changes that need approval, security-sensitive changes, or anything Arshad needs to sign off on.

When in doubt: `--autonomous no`. The task stays in the backlog, visible on the next session.

### Task lifecycle

```
pending → (bot picks up) → in_progress → done
                        ↘ blocked (BLOCKED: reason in summary)
```

Blocked tasks stay `pending` in the file — the bot logs a warning and skips to the next task. Arshad fixes the description or sets `requires_human: yes` when he returns.

### When this rule fires

- **At every `/session-end`** — step 3b queues all incomplete session work.
- **Whenever Claude detects a session limit approaching** — proactively queue the current in-flight task with full context before the session expires.
- **After any dev-team pipeline run** — if the pipeline left TODOs or deferred items, queue them.

### Files involved

| File | Purpose |
|---|---|
| `tasks/backlog.md` | The backlog. Human-readable. Committed to the repo. |
| `scripts/backlog_add.py` | CLI to append tasks |
| `scripts/backlog_run.py` | Executor — called by the workflow |
| `.github/workflows/autonomous-backlog.yml` | Scheduled workflow (every 2 h) |
| `.claude/commands/session-end.md` | Step 3b queues incomplete tasks |

