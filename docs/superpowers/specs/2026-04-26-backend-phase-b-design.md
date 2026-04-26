# Backend Phase B — Anthropic Chat + SSE + Conversation Memory + LLM Agents

**Date:** 2026-04-26
**Phase:** B of 6 — **FINAL phase** (sequence: A → C → D → E → F → B)
**Goal:** Wire the Anthropic SDK, persistent conversation memory, SSE streaming, and replace the 6 LLM-bound Phase E placeholders/heuristics with real Claude calls.

---

## 1. What's in scope

| In | Out |
|---|---|
| `services/ai.py` — Anthropic SDK wrapper (sync + streaming) | Multi-modal (image / file) chat — text only |
| Two-stage routing: Haiku classifier picks domain → second Haiku call with that domain's tools | Multiple parallel tool calls in one turn — sequential only |
| `conversation_sessions` + `conversation_messages` tables + Alembic migration | Edit / regenerate previous messages — append-only |
| `POST /api/v1/chat/sessions` create + `GET /sessions` list + `GET /sessions/{id}/messages` history | Cross-session memory (RAG) — single-session context only |
| `POST /api/v1/chat/sessions/{id}/messages` — SSE stream of the assistant's response | Voice / audio interface |
| 6 placeholder/heuristic agents replaced with real Claude calls | Custom system prompts per session |
| Tools: `github_get_pr`, `github_get_commit` (needed by upgraded pr_reviewer + code_summarizer) | New OAuth scopes |
| Frontend: `useChatStream` hook + ChatPanel + sessions list + ChatBar SSE wiring | Mobile app |

---

## 2. Locked decisions

1. **Conversation memory:** `conversation_sessions` + `conversation_messages` tables. Append-only.
2. **Streaming:** SSE per CLAUDE.md §3. `data: {"delta": "..."}\n\n` for text, `data: {"tool_use": ...}\n\n` for tool calls, `data: {"tool_result": ...}\n\n` for results, final `data: [DONE]\n\n`. `Cache-Control: no-cache`.
3. **Two-stage routing:** stage 1 = Haiku classifier returns one of `{calendar, email, github, general}`; stage 2 = Haiku call with only that domain's tool subset (plus the relevant ai_core agents). General domain gets ZERO tools — pure conversational reply.
4. **Model:** `claude-haiku-4-5-20251001` for both stages.
5. **Replace all 6 LLM-bound agents** with real Claude calls.

---

## 3. Database schema

### `conversation_sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users.id ON DELETE CASCADE | |
| `title` | TEXT | first message's first 60 chars; updateable |
| `created_at` / `updated_at` | TIMESTAMPTZ | updated on every new message |

Index: `(user_id, updated_at DESC)` for the sidebar's "recent chats".

### `conversation_messages`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `session_id` | UUID FK → conversation_sessions.id ON DELETE CASCADE | |
| `role` | TEXT | `user` \| `assistant` \| `tool_use` \| `tool_result` |
| `content` | JSONB | role-shaped (see below) |
| `model` | TEXT, nullable | for assistant rows: `claude-haiku-4-5-20251001` |
| `usage_input_tokens` / `usage_output_tokens` | INTEGER, nullable | for assistant rows |
| `created_at` | TIMESTAMPTZ default now() | |

Index: `(session_id, created_at)` for ordered playback.

`content` JSONB shapes:
- **user**: `{"text": "..."}`
- **assistant**: `{"text": "..."}`
- **tool_use**: `{"tool": "calendar_list_events", "input": {...}, "tool_use_id": "..."}`
- **tool_result**: `{"tool_use_id": "...", "output": {...}, "is_error": false}`

One Alembic migration, `b1c2d3e4f5g6_phase_b_conversation_tables.py`, `down_revision -> f1b2c3d4e5f6` (Phase F).

---

## 4. Module layout

```
backend/src/
├── services/
│   ├── ai.py                       ← Anthropic SDK wrapper
│   ├── intent_classifier.py        ← stage-1 Haiku call
│   └── chat.py                     ← orchestration + SSE event yielder
├── api/v1/
│   └── chat.py                     ← /api/v1/chat/sessions + /messages
├── models/
│   └── conversation.py             ← ConversationSession + ConversationMessage
└── tools/github/
    ├── get_pr.py                   ← NEW — needed for pr_reviewer
    └── get_commit.py               ← NEW — needed for code_summarizer

frontend/src/
├── chat/
│   ├── useChatStream.ts            ← SSE consumer hook
│   ├── ChatPanel.tsx               ← message list + composer
│   ├── MessageList.tsx
│   ├── MessageBubble.tsx
│   └── ToolCallChip.tsx            ← inline "Using calendar_list_events..." UI
└── pages/
    └── Chat.tsx                    ← session-scoped chat page
```

---

## 5. SSE event protocol

Each event is `data: {JSON}\n\n`. Event types:

| Event JSON | When |
|---|---|
| `{"delta": "Sure, I'll check"}` | each text chunk from Claude |
| `{"tool_use": {"id": "tu_01", "name": "calendar_list_events", "input": {...}}}` | Claude decides to call a tool |
| `{"tool_result": {"id": "tu_01", "name": "calendar_list_events", "output": {...}, "is_error": false}}` | tool returned |
| `{"intent": "calendar"}` | (early) classifier resolved |
| `{"session": {"id": "...", "title": "..."}}` | (early) emitted on new sessions for the frontend to update the URL |
| `[DONE]` | final terminator |

Errors mid-stream: `{"error": {"code": "...", "message": "..."}}` then `[DONE]`. Frontend treats any `error` event as the assistant message's final state.

---

## 6. Two-stage routing

```python
async def chat_turn(user_msg: str, session_history: list, user, db):
    # Stage 1 — intent classifier (Haiku, no tools, ~50 tokens output)
    intent = await intent_classifier.classify(user_msg, history=session_history[-4:])
    yield sse_event({"intent": intent})
    # intent is one of: calendar, email, github, general

    # Stage 2 — domain-tools call (Haiku, streaming)
    tools = _tools_for_intent(intent)
    async for event in ai.stream(
        model="claude-haiku-4-5-20251001",
        system=_system_prompt(intent),
        messages=[*session_history, {"role": "user", "content": user_msg}],
        tools=tools,
    ):
        # ai.stream yields ('delta', text), ('tool_use', block), ('tool_result', block), ('done', None)
        ...
        # On tool_use: dispatch via gateway (or TOOL_REGISTRY) and continue the loop
```

`_tools_for_intent`:
- `calendar` → 4 calendar tools + `meeting_suggester` + `schedule_analyzer` agents
- `email` → 4 gmail tools + `email_summarizer` agent
- `github` → 6 github tools (4 from Phase D + new `github_get_pr`, `github_get_commit`) + `pr_reviewer` + `code_summarizer` + `repo_monitor` agents
- `general` → no tools, pure chat

Agents-as-tools: a Phase E agent's `input_schema` becomes a Claude tool schema. Calling the tool dispatches via `gateway.dispatch(domain, agent, ...)` and the result is fed back to Claude.

---

## 7. SDK wrapper (`services/ai.py`)

```python
async def stream(
    *,
    model: str,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
) -> AsyncIterator[tuple[str, Any]]:
    """Yields (event_type, payload) tuples:
       ('delta', str), ('tool_use', dict), ('tool_result', dict), ('done', None)
    """

async def call(
    *,
    model: str,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
) -> dict:
    """Non-streaming. Returns the assistant message dict."""
```

Both go through `anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)`. The wrapper is the single point where the SDK is touched — every other module calls `ai.stream` / `ai.call`.

---

## 8. Replaced agents (6)

| Agent | Phase E | Phase B |
|---|---|---|
| `chat_orchestrator` | placeholder | calls `services.chat.chat_turn` (synchronous wrapper for the agent endpoint; SSE goes through `/chat/sessions/{id}/messages`) |
| `context_manager` | placeholder | reads `conversation_messages`, applies token-budget compression (drop oldest message pairs until under budget); used by chat.py |
| `response_streamer` | placeholder | the SSE plumbing helper that `services/chat.py` calls; agent endpoint exposes a "format these events as SSE bytes" helper |
| `email_summarizer` | heuristic (200-char excerpt) | fetches thread → Haiku call with system prompt "summarize this thread in 2 sentences focused on action items" |
| `pr_reviewer` | heuristic (counts only) | fetches PR + diff → Haiku call with system prompt "review this PR; flag concerns; one paragraph" |
| `code_summarizer` | placeholder | uses new `github_get_commit` tool → Haiku call with system prompt "summarize this commit in 1 sentence" |

Each upgraded agent keeps the same `input_schema` so existing callers don't break. `is_heuristic=True` flag flips to `false` (or removed) to signal "real summary now".

---

## 9. REST endpoints (`/api/v1/chat`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions` | Create new session; body optional `{"title": "..."}` |
| GET | `/sessions` | List user's sessions, ordered by updated_at desc |
| GET | `/sessions/{id}/messages` | Get full message history for the session |
| POST | `/sessions/{id}/messages` | Send a user message; **returns SSE stream** of the assistant's reply |
| DELETE | `/sessions/{id}` | Delete a session (cascades to messages) |

All auth-gated. SSE response uses `StreamingResponse(media_type="text/event-stream", headers={"Cache-Control": "no-cache"})`.

---

## 10. New env vars

| Var | Required | Description |
|---|---|---|
| `ANTHROPIC_MODEL_DEFAULT` | Phase B+ | Default model name; defaults to `claude-haiku-4-5-20251001` |
| `CHAT_MAX_TOKENS` | Phase B+ | Max output tokens per turn; default `2048` |
| `CHAT_HISTORY_TOKEN_BUDGET` | Phase B+ | Max input-history tokens before compression; default `8000` |

`ANTHROPIC_API_KEY` already required since Phase A. Added the 3 new ones to `.env.example`.

---

## 11. Atomic commit breakdown

22 commits.

| # | Title |
|---|---|
| 1 | spec |
| 2 | ConversationSession + ConversationMessage models + Alembic migration |
| 3 | services/ai.py |
| 4 | services/intent_classifier.py |
| 5 | services/chat.py |
| 6 | tools/github/get_pr.py |
| 7 | tools/github/get_commit.py |
| 8 | api/v1/chat.py + register in main.py |
| 9–14 | replace 6 agents (chat_orchestrator, context_manager, response_streamer, email_summarizer, pr_reviewer, code_summarizer) |
| 15 | frontend `useChatStream` hook |
| 16 | frontend ChatPanel + MessageList + MessageBubble + ToolCallChip |
| 17 | frontend sessions list in Sidebar + new-chat button |
| 18 | App.tsx routing for `/chat/:sessionId` |
| 19 | docs (README + CLAUDE.md + .env.example) |
| 20 | gate-cycle 1 fixes |
| 21 | gate report + push for auto-merge |

---

## 12. Verification (post-merge end-to-end)

1. Sign in. Create session: `POST /api/v1/chat/sessions` → 201 with `{id, title: "New chat"}`.
2. Send a message:
   ```bash
   curl -N -X POST https://arshad-ai.onrender.com/api/v1/chat/sessions/<id>/messages \
     -H "Authorization: Bearer $JWT" \
     -d '{"text": "what's on my calendar tomorrow?"}'
   ```
   → SSE stream:
   ```
   data: {"intent": "calendar"}
   data: {"delta": "Let me check"}
   data: {"tool_use": {"id":"tu_01","name":"calendar_list_events","input":{"time_min":"...","time_max":"..."}}}
   data: {"tool_result": {"id":"tu_01","output":{"data":...,"summary":[...]}}}
   data: {"delta": "You have 3 events:"}
   data: {"delta": " 9am standup..."}
   data: [DONE]
   ```
3. `GET /api/v1/chat/sessions` → 1 session, title auto-set from first user message.
4. `GET /api/v1/chat/sessions/<id>/messages` → 4 messages (`user`, `tool_use`, `tool_result`, `assistant`).
5. **Frontend**: visit `/chat`, click "New chat", type a message → see chunks streaming live, tool-use chip rendering inline, final response appearing word-by-word.
6. **Email summarizer real**: `POST /api/v1/agents/email/email_summarizer/run -d '{"thread_id":"..."}'` → `summary.is_heuristic=false`, `summary.summary_text` is a real 2-sentence summary.

---

## 13. Out of scope (future work)

- **Multi-modal** (images / files) — text only
- **Parallel tool calls** in one turn — sequential only
- **Edit / regenerate previous messages** — append-only
- **Cross-session RAG / memory** — single-session context only
- **Voice / audio**
- **Per-user system prompts**
- **Multi-tenant cost tracking** — single-user product
- **Tests** — same project-wide deferral

---

## 14. After Phase B ships

The roadmap is **complete**. All 6 phases done. Outstanding items move to a separate post-MVP backlog:
- Test infrastructure (deferred since Phase A; covers all phases)
- Phase D's docker-compose airflow volume mount (one-line fix flagged in Phase F's gate report)
- Custom system prompts per session
- RAG over `ingested_*` tables (Phase F's data feeds Phase B's chat naturally)
- Multi-modal chat
