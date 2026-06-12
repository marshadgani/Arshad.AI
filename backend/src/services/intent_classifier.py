"""Stage 1 of two-stage routing — picks a domain.

Cheap Haiku call with a tight prompt. Returns one of:
  calendar | email | github | general

Heuristic fast-path for messages that obviously match a single domain
(short keyword check) skips the LLM call entirely. The LLM is only
invoked when the message is ambiguous or has no domain keywords.
"""

from __future__ import annotations

from typing import Literal

from . import ai

Intent = Literal["calendar", "email", "github", "obsidian", "general"]

_VALID_INTENTS: tuple[Intent, ...] = (
    "calendar",
    "email",
    "github",
    "obsidian",
    "general",
)

_FAST_PATH_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    "calendar": (
        "calendar",
        "schedule",
        "meeting",
        "event",
        "free slot",
        "free time",
        "availability",
        "appointment",
        " agenda",
    ),
    "email": (
        "email",
        "inbox",
        "gmail",
        "thread",
        "draft a reply",
        "send an email",
        "label this",
        "unread",
    ),
    "github": (
        "github",
        "pull request",
        " pr ",
        " prs ",
        "issue",
        "issues",
        "repo",
        "commit",
        "diff",
    ),
    "obsidian": (
        "obsidian",
        "vault",
        "my note",
        "my notes",
        "my writing",
        "second brain",
        "knowledge base",
        "what did i write",
        "i wrote",
    ),
}


_SYSTEM_PROMPT = """\
Classify the user's last message into one domain. Reply with EXACTLY ONE word from this list:

  calendar  - if it's about meetings, events, scheduling, availability
  email     - if it's about Gmail, threads, drafting, labels
  github    - if it's about repos, issues, PRs, commits, code review
  obsidian  - if it's about notes, vault, knowledge base, second brain, or asking what the user wrote
  general   - if it doesn't fit any of the above

Output the single word, nothing else. No punctuation, no explanation.
"""


def _fast_path(text: str) -> Intent | None:
    lowered = f" {text.lower()} "
    for intent, keywords in _FAST_PATH_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return intent
    return None


async def classify(message: str, history: list[dict] | None = None) -> Intent:
    """Returns the domain. Uses keyword fast-path first, falls back to Haiku."""
    fast = _fast_path(message)
    if fast is not None:
        return fast

    history = history or []
    short_history = history[-4:]
    convo = [
        *short_history,
        {"role": "user", "content": message},
    ]
    msg = await ai.call(
        system=_SYSTEM_PROMPT,
        messages=convo,
        max_tokens=8,
        # Intent classification is the canonical Haiku job per the 3-tier
        # strategy: 1-token output, verifiable in one read.
        model="claude-haiku-4-5-20251001",
    )
    raw = ""
    for block in msg.get("content", []):
        if block.get("type") == "text":
            raw += block.get("text", "")
    candidate = raw.strip().lower().split()[0] if raw.strip() else "general"
    if candidate in _VALID_INTENTS:
        return candidate  # type: ignore[return-value]
    return "general"
