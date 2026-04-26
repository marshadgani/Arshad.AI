"""ai_core/council_chairman — multi-model panel + chairman synthesis.

Inspired by karpathy/llm-council. Three stages:

  Stage 1  parallel · each panel model answers the question independently
  Stage 2  parallel · each panel model sees the others' anonymised answers
                      and rates them (skip with enable_review=False)
  Stage 3  single   · chairman model (default Opus 4.7) reads everything
                      and produces the final synthesis

Use this when the user asks for a panel review, a "what should we do?" call,
or wants multiple Claude models to weigh in on a high-stakes decision.

Cost note: a 3-model panel with review = 7 LLM calls (~$0.30-0.80 per run
depending on input length). Without review = 4 calls. The default panel is
Opus / Sonnet / Haiku — three different model families weighing in.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...services import ai
from ..base import Agent, AgentError
from ..registry import register

_DEFAULT_PANEL = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

_DEFAULT_CHAIRMAN = "claude-opus-4-7"


_PANELIST_SYSTEM = (
    "You are one member of an LLM panel. Answer the user's question directly "
    "and concisely. Lead with your conclusion, then give the reasoning. Do not "
    "mention that you are part of a panel or that other models will see your "
    "answer."
)

_REVIEWER_SYSTEM = (
    "You are reviewing answers from other panel members. The answers below are "
    "anonymised (Model A, Model B, ...). Rank them from best to worst on "
    "accuracy, clarity, and insight. For each, give a one-sentence critique. "
    "Be honest — if an answer is weak, say so. Output strict JSON in this "
    'shape: {"rankings": [{"label": "A", "rank": 1, "critique": "..."}, ...]}'
)

_CHAIRMAN_SYSTEM = (
    "You are the Chairman of an LLM council. You will receive: (1) the user's "
    "original question, (2) the panel's individual answers, (3) the panel's "
    "cross-rankings of each other (if any). Your job is to produce the single "
    "best final answer the user will actually see. Synthesise — don't pick one "
    "and discard the rest. Where the panel disagrees, name the disagreement and "
    "decide. Where the panel agrees, state the consensus once. Lead with the "
    "answer; keep reasoning tight."
)


class CouncilInput(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    panel_models: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_PANEL),
        min_length=1,
        max_length=10,
    )
    chairman_model: str = Field(default=_DEFAULT_CHAIRMAN)
    enable_review: bool = Field(
        default=True,
        description="If False, skip the cross-ranking stage (saves 3 LLM calls).",
    )
    max_panelist_tokens: int = Field(default=1024, ge=64, le=8192)
    max_chairman_tokens: int = Field(default=2048, ge=128, le=8192)


class PanelOpinion(BaseModel):
    model: str
    label: str
    response: str
    error: str | None = None


class PanelRanking(BaseModel):
    reviewer_model: str
    rankings: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class CouncilSummary(BaseModel):
    final_answer: str
    panel_size: int
    panel_models: list[str]
    chairman_model: str
    review_enabled: bool
    failures: int


class CouncilOutput(BaseModel):
    data: dict[str, Any]
    summary: CouncilSummary


def _label_for(idx: int) -> str:
    return chr(ord("A") + idx) if 0 <= idx < 26 else f"P{idx}"


def _extract_text(msg: dict[str, Any]) -> str:
    return "".join(
        block.get("text", "")
        for block in msg.get("content", [])
        if block.get("type") == "text"
    )


async def _panelist_call(
    *, model: str, question: str, max_tokens: int
) -> tuple[str, str | None]:
    """Returns (response_text, error). Either text is non-empty or error is."""
    try:
        msg = await ai.call(
            model=model,
            system=_PANELIST_SYSTEM,
            messages=[{"role": "user", "content": question}],
            max_tokens=max_tokens,
        )
        text = _extract_text(msg)
        return text or "(empty response)", None
    except Exception as exc:  # noqa: BLE001 — surface as panel failure, don't abort
        return "", f"{type(exc).__name__}: {exc}"


async def _reviewer_call(
    *,
    model: str,
    question: str,
    anonymised_block: str,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (rankings, error). rankings is list of {label, rank, critique}."""
    user_prompt = (
        f"Original question:\n{question}\n\n"
        f"Anonymised panel answers:\n{anonymised_block}\n\n"
        "Output the JSON rankings now."
    )
    try:
        msg = await ai.call(
            model=model,
            system=_REVIEWER_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
        )
        text = _extract_text(msg)
        import json as _json

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return [], "no JSON object in response"
        parsed = _json.loads(text[start : end + 1])
        rankings = parsed.get("rankings", [])
        if not isinstance(rankings, list):
            return [], "rankings field is not a list"
        return rankings, None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def _build_anonymised_block(opinions: list[PanelOpinion]) -> str:
    parts = []
    for op in opinions:
        if op.error:
            continue
        parts.append(f"--- Model {op.label} ---\n{op.response}\n")
    return "\n".join(parts) if parts else "(no answers — panel failed)"


def _build_chairman_prompt(
    question: str,
    opinions: list[PanelOpinion],
    rankings: list[PanelRanking],
    review_enabled: bool,
) -> str:
    out = [f"User's question:\n{question}\n"]

    out.append("\n=== Panel answers ===\n")
    for op in opinions:
        if op.error:
            out.append(f"\n[Model {op.label} ({op.model}) FAILED: {op.error}]\n")
        else:
            out.append(f"\n[Model {op.label} ({op.model})]\n{op.response}\n")

    if review_enabled and rankings:
        out.append("\n=== Panel cross-rankings (anonymised labels) ===\n")
        for rk in rankings:
            if rk.error:
                out.append(f"\n[Reviewer {rk.reviewer_model} FAILED: {rk.error}]\n")
                continue
            out.append(f"\n[Reviewer {rk.reviewer_model}]\n")
            for r in rk.rankings:
                lbl = r.get("label", "?")
                rank = r.get("rank", "?")
                crit = r.get("critique", "")
                out.append(f"  Model {lbl}: rank {rank} — {crit}\n")

    out.append(
        "\n=== Your task ===\n"
        "Produce the final answer the user will see. Synthesise the panel — "
        "don't just pick one. If the panel disagrees, name the disagreement "
        "and resolve it. Lead with the answer."
    )
    return "".join(out)


async def _chairman_call(
    *,
    model: str,
    question: str,
    opinions: list[PanelOpinion],
    rankings: list[PanelRanking],
    review_enabled: bool,
    max_tokens: int,
) -> str:
    prompt = _build_chairman_prompt(question, opinions, rankings, review_enabled)
    msg = await ai.call(
        model=model,
        system=_CHAIRMAN_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    text = _extract_text(msg)
    return text or "(chairman returned empty)"


@register
class CouncilChairmanAgent(Agent):
    domain = "ai_core"
    name = "council_chairman"
    description = (
        "Multi-model LLM council. Sends the question to a panel of Claude "
        "models in parallel, has them anonymously rank each other's answers, "
        "then a chairman model synthesises the final answer. Use for "
        "high-stakes decisions, architectural calls, ambiguous questions "
        "where multiple perspectives matter, or when the user explicitly "
        "asks for a panel/council review. Default panel: Opus 4.7, Sonnet "
        "4.6, Haiku 4.5. Default chairman: Opus 4.7."
    )
    input_schema = CouncilInput
    output_schema = CouncilOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CouncilOutput:
        assert isinstance(payload, CouncilInput)

        if not os.getenv("ANTHROPIC_API_KEY"):
            raise AgentError(
                "missing_api_key",
                "ANTHROPIC_API_KEY is not set; the council needs SDK access.",
            )

        panel = payload.panel_models or list(_DEFAULT_PANEL)
        if not panel:
            raise AgentError("empty_panel", "panel_models cannot be empty.")

        # ── Stage 1: parallel panel answers ──────────────────────────────
        stage1 = await asyncio.gather(
            *[
                _panelist_call(
                    model=m,
                    question=payload.question,
                    max_tokens=payload.max_panelist_tokens,
                )
                for m in panel
            ],
            return_exceptions=False,
        )
        opinions = [
            PanelOpinion(model=panel[i], label=_label_for(i), response=text, error=err)
            for i, (text, err) in enumerate(stage1)
        ]

        if all(op.error for op in opinions):
            errs = "; ".join(f"{op.model}: {op.error}" for op in opinions)
            raise AgentError(
                "all_panelists_failed",
                f"Every panelist failed; refusing to synthesise. Errors: {errs}",
            )

        # ── Stage 2: parallel cross-rankings (optional) ──────────────────
        rankings: list[PanelRanking] = []
        if payload.enable_review:
            anon = _build_anonymised_block(opinions)
            stage2 = await asyncio.gather(
                *[
                    _reviewer_call(
                        model=m,
                        question=payload.question,
                        anonymised_block=anon,
                        max_tokens=payload.max_panelist_tokens,
                    )
                    for m in panel
                ],
                return_exceptions=False,
            )
            rankings = [
                PanelRanking(reviewer_model=panel[i], rankings=ranks, error=err)
                for i, (ranks, err) in enumerate(stage2)
            ]

        # ── Stage 3: chairman synthesis ──────────────────────────────────
        try:
            final = await _chairman_call(
                model=payload.chairman_model,
                question=payload.question,
                opinions=opinions,
                rankings=rankings,
                review_enabled=payload.enable_review,
                max_tokens=payload.max_chairman_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            raise AgentError(
                "chairman_failed",
                f"Chairman synthesis call failed: {type(exc).__name__}: {exc}",
            ) from exc

        failures = sum(1 for op in opinions if op.error) + sum(
            1 for rk in rankings if rk.error
        )

        return CouncilOutput(
            data={
                "question": payload.question,
                "opinions": [op.model_dump() for op in opinions],
                "rankings": [rk.model_dump() for rk in rankings],
                "chairman_model": payload.chairman_model,
                "chairman_response": final,
                "review_enabled": payload.enable_review,
            },
            summary=CouncilSummary(
                final_answer=final,
                panel_size=len(panel),
                panel_models=panel,
                chairman_model=payload.chairman_model,
                review_enabled=payload.enable_review,
                failures=failures,
            ),
        )
