"""Pass 0 — Calendar extractor.

Emits an Event EntityRecord per ``ingested_calendar_events`` row within
the lookback window, plus one Person EntityRecord per attendee email
(deduped within this extractor by normalized email — cross-domain dedup
across extractors happens in the resolver, since two extractors may
reference the same person).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.ingested import IngestedCalendarEvent
from .....models.user import User
from ..config import OntologyConfig
from ..identity import normalize_email, person_id_from_email
from ..models import EntityRecord, RelationshipRef


def _attendees(raw: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for att in raw.get("attendees") or []:
        email = (att.get("email") or "").strip()
        if not email:
            continue
        out.append({"email": email, "name": att.get("displayName") or email})
    return out


async def extract(
    user: User, db: AsyncSession, cfg: OntologyConfig
) -> list[EntityRecord]:
    since = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    rows = await db.scalars(
        select(IngestedCalendarEvent)
        .where(
            IngestedCalendarEvent.user_id == user.id,
            IngestedCalendarEvent.occurred_at >= since,
        )
        .order_by(IngestedCalendarEvent.occurred_at.desc())
    )

    entities: list[EntityRecord] = []
    seen_people: dict[str, EntityRecord] = {}

    for row in rows:
        raw = row.raw or {}
        title = raw.get("summary") or "(untitled event)"
        attendees = _attendees(raw)
        relationships: list[RelationshipRef] = []

        for att in attendees:
            person_id = person_id_from_email(att["email"])
            relationships.append(RelationshipRef("attended_by", person_id))
            if person_id not in seen_people:
                seen_people[person_id] = EntityRecord(
                    entity_type="Person",
                    stable_entity_id=person_id,
                    display_name=att["name"],
                    domain="people",
                    source_id=normalize_email(att["email"]),
                    source_updated_at=row.occurred_at,
                    raw_fields={"email": normalize_email(att["email"])},
                )

        entities.append(
            EntityRecord(
                entity_type="Event",
                stable_entity_id=f"event:{row.provider_id}",
                display_name=title,
                domain="calendar",
                source_id=row.provider_id,
                source_updated_at=row.occurred_at,
                relationships=relationships,
                raw_fields={
                    "location": raw.get("location"),
                    "attendee_count": len(attendees),
                    "html_link": raw.get("htmlLink"),
                },
            )
        )

    entities.extend(seen_people.values())
    return entities
