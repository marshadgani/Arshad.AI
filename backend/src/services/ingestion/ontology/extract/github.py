"""Pass 0 — GitHub extractor.

Emits, per ``ingested_github_activity`` row within the lookback window:
an IssuePR entity, the Repo entity it belongs to (deduped across rows —
a repo appears once no matter how many issues/PRs reference it), and a
Person entity for the actor (author). GitHub actors carry a login but
often no public email, so identity falls back to
``person:gh:{login}`` rather than being dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.ingested import IngestedGitHubActivity
from .....models.user import User
from ..config import OntologyConfig
from ..identity import person_id_from_email, person_id_from_github_login
from ..models import EntityRecord, RelationshipRef


def _actor_person_id(actor: dict[str, Any]) -> tuple[str, str] | None:
    login = (actor.get("login") or "").strip()
    email = (actor.get("email") or "").strip()
    if email:
        return person_id_from_email(email), (actor.get("name") or login or email)
    if login:
        return person_id_from_github_login(login), login
    return None


async def extract(
    user: User, db: AsyncSession, cfg: OntologyConfig
) -> list[EntityRecord]:
    since = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    rows = await db.scalars(
        select(IngestedGitHubActivity)
        .where(
            IngestedGitHubActivity.user_id == user.id,
            IngestedGitHubActivity.occurred_at >= since,
        )
        .order_by(IngestedGitHubActivity.occurred_at.desc())
    )

    entities: list[EntityRecord] = []
    seen_repos: dict[str, EntityRecord] = {}
    seen_people: dict[str, EntityRecord] = {}

    for row in rows:
        raw = row.raw or {}
        repo_slug = row.provider_id.split("#", 1)[0]
        repo_id = f"repo:{repo_slug}"
        relationships: list[RelationshipRef] = [RelationshipRef("in_repo", repo_id)]

        actor = raw.get("user") or {}
        actor_result = _actor_person_id(actor)
        if actor_result:
            person_id, person_name = actor_result
            relationships.append(RelationshipRef("authored_by", person_id))
            if person_id not in seen_people:
                seen_people[person_id] = EntityRecord(
                    entity_type="Person",
                    stable_entity_id=person_id,
                    display_name=person_name,
                    domain="people",
                    source_id=actor.get("login") or person_id,
                    source_updated_at=row.occurred_at,
                    raw_fields={"github_login": actor.get("login")},
                )

        title = raw.get("title") or f"{row.kind} #{raw.get('number', '?')}"
        entities.append(
            EntityRecord(
                entity_type="IssuePR",
                stable_entity_id=f"issue_pr:{row.provider_id}",
                display_name=f"{title} ({row.provider_id})",
                domain="github",
                source_id=row.provider_id,
                source_updated_at=row.occurred_at,
                relationships=relationships,
                tags=[f"github/{row.kind}", raw.get("state") or ""],
                raw_fields={
                    "kind": row.kind,
                    "state": raw.get("state"),
                    "html_url": raw.get("html_url"),
                    "repo": repo_slug,
                },
            )
        )

        # A repo appears once, carrying its most recent activity date.
        known_repo = seen_repos.get(repo_id)
        is_newer = (
            known_repo is not None
            and row.occurred_at
            and known_repo.source_updated_at
            and row.occurred_at > known_repo.source_updated_at
        )
        if known_repo is None or is_newer:
            seen_repos[repo_id] = EntityRecord(
                entity_type="Repo",
                stable_entity_id=repo_id,
                display_name=repo_slug,
                domain="github",
                source_id=repo_slug,
                source_updated_at=row.occurred_at,
                raw_fields={"slug": repo_slug},
            )

    entities.extend(seen_repos.values())
    entities.extend(seen_people.values())
    return entities
