"""Thin async wrapper around the Anthropic SDK.

Single instantiation point for the Claude client (migration seam for a future
`services/ai.py`). All Claude calls in the app should route through here.
"""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic

_client: AsyncAnthropic | None = None


def get_ai_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


async def generate_text(prompt: str, *, model: str, max_tokens: int = 300) -> str:
    client = get_ai_client()
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    raise ValueError("Claude response contained no text content block")
