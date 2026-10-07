"""Chat orchestration — agentic loop + SSE event yielding + persistence.

A single ``chat_turn`` async generator drives:
  1. classify intent (stage 1)
  2. select tool subset for that intent
  3. open a streaming Anthropic call
  4. on tool_use, dispatch via the agent gateway / tool registry
  5. on tool_result, append to messages and re-stream
  6. on text delta, yield SSE delta events
  7. persist as it goes: the user message before streaming starts
     (persist_user_message), tool_use/tool_result rows as they happen, and the
     assistant text when the stream finishes or the client disconnects

The function yields SSE-shaped strings (each ending with `\\n\\n`) so the
REST handler just relays them through StreamingResponse.

Tool subset per intent (see Phase B spec §6):
  calendar: 4 calendar tools + meeting_suggester + schedule_analyzer agents
  email:    4 gmail tools + email_summarizer agent
  github:   6 github tools (incl. new get_pr/get_commit) + pr_reviewer +
            code_summarizer + repo_monitor agents
  general:  no tools, pure conversational reply
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.registry import AGENT_REGISTRY
from ..models.conversation import ConversationMessage, ConversationSession
from ..models.user import User
from ..tools.registry import TOOL_REGISTRY
from . import ai, intent_classifier

_MAX_AGENTIC_HOPS = 6  # safety cap on tool_use → tool_result → call rounds

# 3-tier model strategy (CLAUDE.md §Model Strategy). The chat agentic loop
# is the runtime "chat-orchestrator" — it picks tools and reasons over their
# results. Sonnet, not Haiku: tool selection quality compounds across hops.
# Override via env var for ad-hoc cost tuning without code changes.
_CHAT_MODEL = os.getenv("ANTHROPIC_MODEL_CHAT", "claude-sonnet-4-6")

_SYSTEM_PROMPT_BASE = """\
You are Arshad's personal AI assistant. The user has linked Google (Calendar + Gmail)
and GitHub. You can call tools to take real actions on their behalf. Be concise,
use the tools when relevant, and explain what you're doing in one short sentence
before invoking a tool.
"""


def sse_event(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _tool_subset(intent: str) -> tuple[list[str], list[str]]:
    """Returns (tool_names, agent_slugs) for the intent."""
    if intent == "calendar":
        return (
            [
                "calendar_list_events",
                "calendar_create_event",
                "calendar_update_event",
                "calendar_find_free_slots",
            ],
            ["calendar_meeting_suggester", "calendar_schedule_analyzer"],
        )
    if intent == "email":
        return (
            [
                "gmail_search_threads",
                "gmail_get_thread",
                "gmail_create_draft",
                "gmail_apply_label",
            ],
            ["email_email_summarizer"],
        )
    if intent == "github":
        tool_names = [
            "github_list_issues",
            "github_create_issue",
            "github_update_issue",
            "github_list_prs",
        ]
        if "github_get_pr" in TOOL_REGISTRY:
            tool_names.append("github_get_pr")
        if "github_get_commit" in TOOL_REGISTRY:
            tool_names.append("github_get_commit")
        return (
            tool_names,
            ["github_pr_reviewer", "github_code_summarizer", "github_repo_monitor"],
        )
    if intent == "obsidian":
        return (
            [
                "obsidian_search_notes",
                "obsidian_get_note",
                "obsidian_create_note",
                "obsidian_update_note",
            ],
            [],
        )
    return ([], ["ai_core_council_chairman"])


def _build_tool_schemas(
    tool_names: list[str], agent_slugs: list[str]
) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for name in tool_names:
        tool = TOOL_REGISTRY.get(name)
        if tool is None:
            continue
        schemas.append(
            {
                "name": name,
                "description": tool.description,
                "input_schema": tool.input_schema.model_json_schema(),
            }
        )
    for slug in agent_slugs:
        agent = AGENT_REGISTRY.get(slug)
        if agent is None:
            continue
        schemas.append(
            {
                "name": f"agent_{slug}",
                "description": agent.description,
                "input_schema": agent.input_schema.model_json_schema(),
            }
        )
    return schemas


async def _dispatch_tool(
    name: str,
    raw_input: dict,
    *,
    user: User,
    db: AsyncSession,
) -> tuple[Any, bool]:
    """Returns (output, is_error). is_error=True surfaces error envelope to Claude."""
    if name.startswith("agent_"):
        slug = name[len("agent_") :]
        agent = AGENT_REGISTRY.get(slug)
        if agent is None:
            return ({"error": "unknown_agent", "name": slug}, True)
        try:
            payload = agent.input_schema.model_validate(raw_input)
            result = await agent.run(user=user, db=db, payload=payload)
            return (result.model_dump(mode="json"), False)
        except Exception as exc:  # noqa: BLE001 — return as error to Claude, not crash
            return ({"error": type(exc).__name__, "message": str(exc)}, True)

    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return ({"error": "unknown_tool", "name": name}, True)
    try:
        payload = tool.input_schema.model_validate(raw_input)
        result = await tool(user=user, db=db, payload=payload)
        return (result.model_dump(mode="json"), False)
    except Exception as exc:  # noqa: BLE001
        return ({"error": type(exc).__name__, "message": str(exc)}, True)


def _history_token_budget() -> int:
    try:
        return max(500, int(os.getenv("CHAT_HISTORY_TOKEN_BUDGET", "8000")))
    except ValueError:
        return 8000


def _approx_tokens(text: str) -> int:
    """Rough 4-chars-per-token estimate. Cheap enough to call per row."""
    return max(1, len(text) // 4)


def _compress_history(messages: list[dict]) -> list[dict]:
    """Drop oldest user/assistant pairs until under the token budget.

    Tool_use / tool_result blocks within an assistant turn stay glued to
    their parent assistant message — we drop whole turns, never half a turn.
    """
    budget = _history_token_budget()
    total = sum(_approx_tokens(json.dumps(m.get("content", ""))) for m in messages)
    if total <= budget:
        return messages

    compressed = list(messages)
    while compressed and total > budget:
        # Find the index of the SECOND user message (preserve the first as
        # context). Drop from the start up to (but not including) that index.
        user_indices = [i for i, m in enumerate(compressed) if m.get("role") == "user"]
        if len(user_indices) < 2:
            break
        drop_until = user_indices[1]
        dropped = compressed[:drop_until]
        compressed = compressed[drop_until:]
        total -= sum(_approx_tokens(json.dumps(m.get("content", ""))) for m in dropped)
    return compressed


async def _load_session_history(db: AsyncSession, session_id) -> list[dict[str, Any]]:
    """Loads ConversationMessage rows and rebuilds Anthropic-API-shaped history.

    Anthropic's messages API expects:
      [{"role": "user", "content": "..."}, {"role": "assistant", "content": [...]}, ...]
    """
    from sqlalchemy import select

    rows = (
        await db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at)
        )
    ).all()

    history: list[dict[str, Any]] = []
    pending_assistant_blocks: list[dict[str, Any]] = []

    def _flush_assistant() -> None:
        if pending_assistant_blocks:
            history.append(
                {"role": "assistant", "content": list(pending_assistant_blocks)}
            )
            pending_assistant_blocks.clear()

    for row in rows:
        c = row.content
        if row.role == "user":
            _flush_assistant()
            history.append({"role": "user", "content": c.get("text", "")})
        elif row.role == "assistant":
            _flush_assistant()
            history.append({"role": "assistant", "content": c.get("text", "")})
        elif row.role == "tool_use":
            pending_assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": c.get("tool_use_id"),
                    "name": c.get("tool"),
                    "input": c.get("input", {}),
                }
            )
        elif row.role == "tool_result":
            _flush_assistant()
            history.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": c.get("tool_use_id"),
                            "content": json.dumps(c.get("output", {}), default=str),
                            "is_error": c.get("is_error", False),
                        }
                    ],
                }
            )
    _flush_assistant()
    return history


async def _persist_partial_reply(
    db: AsyncSession,
    session: ConversationSession,
    assistant_text: str,
    usage: dict[str, Any],
) -> None:
    """Best-effort save of a reply cut short by a client disconnect.

    Never raises: it runs while a GeneratorExit is propagating and must not
    mask it with a different exception.
    """
    if not assistant_text or session.id is None:
        return
    try:
        db.add(
            ConversationMessage(
                session_id=session.id,
                role="assistant",
                content={"text": assistant_text, "_partial": True},
                model=_CHAT_MODEL,
                usage_input_tokens=usage.get("input_tokens"),
                usage_output_tokens=usage.get("output_tokens"),
            )
        )
        await db.commit()
    except Exception:
        # Roll back so the AsyncSession's dirty state doesn't leak into the
        # next request via connection-pool reuse.
        try:
            await db.rollback()
        except Exception:
            pass


async def persist_user_message(
    *, session: ConversationSession, db: AsyncSession, user_text: str
) -> None:
    """Commit the user's message before any response bytes are sent.

    Callers that stream (the HTTP route) must await this *before* building
    the StreamingResponse: an exception raised inside the response body
    arrives after the 200 and headers are already on the wire, so the client
    would see a silently truncated stream instead of an error status.
    """
    db.add(
        ConversationMessage(
            session_id=session.id,
            role="user",
            content={"text": user_text},
        )
    )
    if session.title == "New chat":
        session.title = user_text[:60]
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def chat_turn(
    *,
    session: ConversationSession,
    user: User,
    db: AsyncSession,
    user_text: str,
    user_message_persisted: bool = False,
) -> AsyncIterator[str]:
    """Drive one user → assistant turn. Yields SSE-shaped strings.

    Persists every message (user + each tool_use + tool_result + final
    assistant text) to ``conversation_messages`` so the next turn can
    reload the full history. Pass ``user_message_persisted=True`` when the
    caller already awaited :func:`persist_user_message`.
    """
    if not user_message_persisted:
        await persist_user_message(session=session, db=db, user_text=user_text)

    history = await _load_session_history(db, session.id)
    history = _compress_history(history)

    intent = await intent_classifier.classify(user_text, history)
    yield sse_event({"intent": intent})

    tool_names, agent_slugs = _tool_subset(intent)
    # Build tool schemas regardless of intent — `general` carries the
    # `ai_core_council_chairman` agent in agent_slugs, which the prior code
    # suppressed by short-circuiting on intent=="general". Now we only fall
    # back to None when both lists are empty, which is the actual signal
    # for "no tools at all".
    if not tool_names and not agent_slugs:
        tool_schemas = None
    else:
        tool_schemas = _build_tool_schemas(tool_names, agent_slugs)

    assistant_text = ""
    final_usage = {"input_tokens": 0, "output_tokens": 0}

    try:
        for hop in range(_MAX_AGENTIC_HOPS):
            new_assistant_blocks: list[dict[str, Any]] = []
            ran_a_tool = False

            async for event_type, payload in ai.stream(
                system=_SYSTEM_PROMPT_BASE,
                messages=history,
                tools=tool_schemas,
                model=_CHAT_MODEL,
            ):
                if event_type == "delta":
                    assistant_text += payload
                    yield sse_event({"delta": payload})
                elif event_type == "tool_use":
                    yield sse_event(
                        {
                            "tool_use": {
                                "id": payload["id"],
                                "name": payload["name"],
                                "input": payload["input"],
                            }
                        }
                    )
                    db.add(
                        ConversationMessage(
                            session_id=session.id,
                            role="tool_use",
                            content={
                                "tool_use_id": payload["id"],
                                "tool": payload["name"],
                                "input": payload["input"],
                            },
                        )
                    )
                    output, is_error = await _dispatch_tool(
                        payload["name"], payload["input"], user=user, db=db
                    )
                    yield sse_event(
                        {
                            "tool_result": {
                                "id": payload["id"],
                                "name": payload["name"],
                                "output": output,
                                "is_error": is_error,
                            }
                        }
                    )
                    db.add(
                        ConversationMessage(
                            session_id=session.id,
                            role="tool_result",
                            content={
                                "tool_use_id": payload["id"],
                                "output": output,
                                "is_error": is_error,
                            },
                        )
                    )
                    new_assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": payload["id"],
                            "name": payload["name"],
                            "input": payload["input"],
                        }
                    )
                    history.append(
                        {"role": "assistant", "content": list(new_assistant_blocks)}
                    )
                    history.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": payload["id"],
                                    "content": json.dumps(output, default=str),
                                    "is_error": is_error,
                                }
                            ],
                        }
                    )
                    ran_a_tool = True
                elif event_type == "usage":
                    final_usage = payload
                elif event_type == "done":
                    pass

            if not ran_a_tool:
                break  # Claude returned a final text answer; we're done
    except GeneratorExit:
        # Client dropped while the model was still streaming (or between
        # tool hops): keep what was generated so far, then let the
        # generator close.
        await _persist_partial_reply(db, session, assistant_text, final_usage)
        raise

    # Persist the assistant text even if the client disconnects mid-stream.
    # We wrap the final commit in a try/finally so the generator's GeneratorExit
    # (raised by FastAPI when the SSE consumer drops) still triggers persistence.
    # Without this, the user message is already committed but partial assistant
    # text is lost — DEF-028-01 from the audit.
    reply_saved = False
    try:
        if assistant_text:
            db.add(
                ConversationMessage(
                    session_id=session.id,
                    role="assistant",
                    content={"text": assistant_text},
                    model=_CHAT_MODEL,
                    usage_input_tokens=final_usage.get("input_tokens"),
                    usage_output_tokens=final_usage.get("output_tokens"),
                )
            )
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        reply_saved = True
        yield sse_event("[DONE]")
    except GeneratorExit:
        # Client disconnected on the final event. Commit what we have so the
        # partial assistant_text survives, and re-raise so FastAPI cleans up.
        if not reply_saved:
            await _persist_partial_reply(db, session, assistant_text, final_usage)
        raise
