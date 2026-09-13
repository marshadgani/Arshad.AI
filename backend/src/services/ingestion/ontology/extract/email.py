"""Pass 0 — Email extractor.

Emits a Thread EntityRecord per ``ingested_gmail_threads`` row within the
lookback window. Gmail's ``threads.list`` only returns
``{id, snippet, historyId}`` — participant emails are not currently
present in ``raw`` (see FEAT-141 system design, "email_person_gap").
Thread -> Person links are therefore gated behind
``ONTOLOGY_EMAIL_PEOPLE`` (default off) and only ever emitted when a
row's ``raw['_derived']['participants']`` key is present — the extractor
never treats its absence as an error, since most threads won't have it
until the enrichment cap is widened.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.ingested import IngestedGmailThread
from .....models.user import User
from ..config import OntologyConfig
from ..identity import normalize_email, person_id_from_email
from ..models import EntityRecord, RelationshipRef


def _email_people_enabled() -> bool:
    return os.getenv("ONTOLOGY_EMAIL_PEOPLE", "false").strip().lower() == "true"


def _participants(derived: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for p in derived.get("participants") or []:
        email = (p.get("email") or "").strip()
        if not email:
            continue
        out.append({"email": email, "name": p.get("name") or email})
    return out


async def extract(
    user: User, db: AsyncSession, cfg: OntologyConfig
) -> list[EntityRecord]:
    since = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    rows = await db.scalars(
        select(IngestedGmailThread)
        .where(
            IngestedGmailThread.user_id == user.id,
            IngestedGmailThread.occurred_at >= since,
        )
        .order_by(IngestedGmailThread.occurred_at.desc())
    )

    entities: list[EntityRecord] = []
    seen_people: dict[str, EntityRecord] = {}
    people_enabled = _email_people_enabled()

    for row in rows:
        raw = row.raw or {}
        derived = raw.get("_derived") or {}
        subject = derived.get("subject") or raw.get("snippet") or "(no subject)"
        labels = derived.get("labels") or []
        relationships: list[RelationshipRef] = []

        if people_enabled:
            for p in _participants(derived):
                person_id = person_id_from_email(p["email"])
                relationships.append(RelationshipRef("participant", person_id))
                if person_id not in seen_people:
                    seen_people[person_id] = EntityRecord(
                        entity_type="Person",
                        stable_entity_id=person_id,
                        display_name=p["name"],
                        domain="people",
                        source_id=normalize_email(p["email"]),
                        source_updated_at=row.occurred_at,
                        raw_fields={"email": normalize_email(p["email"])},
                    )

        entities.append(
            EntityRecord(
                entity_type="Thread",
                stable_entity_id=f"thread:{row.provider_id}",
                display_name=subject,
                domain="email",
                source_id=row.provider_id,
                source_updated_at=row.occurred_at,
                relationships=relationships,
                tags=[f"gmail/{lbl.lower()}" for lbl in labels],
                raw_fields={"labels": labels, "snippet": raw.get("snippet")},
            )
        )

    entities.extend(seen_people.values())
    return entities
