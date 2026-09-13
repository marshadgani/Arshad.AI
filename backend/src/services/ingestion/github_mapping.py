"""Pure translation of GitHub API payloads into activity rows.

This layer is deliberately free of I/O: no session, no tool client, no
network, no SQLAlchemy. It knows two things only — the shape GitHub sends
and the shape ``ingested_github_activity`` stores — so a change to
GitHub's response format is confined to this file, and the rules it
encodes (which items are dropped, how ``provider_id`` is composed) can be
exercised directly without a database or a fake provider.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

ActivityKind = Literal["issue", "pr"]


@dataclass(frozen=True)
class MappedBatch:
    """One repo-and-kind's worth of mapping output — rows kept, rows dropped."""

    rows: list[dict[str, Any]]
    skipped_count: int


def build_provider_id(repo: str, number: int) -> str:
    """Namespace an item number by its repo.

    GitHub numbers issues and PRs per-repo, so ``#3`` is ambiguous across
    the repos a user has linked. ``kind`` is a separate column, so this
    only has to disambiguate repos — issue#3 and pr#3 in the same repo
    share this value but differ on ``kind``, which is why the unique
    constraint is (user_id, kind, provider_id).
    """
    return f"{repo}#{number}"


def parse_github_timestamp(value: str | None) -> datetime | None:
    """Strictly parse a GitHub ISO-8601 timestamp.

    Returns ``None`` on missing/unparseable input — never
    ``datetime.now()``. ``occurred_at`` is the feed's sort key; silently
    promoting a malformed item to "now" would pin it permanently at the
    top of the widget.

    Checks ``isinstance(value, str)`` before touching it: ``value`` is
    untrusted third-party JSON, and GitHub's own contract (always a
    string or null) is not a guarantee against a malformed proxy/response
    body handing us an int, list or dict instead. Without that check, a
    non-string value raises ``AttributeError`` out of ``.replace()`` —
    and ``github.py`` isolates only ``ToolError``/``httpx.HTTPError``/
    ``SQLAlchemyError`` per repo, so that would abort every remaining
    repo in the run rather than skipping one malformed item.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_activity_rows(
    *,
    user_id: uuid.UUID,
    repo: str,
    kind: ActivityKind,
    items: list[dict[str, Any]],
) -> MappedBatch:
    """Map raw GitHub items to upsert rows, dropping unusable ones.

    Two classes of item are skipped: those with no ``number`` (no stable
    identity, so nothing to upsert against) and those whose ``updated_at``
    is missing or unparseable (no trustworthy sort key). Both are counted;
    only the latter is logged, since a numberless item indicates a
    malformed response rather than a data-quality issue worth alerting on.
    """
    rows: list[dict[str, Any]] = []
    skipped = 0

    for item in items:
        number = item.get("number")
        if number is None:
            skipped += 1
            continue

        occurred_at = parse_github_timestamp(item.get("updated_at"))
        if occurred_at is None:
            skipped += 1
            logger.warning(
                "github_ingest_skipped_malformed_updated_at",
                extra={"repo": repo, "kind": kind, "number": number},
            )
            continue

        rows.append(
            {
                "user_id": user_id,
                "occurred_at": occurred_at,
                "provider_id": build_provider_id(repo, number),
                "kind": kind,
                "raw": item,
            }
        )

    return MappedBatch(rows=rows, skipped_count=skipped)
