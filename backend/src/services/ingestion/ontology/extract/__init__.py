"""Pass 0 — per-domain, pure-DB extractors, plus the registry over them.

Each sibling module exposes ``async def extract(user, db, cfg) -> list[EntityRecord]``.
Zero network I/O — extractors only read already-ingested Postgres rows
(``ingested_calendar_events``, ``ingested_gmail_threads``,
``ingested_github_activity``). Materiality filtering (lookback window,
per-domain cap) happens there so Pass 1 onward never sees more
candidates than the run's budget allows.

``collect()`` is the registry: it owns which domain maps to which
extractor and the run-wide ``max_entities`` ceiling. The orchestrator
asks for candidates and gets candidates — adding a domain means adding a
module and one dict entry here, and touching nothing downstream.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.user import User
from ..config import OntologyConfig
from ..models import EntityRecord, recency_desc_key
from . import calendar as calendar_extractor
from . import email as email_extractor
from . import github as github_extractor

Extractor = Callable[
    [User, AsyncSession, OntologyConfig], Awaitable[list[EntityRecord]]
]

EXTRACTORS: Mapping[str, Extractor] = {
    "calendar": calendar_extractor.extract,
    "email": email_extractor.extract,
    "github": github_extractor.extract,
}


async def collect(
    user: User, db: AsyncSession, cfg: OntologyConfig
) -> list[EntityRecord]:
    """Every candidate entity for this run, capped at ``cfg.max_entities``.

    Domains with no registered extractor are skipped rather than raising:
    ``OntologyConfig`` already rejects unknown domain names, so anything
    reaching here unregistered is a domain that exists but has no reader
    yet.
    """
    entities: list[EntityRecord] = []
    for domain in cfg.domains:
        extractor = EXTRACTORS.get(domain)
        if extractor is None:
            continue
        entities.extend(await extractor(user, db, cfg))

    if len(entities) > cfg.max_entities:
        # Deterministic ceiling: most-recently-updated entities win a
        # contested slot, ties broken by stable_entity_id ascending.
        entities.sort(key=recency_desc_key)
        entities = entities[: cfg.max_entities]
    return entities
