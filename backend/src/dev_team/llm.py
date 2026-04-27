"""Anthropic SDK wrapper for the dev-team pipeline.

structured_call() — runs a single Claude request with tool-use as the
structured-output mechanism. Each agent declares an `output_schema`
(Pydantic model); we convert it to a tool's input_schema and force the
model to call that single tool. The tool's `input` argument IS the
agent's output — guaranteed-validated by Pydantic on return.

Why tool-use rather than free-text JSON parsing:
  - Anthropic's models hit far higher schema-conformance rates when
    the schema is presented as a tool's input_schema vs. described in
    a system prompt.
  - tool_choice={'type': 'tool', 'name': ...} forces the call.
  - Validation failures are deterministic (Pydantic raises) instead of
    free-text parsing flakes.
"""

from __future__ import annotations

import os
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 4096

T = TypeVar("T", bound=BaseModel)


def _client() -> AsyncAnthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=api_key)


def _model() -> str:
    return os.getenv("DEV_TEAM_MODEL", _DEFAULT_MODEL)


async def structured_call(
    *,
    system: str,
    user_message: str,
    output_schema: type[T],
    max_tokens: int | None = None,
    tool_name: str = "submit_result",
    tool_description: str | None = None,
) -> T:
    """Single Claude turn with forced tool-use as the structured-output channel.

    Returns a validated instance of ``output_schema``. Raises on:
      - missing ANTHROPIC_API_KEY
      - SDK / network errors (propagate)
      - schema validation failure (pydantic.ValidationError)
      - model declined to call the tool (RuntimeError)
    """
    schema = output_schema.model_json_schema()
    tool = {
        "name": tool_name,
        "description": tool_description
        or f"Submit the result as a {output_schema.__name__}.",
        "input_schema": schema,
    }
    msg = await _client().messages.create(
        model=_model(),
        max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            try:
                return output_schema.model_validate(block.input)
            except ValidationError as exc:
                raise RuntimeError(
                    f"{output_schema.__name__} validation failed: {exc}"
                ) from exc
    raise RuntimeError(f"Model did not call the {tool_name} tool. Got: {msg.content!r}")


async def free_text_call(
    *,
    system: str,
    user_message: str,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Plain text Claude call. Used by the intent classifier."""
    msg = await _client().messages.create(
        model=model or _model(),
        max_tokens=max_tokens or 256,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()
