"""The single registry of exportable domains.

One record per domain, holding everything the router and the exporter
need to know about it. Keeping model, renderer, source table and privacy
policy on one record is what stops the router accepting a domain the
exporter has no renderer for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...models.ingested import (
    IngestedCalendarEvent,
    IngestedGitHubActivity,
    IngestedGmailThread,
)
from .config import ExportConfig
from .renderers import (
    RenderedNote,
    render_calendar_note,
    render_email_note,
    render_github_note,
)


@dataclass(frozen=True)
class ExportDomain:
    """How one Arshad.AI data domain maps onto vault notes."""

    name: str
    model: type[Any]
    renderer: Callable[[Any, ExportConfig], RenderedNote]
    source_table: str
    # When True the export is refused unless the vault repo is *confirmed*
    # private. GitHub activity is exempt: it mirrors the user's own GitHub
    # data from a repo they can already read, so it carries nothing the
    # vault's visibility could newly expose.
    requires_private_vault: bool


EXPORT_DOMAINS: tuple[ExportDomain, ...] = (
    ExportDomain(
        name="calendar",
        model=IngestedCalendarEvent,
        renderer=render_calendar_note,
        source_table="ingested_calendar_events",
        requires_private_vault=True,
    ),
    ExportDomain(
        name="email",
        model=IngestedGmailThread,
        renderer=render_email_note,
        source_table="ingested_gmail_threads",
        requires_private_vault=True,
    ),
    ExportDomain(
        name="github",
        model=IngestedGitHubActivity,
        renderer=render_github_note,
        source_table="ingested_github_activity",
        requires_private_vault=False,
    ),
)

DOMAIN_NAMES: tuple[str, ...] = tuple(d.name for d in EXPORT_DOMAINS)

_BY_NAME: dict[str, ExportDomain] = {d.name: d for d in EXPORT_DOMAINS}


def get_domain(name: str) -> ExportDomain:
    return _BY_NAME[name]


def select_domains(requested: list[str] | None) -> list[ExportDomain]:
    """Resolve a requested domain-name list to registry order.

    Registry order wins over caller order, and unknown names are dropped
    — the router has already rejected those with a 422.
    """
    if not requested:
        return list(EXPORT_DOMAINS)
    return [d for d in EXPORT_DOMAINS if d.name in requested]


__all__ = [
    "DOMAIN_NAMES",
    "EXPORT_DOMAINS",
    "ExportDomain",
    "get_domain",
    "select_domains",
]
