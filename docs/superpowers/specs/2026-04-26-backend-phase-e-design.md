# Backend Phase E — 24 Domain Agents + In-Process Gateway

**Date:** 2026-04-26
**Phase:** E of 6 (sequence: A → C → D → E → F → B; chat is last)
**Goal:** 24 deterministic domain agents (4 each across calendar / email / github / ai-core / data-pipeline / infrastructure) composing Phase D tools through a single in-process gateway. Phase B will swap LLM reasoning into the LLM-bound agents.

---

## 1. What's in scope

| In | Out |
|---|---|
| `Agent` ABC + `AGENT_REGISTRY` map | Anthropic SDK / Claude tool-use orchestration (Phase B) |
| 24 agent classes (one per CLAUDE.md §19 entry) | Real LLM reasoning inside agents — placeholder/raise-NotImplementedError where required |
| `backend/src/services/gateway.py` — single in-process dispatcher with auth + domain routing | Cross-process service discovery |
| `POST /api/v1/agents/{domain}/{agent}/run` per agent (auth-gated) | Async event bus (Phase F adds Redis pub/sub) |
| `GET /api/v1/agents` — discovery endpoint listing all 24 | Airflow DAG triggers (Phase F implements; data-pipeline agents are stubs) |
| Pydantic input/output schemas with `data` + `summary` envelope (mirrors Phase D) | New env vars (none needed) |

---

## 2. Locked decisions

1. **All 24 agents** per CLAUDE.md §19. Some are real Phase E logic (~14), some are placeholder shells (~10) that Phase B/F replace.
2. **Deterministic only** — no Anthropic SDK calls in this phase. LLM-bound agents (e.g. `email_summarizer`, `pr_reviewer`) raise `AgentError("not_yet_implemented", "...replaced in Phase B")` from inside `run()` so the surface is alive but the brain isn't.
3. **In-process gateway** — `services/gateway.py` is a single Python module. Auth dependency `Depends(get_current_user)` enforced at the router level. Inter-agent calls go through `gateway.dispatch(domain, agent, user, db, payload)`.
4. **No async bus** — synchronous calls only this phase. Phase F adds Redis pub/sub.
5. **REST + Python registry** — same shape as Phase D. Each agent gets a slug `<domain>_<agent>` (e.g. `calendar_event_creator`). REST endpoint `POST /api/v1/agents/{domain}/{agent}/run` and direct callable `AGENT_REGISTRY[slug]`.

---

## 3. Module layout

```
backend/src/
├── agents/
│   ├── __init__.py
│   ├── base.py                      ← Agent ABC + AgentError + slug helpers
│   ├── registry.py                  ← AGENT_REGISTRY + @register
│   ├── routers.py                   ← REST: /api/v1/agents/{domain}/{agent}/run
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── event_creator.py
│   │   ├── event_updater.py
│   │   ├── meeting_suggester.py
│   │   └── schedule_analyzer.py
│   ├── email/
│   │   ├── __init__.py
│   │   ├── email_searcher.py
│   │   ├── email_drafter.py
│   │   ├── email_labeler.py
│   │   └── email_summarizer.py
│   ├── github/
│   │   ├── __init__.py
│   │   ├── issue_manager.py
│   │   ├── pr_reviewer.py
│   │   ├── code_summarizer.py
│   │   └── repo_monitor.py
│   ├── ai_core/
│   │   ├── __init__.py
│   │   ├── chat_orchestrator.py     ← placeholder; Phase B replaces
│   │   ├── tool_dispatcher.py       ← thin pointer at TOOL_REGISTRY
│   │   ├── context_manager.py       ← placeholder; needs conversation_messages table (Phase B)
│   │   └── response_streamer.py     ← placeholder; SSE plumbing in Phase B
│   ├── data_pipeline/
│   │   ├── __init__.py
│   │   ├── calendar_ingestor.py     ← placeholder; Phase F triggers Airflow DAG
│   │   ├── email_ingestor.py        ← placeholder
│   │   ├── github_ingestor.py       ← placeholder
│   │   └── analytics_processor.py   ← placeholder
│   └── infrastructure/
│       ├── __init__.py
│       ├── api_gateway.py           ← self-ref to gateway.py (echoes routing decisions)
│       ├── auth_manager.py          ← thin pointer at /auth endpoints
│       ├── cache_manager.py         ← Redis CRUD
│       └── health_monitor.py        ← polls dependencies
└── services/
    ├── __init__.py
    └── gateway.py                   ← single dispatcher module
```

---

## 4. Agent ABC contract

```python
class Agent(ABC):
    domain: str               # one of 6 — used for URL routing
    name: str                 # snake_case, e.g. "event_creator"
    description: str          # for Phase B Claude tool-use schema later
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]   # always {data, summary}
    tool_dependencies: list[str]      # Phase D tool names this agent invokes

    async def run(self, *, user: User, db: AsyncSession, payload: BaseModel) -> BaseModel: ...
```

`slug = f"{domain}_{name}"`. Registry keys by slug. The REST URL is `/api/v1/agents/{domain}/{name}/run` (no slug duplication in path).

---

## 5. Gateway contract

```python
async def dispatch(
    domain: str,
    agent: str,
    *,
    user: User,
    db: AsyncSession,
    payload: dict,
) -> BaseModel:
    """Single entry point for inter-agent calls + REST router.

    1. Look up agent by (domain, name).
    2. Validate payload against agent.input_schema.
    3. Run agent.run().
    4. Map exceptions to envelope codes for the router.
    """
```

Router calls `gateway.dispatch(...)`. Phase B chat will also call `gateway.dispatch(...)` directly when routing user intent to an agent. Inter-agent calls (rule §19.4) go through the same function — never `Agent.run()` directly.

---

## 6. Per-agent inventory (24 — what each one does in Phase E)

### calendar (4) — real logic
| Agent | Tools used | Phase E behaviour |
|---|---|---|
| `event_creator` | `calendar_create_event` | Pass-through with input mapping |
| `event_updater` | `calendar_update_event` | Pass-through with input mapping |
| `meeting_suggester` | `calendar_find_free_slots` + `calendar_list_events` | Composes free-slot search and surrounding context |
| `schedule_analyzer` | `calendar_list_events` | Returns events + count-of-conflicts (overlap detection) |

### email (4) — real logic
| Agent | Tools used | Phase E behaviour |
|---|---|---|
| `email_searcher` | `gmail_search_threads` | Pass-through; query passes verbatim |
| `email_drafter` | `gmail_create_draft` | Pass-through; LLM composition deferred to Phase B |
| `email_labeler` | `gmail_apply_label` | Pass-through |
| `email_summarizer` | `gmail_get_thread` | Heuristic: returns first 200 chars of latest message body — Phase B replaces with Claude |

### github (4) — real logic
| Agent | Tools used | Phase E behaviour |
|---|---|---|
| `issue_manager` | `github_list_issues` + `github_create_issue` + `github_update_issue` | Verb routing: action=`list/create/update` |
| `pr_reviewer` | `github_list_prs` | Heuristic summary: counts open PRs, flags drafts — Phase B adds diff review |
| `code_summarizer` | none yet | Phase E: raises `not_yet_implemented` (needs commit-fetch tool not in Phase D) |
| `repo_monitor` | `github_list_issues` + `github_list_prs` | Aggregates open issue + PR counts |

### ai_core (4) — placeholders
| Agent | Phase E behaviour |
|---|---|
| `chat_orchestrator` | `not_yet_implemented` — Phase B owns intent routing |
| `tool_dispatcher` | Pointer at Phase D's `TOOL_REGISTRY`; runs the named tool with the supplied payload |
| `context_manager` | `not_yet_implemented` — needs conversation_messages table (Phase B schema) |
| `response_streamer` | `not_yet_implemented` — SSE plumbing lands in Phase B |

### data_pipeline (4) — placeholders
| Agent | Phase E behaviour |
|---|---|
| `calendar_ingestor` | `not_yet_implemented` — Phase F triggers the Airflow DAG |
| `email_ingestor` | same |
| `github_ingestor` | same |
| `analytics_processor` | same — needs ingested data first |

### infrastructure (4) — mixed
| Agent | Phase E behaviour |
|---|---|
| `api_gateway` | Self-reflective: returns the gateway's current registered domains + agent counts |
| `auth_manager` | Read-only pointer at `/api/v1/auth/me` data (returns the calling user's profile) |
| `cache_manager` | Redis GET/SET/DEL on a namespaced prefix (`agent_cache:{user_id}:{key}`) |
| `health_monitor` | Pings Postgres + Redis + Anthropic API key existence; returns `{ok: bool, components: [...]}` |

---

## 7. New env vars

None.

---

## 8. Atomic commit breakdown

32 commits.

| # | Title | Files |
|---|---|---|
| 1 | spec | this file |
| 2 | Agent ABC + registry | `backend/src/agents/{__init__.py, base.py, registry.py}` |
| 3 | gateway | `backend/src/services/{__init__.py, gateway.py}` |
| 4–7 | calendar agents | `agents/calendar/*` |
| 8–11 | email agents | `agents/email/*` |
| 12–15 | github agents | `agents/github/*` |
| 16–19 | ai_core agents | `agents/ai_core/*` |
| 20–23 | data_pipeline agents | `agents/data_pipeline/*` |
| 24–27 | infrastructure agents | `agents/infrastructure/*` |
| 28 | REST router + main.py wiring | `agents/routers.py`, `main.py` |
| 29 | docs | `README.md`, `CLAUDE.md` |
| 30–31 | gate cycle 1 fixes | various |
| 32 | gate report + push | `tasks/last-gate-report.md` |

---

## 9. Verification (post-merge end-to-end)

1. `curl https://arshad-ai.onrender.com/api/v1/agents -H "Authorization: Bearer $JWT"` → 24 agents listed.
2. `curl POST /api/v1/agents/calendar/meeting_suggester/run -d '{"time_min":"...","time_max":"...","duration_minutes":30}'` → `{data, summary: [{start,end},...]}`.
3. `curl POST /api/v1/agents/github/repo_monitor/run -d '{"repo":"marshadgani/Arshad.AI"}'` → `{data, summary: {open_issues, open_prs}}`.
4. `curl POST /api/v1/agents/ai_core/chat_orchestrator/run -d '{}'` → 501 `not_yet_implemented`.
5. `curl POST /api/v1/agents/infrastructure/health_monitor/run -d '{}'` → 200 with each component's status.

---

## 10. Out of scope (deferred)

- **Anthropic SDK** → Phase B
- **Real LLM reasoning** in any agent — Phase B replaces the placeholder paths
- **Airflow DAG triggers** → Phase F implements the data_pipeline agents' real behaviour
- **Conversation memory + SSE** → Phase B (the ai_core placeholders)
- **Service discovery / cross-process** → not planned
- **Tests** → same project-wide deferral as Phase A/C/D
