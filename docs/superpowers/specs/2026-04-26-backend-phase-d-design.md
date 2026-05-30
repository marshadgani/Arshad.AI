# Backend Phase D — Real Integrations via Claude Tool-Calling

**Date:** 2026-04-26
**Phase:** D of 6 (sequence: A → C → D → E → F → B; chat is last)
**Goal:** 12 real tools (4 each for Calendar, Gmail, GitHub) using the encrypted OAuth tokens from Phase C. Each tool is invokable via REST (`POST /api/v1/tools/{name}`) and exported from a Python registry that Phase B chat will consume.

---

## 1. What's in scope

| In | Out |
|---|---|
| Token service (decrypt OAuth token row → access_token; lazy Google refresh on 401) | Anthropic SDK / chat orchestration (Phase B) |
| `Tool` ABC + `TOOL_REGISTRY` map | 24 domain agents (Phase E) — these will COMPOSE Phase D tools |
| Provider HTTP clients — Google Calendar, Gmail, GitHub | Airflow ingestion DAGs (Phase F) |
| 12 tool implementations (4 calendar, 4 gmail, 4 github) | Webhooks / push notifications |
| `POST /api/v1/tools/{tool-name}` — auth-gated, JSON in/out | Bulk ops, file attachments, drafts-with-attachments |
| Pydantic input/output schemas with `data` (raw) + `summary` (normalized) | Per-tool rate limiting (rely on provider 429) |
| `github_reauth_required` envelope when GitHub returns 401 | Background sync / caching of provider data |

---

## 2. Locked decisions

1. **12 tools, 4 per provider:**
   - Calendar: `calendar_list_events`, `calendar_create_event`, `calendar_update_event`, `calendar_find_free_slots`
   - Gmail: `gmail_search_threads`, `gmail_get_thread`, `gmail_create_draft`, `gmail_apply_label`
   - GitHub: `github_list_issues`, `github_create_issue`, `github_update_issue`, `github_list_prs`
2. **REST + Python registry.** REST endpoint per tool (auth-gated by `Depends(get_current_user)`); same handler exported from `tools/registry.py` so Phase B chat can call without HTTP round-trip.
3. **Lazy Google refresh on 401.** Catch 401 → exchange refresh_token → encrypt → persist → retry once. If refresh itself returns 4xx, return `google_reauth_required` envelope.
4. **GitHub 401 → `github_reauth_required` envelope.** No silent retry — user must reconnect.
5. **Response shape: `{data, summary}`.** Raw provider JSON under `data` (Claude tool-use is fine with raw shapes); normalized fields under `summary` for chat surfacing.

---

## 3. Module layout

```
backend/src/tools/
├── __init__.py
├── base.py                    ← Tool ABC + ToolError + ProviderReauthRequired
├── registry.py                ← TOOL_REGISTRY: dict[str, Tool] + dispatch()
├── token_service.py           ← get_access_token(user, provider) — handles refresh
├── clients/
│   ├── __init__.py
│   ├── google_calendar.py     ← thin httpx wrapper, refresh-on-401 decorator
│   ├── gmail.py
│   └── github.py
├── calendar/
│   ├── __init__.py
│   ├── list_events.py         ← class CalendarListEvents(Tool)
│   ├── create_event.py
│   ├── update_event.py
│   └── find_free_slots.py
├── gmail/
│   ├── __init__.py
│   ├── search_threads.py
│   ├── get_thread.py
│   ├── create_draft.py
│   └── apply_label.py
├── github/
│   ├── __init__.py
│   ├── list_issues.py
│   ├── create_issue.py
│   ├── update_issue.py
│   └── list_prs.py
└── routers.py                 ← POST /api/v1/tools/{name}
```

---

## 4. Tool ABC contract

```python
class Tool(ABC):
    name: str                   # e.g. "calendar_list_events" — also URL slug
    description: str            # for Claude tool-use schema (Phase B)
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]   # always shaped {data, summary}

    async def __call__(self, *, user: User, db: AsyncSession, payload: BaseModel) -> BaseModel: ...
```

Every tool subclass:
1. Validates input via Pydantic.
2. Calls `get_access_token(db, user, provider)` to obtain a usable token.
3. Calls the provider HTTP client; the client wraps refresh-on-401 for Google.
4. Returns a Pydantic model with `data` (provider JSON) and `summary` (normalized).

`TOOL_REGISTRY = {tool.name: tool for tool in [...]}`. The REST router and Phase B chat both consume this map.

---

## 5. Token service contract

```python
async def get_access_token(
    db: AsyncSession,
    user: User,
    provider: Literal["google", "github"],
) -> str:
    """Returns a usable access token. Decrypts from oauth_tokens.

    Raises ProviderNotLinked(provider) if the user has no oauth_account
    for this provider — tool router maps to 400 oauth_account_not_linked.

    Does NOT preemptively refresh. Caller (the HTTP client) detects 401
    and calls refresh_google_token() to get a fresh token, then retries.
    """

async def refresh_google_token(
    db: AsyncSession,
    oauth_account_id: uuid.UUID,
) -> str:
    """Exchange refresh_token for new access_token. Persists encrypted.
    Raises ProviderReauthRequired('google') if Google rejects the refresh
    (refresh token revoked, scope removed, etc.).
    """
```

GitHub has no refresh path. On 401, the GitHub HTTP client raises `ProviderReauthRequired("github")` directly.

---

## 6. REST endpoint contract

```
POST /api/v1/tools/{tool-name}
Authorization: Bearer <jwt>
Content-Type: application/json

{ ... tool-specific input ... }
```

Response (200):
```json
{
  "data": { ...raw provider JSON... },
  "summary": { "id": "...", "title": "...", "when": "...", "url": "..." }
}
```

Errors:
- 400 `oauth_account_not_linked` — user hasn't logged in with this provider yet
- 400 `invalid_input` — Pydantic validation error
- 401 `google_reauth_required` / `github_reauth_required` — token revoked
- 502 `provider_http_error` / `provider_unreachable` — same envelope as Phase C OAuth callback errors
- 404 `unknown_tool` — slug doesn't match a registered tool

---

## 7. Per-tool input/output (concise)

### Calendar
| Tool | Input | Output `summary` shape |
|---|---|---|
| `calendar_list_events` | `time_min` (RFC3339), `time_max`, `max_results=20` | `[{id, title, start, end, location?, attendees?}]` |
| `calendar_create_event` | `title`, `start`, `end`, `description?`, `attendees?[]`, `location?` | `{id, title, start, end, html_link}` |
| `calendar_update_event` | `event_id`, `patch: {title?, start?, end?, description?}` | `{id, title, start, end}` |
| `calendar_find_free_slots` | `time_min`, `time_max`, `duration_minutes`, `max_results=5` | `[{start, end}]` (computed from busy ranges) |

### Gmail
| Tool | Input | Output `summary` shape |
|---|---|---|
| `gmail_search_threads` | `query` (Gmail search syntax), `max_results=20`, `label_ids?[]` | `[{thread_id, snippet, latest_subject, latest_from, latest_date}]` |
| `gmail_get_thread` | `thread_id` | `{thread_id, messages: [{id, from, to, subject, date, body_plain}]}` |
| `gmail_create_draft` | `to[]`, `subject`, `body_plain`, `cc?[]`, `in_reply_to_thread_id?` | `{draft_id, message_id}` |
| `gmail_apply_label` | `thread_id`, `add_label_ids?[]`, `remove_label_ids?[]` | `{thread_id, label_ids[]}` |

### GitHub
| Tool | Input | Output `summary` shape |
|---|---|---|
| `github_list_issues` | `repo` (owner/name), `state=open\|closed\|all`, `labels?[]`, `assignee?`, `max_results=30` | `[{number, title, state, url, author, labels[], updated_at}]` |
| `github_create_issue` | `repo`, `title`, `body?`, `labels?[]`, `assignees?[]` | `{number, url, title}` |
| `github_update_issue` | `repo`, `number`, `patch: {title?, body?, state?, labels?, assignees?}` | `{number, url, state, title}` |
| `github_list_prs` | `repo`, `state`, `max_results=30` | `[{number, title, state, url, author, head, base, draft, mergeable_state, updated_at}]` |

All raw provider JSON survives in `data`.

---

## 8. New env vars

None. Phase D reuses `OAUTH_ENCRYPTION_KEY`, the OAuth client IDs/secrets, and `BACKEND_URL` from Phase C.

---

## 9. Atomic commit breakdown

22 commits.

| # | Title | Files |
|---|---|---|
| 1 | spec doc | this file |
| 2 | token service | `backend/src/tools/{__init__.py, token_service.py}` |
| 3 | tool ABC + registry | `backend/src/tools/{base.py, registry.py}` |
| 4 | google calendar client | `backend/src/tools/clients/{__init__.py, google_calendar.py}` |
| 5 | gmail client | `backend/src/tools/clients/gmail.py` |
| 6 | github client | `backend/src/tools/clients/github.py` |
| 7 | calendar.list_events | `backend/src/tools/calendar/{__init__.py, list_events.py}` |
| 8 | calendar.create_event | `backend/src/tools/calendar/create_event.py` |
| 9 | calendar.update_event | `backend/src/tools/calendar/update_event.py` |
| 10 | calendar.find_free_slots | `backend/src/tools/calendar/find_free_slots.py` |
| 11 | gmail.search_threads | `backend/src/tools/gmail/{__init__.py, search_threads.py}` |
| 12 | gmail.get_thread | `backend/src/tools/gmail/get_thread.py` |
| 13 | gmail.create_draft | `backend/src/tools/gmail/create_draft.py` |
| 14 | gmail.apply_label | `backend/src/tools/gmail/apply_label.py` |
| 15 | github.list_issues | `backend/src/tools/github/{__init__.py, list_issues.py}` |
| 16 | github.create_issue | `backend/src/tools/github/create_issue.py` |
| 17 | github.update_issue | `backend/src/tools/github/update_issue.py` |
| 18 | github.list_prs | `backend/src/tools/github/list_prs.py` |
| 19 | REST router + main.py wiring | `backend/src/tools/routers.py`, `main.py` |
| 20 | docs | `README.md`, `CLAUDE.md` |
| 21 | gate cycle 1 fixes | various |
| 22 | gate report + push | `tasks/last-gate-report.md` |

---

## 10. Verification (post-merge end-to-end)

1. `docker compose up --build`
2. Sign into the app once with Google + once with GitHub (populates oauth_tokens)
3. Mint a JWT (UI login OR `curl /api/v1/auth/me` to confirm)
4. **Calendar**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/tools/calendar_list_events \
     -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
     -d '{"time_min":"2026-04-26T00:00:00Z","time_max":"2026-05-03T00:00:00Z"}' | jq
   ```
   Expect `{data: {...kind:"calendar#events", items:[...]}, summary: [{id, title, start, end}, ...]}`.
5. **Gmail**: `curl POST gmail_search_threads {"query":"in:inbox newer_than:7d","max_results":5}` → see thread snippets.
6. **GitHub**: `curl POST github_list_issues {"repo":"marshadgani/Arshad.AI","state":"open"}` → see issue list.
7. **Token refresh**: invalidate the Google access_token in DB (or wait 1h); next call returns 200 (refresh kicked in transparently).
8. **GitHub revoke**: revoke the OAuth app at https://github.com/settings/applications; next github_* call returns 401 `github_reauth_required`.

---

## 11. Out of scope (deferred to later phases)

- **Anthropic SDK / chat orchestration** → Phase B (last phase). Phase D's registry is what Phase B consumes.
- **24 domain agents** → Phase E. They compose Phase D tools (e.g. `meeting-suggester` agent calls `calendar_find_free_slots` + `calendar_list_events` + LLM reasoning).
- **Webhooks / push notifications / background sync** → Phase F.
- **Bulk operations, file attachments, drafts with attachments** → ad-hoc.
- **Per-tool rate limiting** → defer; Google + GitHub already 429 on overuse, providers handle backoff.
- **Tests** → same project-wide deferral as Phase A and Phase C.
