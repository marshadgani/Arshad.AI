"""Command-line entry for the dev-team pipeline.

Usage:
    python -m src.dev_team.cli "<requirement text>"
    python -m src.dev_team.cli --dry-run "<requirement>"

Auto-invoked by Claude Code per CLAUDE.md §21 whenever the user prompt
classifies as a feature requirement.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .pipeline import Pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dev-team")
    parser.add_argument(
        "requirement",
        help="The feature requirement, in plain language.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline but skip the live-write + commit step. "
        "Generated code stays in tasks/agent-outputs/dev/ only.",
    )
    args = parser.parse_args(argv)

    pipeline = Pipeline(dry_run=args.dry_run)
    result = asyncio.run(pipeline.run(args.requirement))

    if result.status == "completed":
        print(f"\n✅ {result.feature_id} completed in {result.duration_seconds:.1f}s.")
        for label, path in result.artifact_paths.items():
            print(f"   {label}: {path}")
        return 0
    print(f"\n❌ {result.feature_id} {result.status}: {result.halt_reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
