"""Anthropic SDK wrapper.

Single point in the codebase that touches the SDK. Every other module
calls ``ai.call(...)`` (non-streaming) or ``ai.stream(...)`` (streaming).

Streaming yields tagged tuples for clean dispatch in services/chat.py:
  ('delta', text)            — text chunks for SSE relay
  ('tool_use', block_dict)   — Claude wants to call a tool
  ('usage', dict)            — final token counts
  ('done', None)             — stream finished

The wrapper does NOT execute tool calls itself — chat.py owns the
agentic loop (run tool, append result, call again).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

_DEFAULT_MAX_TOKENS = 2048


def _client() -> AsyncAnthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("your-"):
        raise RuntimeError("ANTHROPIC_API_KEY is unset or still a placeholder")
    return AsyncAnthropic(api_key=api_key)


def _default_model() -> str:
    return os.getenv("ANTHROPIC_MODEL_DEFAULT", "claude-haiku-4-5-20251001")


def _max_tokens() -> int:
    try:
        return max(1, int(os.getenv("CHAT_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))))
    except ValueError:
        return _DEFAULT_MAX_TOKENS


async def call(
    *,
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Non-streaming. Returns the assistant Message dict.

    Used by intent_classifier (no tools, short output) and by upgraded
    agents that want a one-shot summary (email_summarizer, pr_reviewer,
    code_summarizer).
    """
    kwargs: dict[str, Any] = {
        "model": model or _default_model(),
        "max_tokens": max_tokens or _max_tokens(),
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    msg = await _client().messages.create(**kwargs)
    return msg.model_dump()


async def stream(
    *,
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Async generator yielding tagged events.

    Caller (chat.py) is responsible for the agentic loop: when 'tool_use'
    arrives, run the tool, append a tool_result message, re-invoke
    ``stream`` with the updated history.
    """
    kwargs: dict[str, Any] = {
        "model": model or _default_model(),
        "max_tokens": max_tokens or _max_tokens(),
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    pending_tool_uses: dict[int, dict[str, Any]] = {}
    pending_tool_input: dict[int, list[str]] = {}

    async with _client().messages.stream(**kwargs) as resp:
        async for event in resp:
            etype = getattr(event, "type", None)

            if etype == "content_block_start":
                block = event.content_block
                if getattr(block, "type", None) == "tool_use":
                    pending_tool_uses[event.index] = {
                        "id": block.id,
                        "name": block.name,
                        "input": {},
                    }
                    pending_tool_input[event.index] = []

            elif etype == "content_block_delta":
                delta = event.delta
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    yield "delta", delta.text
                elif dtype == "input_json_delta":
                    pending_tool_input.setdefault(event.index, []).append(
                        delta.partial_json
                    )

            elif etype == "content_block_stop":
                if event.index in pending_tool_uses:
                    block_meta = pending_tool_uses.pop(event.index)
                    raw = "".join(pending_tool_input.pop(event.index, []))
                    try:
                        import json as _json

                        block_meta["input"] = _json.loads(raw) if raw else {}
                    except Exception:
                        block_meta["input"] = {}
                    yield "tool_use", block_meta

            elif etype == "message_delta":
                usage = getattr(event, "usage", None)
                if usage is not None:
                    yield (
                        "usage",
                        {
                            "input_tokens": getattr(usage, "input_tokens", None),
                            "output_tokens": getattr(usage, "output_tokens", None),
                        },
                    )

    yield "done", None
