"""Heuristic-first, LLM-fallback intent classifier.

Used by Claude Code (per CLAUDE.md §21) to decide whether a user prompt
is a feature requirement that should auto-trigger the dev-team pipeline.

Pipeline:
    1. Strip @build / @chat escape hatches first.
    2. Heuristic pass — keyword + length checks return one of:
         feature_requirement | not_feature | ambiguous
    3. If ambiguous, call Haiku 4.5 (fast, cheap) for the final verdict.

Cost: heuristics free, Haiku call ~200 tokens × $0.25/$1.25 per Mtok ≈ $0.0001.
"""

from __future__ import annotations

import re
from typing import Literal

from .llm import free_text_call

Verdict = Literal["feature_requirement", "not_feature", "ambiguous"]


_FEATURE_VERBS = {
    "build",
    "add",
    "implement",
    "create",
    "develop",
    "design",
    "make",
    "introduce",
    "construct",
}

_NON_FEATURE_PATTERNS = (
    re.compile(r"^\s*(why|how|what|when|where|who|which)\b", re.IGNORECASE),
    re.compile(r"^\s*(yes|no|ok|sure|continue|go|stop|cancel)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank you|nice|great)\b", re.IGNORECASE),
    re.compile(
        r"\b(fix|debug|investigate|diagnose)\s+(this|the|that)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(running|deploying|deployed|crash|crashed|error|exception)\b", re.IGNORECASE
    ),
)


def strip_escape_hatch(prompt: str) -> tuple[str, Verdict | None]:
    """Returns (cleaned_prompt, forced_verdict_or_None).

    @build → forces 'feature_requirement'
    @chat  → forces 'not_feature'
    """
    p = prompt.strip()
    if p.lower().startswith("@build"):
        return p[len("@build") :].strip(), "feature_requirement"
    if p.lower().startswith("@chat"):
        return p[len("@chat") :].strip(), "not_feature"
    return p, None


def heuristic_classify(prompt: str) -> Verdict:
    """Cheap synchronous classifier. Returns 'ambiguous' when uncertain."""
    p = prompt.strip()
    if len(p) < 12:
        return "not_feature"  # too short to be a real requirement

    for pat in _NON_FEATURE_PATTERNS:
        if pat.search(p):
            return "not_feature"

    words = re.findall(r"\b\w+\b", p.lower())
    has_verb = any(w in _FEATURE_VERBS for w in words[:5])
    long_enough = len(words) >= 6

    if has_verb and long_enough:
        return "feature_requirement"
    if has_verb or long_enough:
        return "ambiguous"
    return "not_feature"


_LLM_SYSTEM = (
    "You are an intent classifier for a personal AI assistant. "
    "Given a user prompt, decide whether it's a 'feature requirement' "
    "(asking to build new functionality / a new feature in the product), "
    "a 'not_feature' message (questions, diagnostics, conversational, "
    "trivial fixes), or 'ambiguous' (genuinely unclear). "
    "Respond with EXACTLY one of: feature_requirement | not_feature | ambiguous"
)


async def llm_classify(prompt: str) -> Verdict:
    """Final-arbiter Haiku call when heuristics return 'ambiguous'."""
    text = await free_text_call(
        system=_LLM_SYSTEM,
        user_message=f"Prompt:\n{prompt}",
        max_tokens=16,
        model="claude-haiku-4-5-20251001",
    )
    cleaned = text.strip().lower().split()[0] if text.strip() else "ambiguous"
    if cleaned == "feature_requirement":
        return "feature_requirement"
    if cleaned == "not_feature":
        return "not_feature"
    return "ambiguous"


async def classify(prompt: str) -> Verdict:
    """Public API. Heuristic first, LLM fallback on ambiguous."""
    cleaned, forced = strip_escape_hatch(prompt)
    if forced is not None:
        return forced
    verdict = heuristic_classify(cleaned)
    if verdict != "ambiguous":
        return verdict
    return await llm_classify(cleaned)
