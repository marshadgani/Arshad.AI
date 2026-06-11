"""Register or update an agent in the AI Ecosystem registry.

Parses a .md agent file OR accepts explicit flags. Upserts into agent_registry.

Usage (inside container):
  python -m scripts.register_agent --file /app/.claude/agents/n8n-mcp/code-reviewer.md
  python -m scripts.register_agent --name my-agent --display "My Agent" --purpose "Does X"

Usage (from host via docker compose):
  docker compose exec backend python -m scripts.register_agent --file /app/.claude/agents/n8n-mcp/code-reviewer.md
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.ai_ecosystem import AgentRegistry  # noqa: E402


def _parse_md(path: str) -> dict:
    """Extract agent metadata from a .md agent definition file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    filename = os.path.basename(path).removesuffix(".md")

    # display_name: first # heading, else title-case the filename
    h1 = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    display_name = h1.group(1).strip() if h1 else filename.replace("-", " ").title()

    # purpose: first non-empty paragraph that isn't a heading or code block
    purpose = filename  # fallback
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or line.startswith("#") or not line.strip():
            continue
        purpose = re.sub(r"[*_`]", "", line.strip())[:250]
        break

    # model: detect from content
    model = "claude-sonnet-4-6"
    lower = text.lower()
    if "opus" in lower:
        model = "claude-opus-4-8"
    elif "haiku" in lower:
        model = "claude-haiku-4-5-20251001"

    return {
        "agent_name": filename,
        "display_name": display_name,
        "purpose": purpose,
        "model": model,
    }


async def _upsert(args: argparse.Namespace) -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/arshad_ai",
    )
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        existing = await session.scalar(
            select(AgentRegistry).where(AgentRegistry.agent_name == args.name)
        )
        if existing:
            existing.display_name = args.display
            existing.purpose = args.purpose
            existing.model = args.model
            existing.category = args.category
            if args.stage is not None:
                existing.pipeline_stage = args.stage
            existing.is_active = True
            print(f"Updated:    {args.name}  [{args.category}]")
        else:
            session.add(
                AgentRegistry(
                    id=uuid.uuid4(),
                    agent_name=args.name,
                    display_name=args.display,
                    purpose=args.purpose,
                    model=args.model,
                    category=args.category,
                    pipeline_stage=args.stage,
                    is_active=True,
                )
            )
            print(f"Registered: {args.name}  [{args.category}]")
        await session.commit()

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register an agent in the AI Ecosystem"
    )
    parser.add_argument(
        "--file", help="Path to agent .md file (auto-extracts metadata)"
    )
    parser.add_argument("--name", help="agent_name slug (overrides --file filename)")
    parser.add_argument("--display", help="Human-readable display name")
    parser.add_argument("--purpose", help="One-sentence purpose description")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument(
        "--category", default="other", choices=["development_team", "other"]
    )
    parser.add_argument(
        "--stage", type=int, default=None, help="Pipeline stage (dev-team only)"
    )
    args = parser.parse_args()

    if args.file:
        meta = _parse_md(args.file)
        if not args.name:
            args.name = meta["agent_name"]
        if not args.display:
            args.display = meta["display_name"]
        if not args.purpose:
            args.purpose = meta["purpose"]
        if args.model == "claude-sonnet-4-6":
            args.model = meta["model"]

    missing = [
        f"--{k}"
        for k, v in {
            "name": args.name,
            "display": args.display,
            "purpose": args.purpose,
        }.items()
        if not v
    ]
    if missing:
        parser.error(f"Missing required: {', '.join(missing)}  (or pass --file)")

    asyncio.run(_upsert(args))


if __name__ == "__main__":
    main()
