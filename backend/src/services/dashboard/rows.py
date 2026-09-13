"""Defensive access to ingested rows, plus per-row fault isolation.

Ingested rows carry verbatim third-party JSONB under ``raw``, so every
field lookup here returns a safe default rather than raising — which is
what keeps ``projections`` free of ``isinstance`` noise and readable as a
plain field mapping.

Knows about *row shape*; knows nothing about which widget a row ends up in.
``project_all`` is the single place the package's "one bad row must not
kill the widget" contract is enforced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

from .formatting import extract_repo_from_provider_id

if TYPE_CHECKING:
    # Row types only. Every annotation in this module is a string thanks to
    # `from __future__ import annotations`, so importing the ORM models
    # costs nothing at runtime (no cycle, no I/O) and only feeds the type
    # checker — the package's "derivation does zero I/O" contract is
    # unaffected.
    from src.models.ingested import IngestedGmailThread

logger = logging.getLogger(__name__)

_RowT = TypeVar("_RowT")
_ItemT = TypeVar("_ItemT")


def raw_of(row: Any) -> dict[str, Any]:
    """``row.raw`` when it is a dict, else ``{}``."""
    raw = getattr(row, "raw", None)
    return raw if isinstance(raw, dict) else {}


def derived_of(row: IngestedGmailThread) -> dict[str, Any]:
    """``row.raw['_derived']`` when it is a dict, else ``{}``."""
    derived = raw_of(row).get("_derived")
    return derived if isinstance(derived, dict) else {}


def occurred_at_of(row: Any) -> datetime | None:
    """``row.occurred_at`` when it is a real datetime.

    Every projection formats this field for display, so a missing or
    non-datetime value drops the row rather than rendering a placeholder.
    """
    occurred_at = getattr(row, "occurred_at", None)
    return occurred_at if isinstance(occurred_at, datetime) else None


def parse_iso(value: Any) -> datetime | None:
    """Defensive ISO8601 parse for a raw JSONB string field.

    Private to the dashboard package — derivation has a stated zero-I/O /
    no-service-import contract, so this does not import ingestion's
    ``_parse_iso``. Accepts a trailing 'Z' (not handled by
    ``datetime.fromisoformat`` on older Python) by rewriting it to
    '+00:00'.
    """
    if not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def pr_opened_at(row: Any) -> datetime | None:
    """When a PR was actually opened, for elapsed-duration display.

    ``row.occurred_at`` tracks the ingestion pipeline's ``updated_at``
    (see ``services/ingestion/github.py``), which resets on every push or
    comment — using it here would make a PR opened nine days ago and
    commented on two minutes ago render "waiting just now", hiding exactly
    the backlog a decision queue exists to surface. ``raw['created_at']``
    is GitHub's true PR-open timestamp and is preferred; ``occurred_at`` is
    only a fallback for a row missing/malformed ``created_at``.
    """
    opened_at = parse_iso(raw_of(row).get("created_at"))
    if opened_at is not None:
        return opened_at
    return occurred_at_of(row)


def repo_or_github(row: Any) -> str:
    """Short repo name for a narrow display column, falling back to 'github'."""
    return (
        extract_repo_from_provider_id(getattr(row, "provider_id", "") or "") or "github"
    )


def project_all(
    rows: Sequence[_RowT],
    project: Callable[[_RowT], _ItemT | None],
    *,
    widget: str,
) -> list[_ItemT]:
    """Apply ``project`` to every row, dropping the ones it rejects (``None``)
    and the ones it raises on.

    This is the single place the "one bad row must not kill the widget"
    contract is enforced, so each projection stays a plain row->dict
    function with no error handling of its own. ``raw`` is untrusted
    third-party JSONB: the projections guard the shapes they know about,
    but cannot be exhaustive over every malformed payload.
    """
    items: list[_ItemT] = []
    for row in rows:
        try:
            item = project(row)
        except Exception:  # noqa: BLE001 — one bad row must not kill the widget
            logger.warning(
                "dashboard %s: skipping malformed row id=%s",
                widget,
                getattr(row, "id", "?"),
                exc_info=True,
            )
            continue
        if item is not None:
            items.append(item)
    return items
