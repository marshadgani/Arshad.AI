# Backend Phase A — Mock-backed REST API

**Date:** 2026-04-25
**Phase:** A of 6 (see CLAUDE.md §3 + roadmap below)
**Goal:** Turn the React dashboard from "imports from `mockData.ts`" to "fetches from a real Postgres-backed FastAPI". Dashboard renders identically; data lives in the DB.

---

## 1. What's in scope (Phase A only)

| In | Out |
|---|---|
| Postgres schema for every shape currently in `frontend/src/data/mockData.ts` | OAuth, auth middleware (Phase C) |
| Alembic init + initial migration | Anthropic chat / streaming (Phase B) |
| SQLAlchemy 2.x async models | Real Google / GitHub data (Phase D) |
| Pydantic v2 response schemas | 24 domain agents + API gateway (Phase E) |
| Read-only `GET /api/v1/dashboard/*` and `/api/v1/domains/*` endpoints | Airflow ingestion DAGs (Phase F) |
| Seed script that loads `mockData.ts` content into Postgres | Tests (separate test-infra phase) |
| `useFetch<T>` hook + replace every mock import | POST/PATCH/DELETE — Phase A is read-only |
| `docker compose up --build` end-to-end | New env vars (DATABASE_URL / REDIS_URL already exist) |

---

## 2. Roadmap context (so Phase A has a place to grow into)

```
A. Mock-backed REST   ← this session (foundation)
B. Anthropic chat (SSE streaming, conversation history)
C. OAuth (Google + GitHub) + bearer auth
D. Real integrations via Claude tool-calling
E. 24 domain agents + API gateway
F. Airflow ingestion DAGs
```

Phase A defines the data contract that B–F all reuse. Phase B replaces only the chat-related rows; Phase D replaces seeded values with live API calls. The schema doesn't have to predict everything — it just has to mirror the frontend's current shape.

---

## 3. Database schema

20 tables. Naming follows `.claude/rules/database.md`: snake_case plural, UUID PK by default, but for entities the frontend already keys by string ID (e.g. `t1`, `e1`, `d1`) the PK is a `String` matching that ID — preserving stable keys end-to-end.

### Core dashboard (`backend/src/models/dashboard.py`)

| Table | Cols | PK | Notes |
|---|---|---|---|
| `tasks` | id, title, source, due, priority, created_at, updated_at | id (string, e.g. `t1`) | `source` is enum `Source`, `priority` is enum `p0..p3` |
| `events` | id, title, start, duration, calendar, source, created_at, updated_at | id (string) | `calendar` enum `CalendarTag`, `source` enum `Google\|Apple\|Outlook` |
| `agents_global` | id, name, domain, health, uptime, accuracy, last_action, last_run | id (string) | Cross-domain agent roster (separate from per-domain `domain_agents`) |
| `decisions` | id, title, context, source, waiting_since | id (string) | |
| `agent_activity` | id, agent, message, time | id (string) | Live-ticker rows |
| `notifications` | id, severity, title, detail, time | id (string) | `severity` enum `Severity` |
| `news_items` | id, title, source | id (string) | `source` is free-text (e.g. "Reuters"), not the same as `Source` enum |
| `knowledge_suggestions` | id (uuid), text | uuid | Auto-generated UUID since mockData has no IDs |
| `quick_actions` | id, label, hint | id (string) | |
| `health_habits` | name, value, delta | name (string) | Singleton-style: 4 rows, name is "sleep"/"steps"/"workout"/"water" |
| `daily_briefing` | id, greeting, date_label, summary | id (smallint, always 1) | True singleton (1 row enforced by check constraint) |
| `focus_now` | id, title, subtitle, context, action | id (smallint, always 1) | Singleton |
| `weather` | id, temp, condition, city | id (smallint, always 1) | Singleton |
| `commute` | id, eta, mode, dest | id (smallint, always 1) | Singleton |

### Domain catalogue (`backend/src/models/domain.py`)

| Table | Cols | PK | FK |
|---|---|---|---|
| `domains` | slug, title, emoji, tagline | slug (string) | — |
| `domain_kpis` | id (uuid), domain_slug, label, value, delta, ord | uuid | domain_slug → domains.slug |
| `domain_applications` | id, domain_slug, name, description, status | id (string, e.g. `fa1`) | domain_slug → domains.slug |
| `domain_agents` | id (uuid), domain_slug, name, description, health, uptime, accuracy, last_action, last_run | uuid | domain_slug → domains.slug |
| `domain_feed_rows` | id, domain_slug, message, time | id (string, e.g. `ff1`) | domain_slug → domains.slug |
| `nav_items` | path, label, icon, domain | path (string) | — |

**Indexes:** `ix_domain_kpis_domain_slug`, `ix_domain_applications_domain_slug`, `ix_domain_agents_domain_slug`, `ix_domain_feed_rows_domain_slug` per database rule "add an index on foreign keys".

**Enums:** Use SQLAlchemy `Enum` with native PG `CREATE TYPE ... AS ENUM` so values are validated at the DB level.

---

## 4. Pydantic schemas (`backend/src/schemas/`)

One file per model group:
- `backend/src/schemas/dashboard.py` — `TaskResponse`, `EventResponse`, etc.
- `backend/src/schemas/domain.py` — `DomainConfigResponse`, `DomainListResponse`, `NavItemResponse`

Every response schema uses `model_config = ConfigDict(from_attributes=True)` so SQLAlchemy ORM objects convert directly. No request schemas this phase (read-only).

---

## 5. REST endpoints

All under `/api/v1`. All `GET`. All return `{"data": ...}` per `.claude/rules/api.md`.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/dashboard/briefing` | `{ data: DailyBriefing }` |
| GET | `/api/v1/dashboard/focus` | `{ data: FocusBlock }` |
| GET | `/api/v1/dashboard/decisions` | `{ data: Decision[], total }` |
| GET | `/api/v1/dashboard/tasks` | `{ data: Task[], total }` |
| GET | `/api/v1/dashboard/events` | `{ data: Event[], total }` |
| GET | `/api/v1/dashboard/agent-activity` | `{ data: AgentTick[], total }` |
| GET | `/api/v1/dashboard/health-habits` | `{ data: HealthHabit[] }` (returned as object keyed by name for frontend ergonomics) |
| GET | `/api/v1/dashboard/notifications` | `{ data: Notification[], total }` |
| GET | `/api/v1/dashboard/weather` | `{ data: Weather }` |
| GET | `/api/v1/dashboard/commute` | `{ data: Commute }` |
| GET | `/api/v1/dashboard/news` | `{ data: NewsItem[], total }` |
| GET | `/api/v1/dashboard/knowledge-suggestions` | `{ data: string[] }` (just the text) |
| GET | `/api/v1/dashboard/quick-actions` | `{ data: QuickAction[], total }` |
| GET | `/api/v1/dashboard/agents` | `{ data: Agent[], total }` (cross-domain roster) |
| GET | `/api/v1/domains` | `{ data: DomainSummary[], total: 7 }` (slug + title + emoji + tagline only) |
| GET | `/api/v1/domains/{slug}` | `{ data: DomainConfig }` (full nested) — 404 if slug not found |
| GET | `/api/v1/nav` | `{ data: NavItem[] }` |

Pagination: not added in Phase A — each collection is small (≤ 7) and the rule's "default limit 20, max 100" is preserved by simply returning all rows. We'll add `?limit=&offset=` when the lists are large enough to need it.

Auth: deferred to Phase C. Routes are open within the Docker network; the frontend talks to them via Vite's `/api` proxy on localhost.

---

## 6. Seed strategy

**Decision: hand-translate `mockData.ts` to a Python literal in `backend/scripts/seed_from_mock.py`.**

- TS-side has interfaces, type narrowing, and Record types that are messy to parse in Python.
- A TS→JSON export script adds an extra build step and a Node dependency to the Python container.
- The mock data is small (24 KB) and stable. One-time hand-translation is the simplest correct path.
- Phase D will replace seeded values with real API responses; the Python literal is interim, not a long-term contract.

**Seed flow:**
1. Connect via `AsyncSessionLocal`
2. Truncate every Phase A table (idempotent re-seed)
3. Insert in dependency order: domains → kpis/applications/agents/feed → everything else
4. Run via `python -m scripts.seed_from_mock`

**Wiring into Docker:**
Add a `db-init` one-shot service in `docker-compose.yml` that:
1. Waits for postgres healthcheck
2. Runs `alembic upgrade head`
3. Runs `python -m scripts.seed_from_mock`
4. Exits

Backend service `depends_on: db-init: { condition: service_completed_successfully }`.

---

## 7. Frontend wiring

### New file: `frontend/src/hooks/useFetch.ts`
```ts
export interface UseFetchResult<T> { data: T | null; isLoading: boolean; error: Error | null; }
export function useFetch<T>(url: string): UseFetchResult<T> { /* fetch, unwrap .data, set state */ }
```
Per `.claude/rules/frontend.md`: "A hook that fetches data returns `{ data, isLoading, error }`."

### Replace pattern (one component at a time)

**Before:**
```tsx
import { tasks, events, /* … */ } from '../data/mockData';
```

**After:**
```tsx
const { data: tasks } = useFetch<Task[]>('/api/v1/dashboard/tasks');
const { data: events } = useFetch<Event[]>('/api/v1/dashboard/events');
// Each widget shows a skeleton/loader while data === null.
```

### Components touched

- `frontend/src/pages/Dashboard.tsx` (13 widgets — biggest change)
- `frontend/src/components/Sidebar.tsx` (navItems)
- `frontend/src/components/DomainPage.tsx` (already takes `domain` as a prop)
- `frontend/src/pages/PersonalFinance.tsx`, `ShopifyStore.tsx`, `StockMarket.tsx`, `HealthFitness.tsx`, `Learning.tsx`, `HomeIoT.tsx`, `Travel.tsx` — change from `<DomainPage domain={domains.finance} />` to `<DomainPage slug="finance" />` and let DomainPage fetch by slug.

### `mockData.ts` future

Keep it for now (used by tests later, and the Python seed is hand-derived from it). When Phase D replaces the seed with real integrations, `mockData.ts` can be deleted. Until then it's the source of truth for the type definitions, which the frontend hooks still import as types only:
```ts
import type { Task, Event, /* … */ } from '../data/mockData';
```

---

## 8. Vite proxy

`frontend/vite.config.ts` already proxies `/api` → `http://localhost:8000`. Confirmed; no change.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hand-translated seed drifts from `mockData.ts` | Phase D deletes the seed entirely. Until then a CI check could diff types — out of scope this phase. |
| Singleton tables (briefing/focus/weather/commute) feel awkward in SQL | Use `CHECK (id = 1)` constraint. Pragmatic for read-only data; Phase B+ may upgrade to per-user rows. |
| Two `agents` concepts (cross-domain roster vs per-domain agents) can confuse | Use distinct table names: `agents_global` for the roster, `domain_agents` for per-domain. Endpoints clearly labelled (`/dashboard/agents` vs `/domains/{slug}` nested). |
| Migration order — applications/agents/kpis FK domains | Alembic autogenerate handles ordering; verify before commit. |
| `useFetch` has no caching/dedup → 13 fetches on Dashboard mount | Acceptable for Phase A. Switch to React Query / SWR in a later UX-polish phase. |
| Loading flicker on each widget | Each widget shows its existing styling with placeholder content while `data === null`. Skeleton loaders deferred to UX polish. |

---

## 10. Verification

Final task is a smoke test:
1. `docker compose up --build`
2. `curl http://localhost:8000/api/v1/dashboard/tasks` returns the 6 seeded tasks
3. `curl http://localhost:8000/api/v1/domains/finance` returns the full finance config
4. Open `http://localhost:3000` — every widget renders the same content as before, but Network tab shows 13–14 `/api/v1/...` requests.
5. Stop containers, `docker compose down -v`, restart — seed re-runs cleanly.

If all four pass, Phase A ships. Then `/gate` → Merge to Main → Vercel deploy.

---

## 11. Out of scope (explicit)

- Authentication / OAuth
- Anthropic chat or any AI calls
- Write endpoints (POST/PATCH/DELETE)
- Tests (unit, integration, E2E) — separate test-infra phase
- Real Google Calendar / Gmail / GitHub integrations
- The 24 domain agents implementation (only their *display rows* in `domain_agents` table)
- Airflow DAGs
- Frontend skeleton loaders / fancy loading states
- Caching / SWR / React Query
- Pagination of any list (deferred until lists exceed 100 rows)
