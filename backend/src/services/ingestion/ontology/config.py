"""Run-scoped tunables, parsed once by the orchestrator and threaded
through every pass. Keeping this as one frozen dataclass (rather than a
raw dict) means every pass gets static typing on the knobs it reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_MAX_ENTITIES = 2000
HARD_MAX_ENTITIES = 5000
ALL_DOMAINS = ("calendar", "email", "github")


@dataclass(frozen=True)
class OntologyConfig:
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_entities: int = DEFAULT_MAX_ENTITIES
    domains: tuple[str, ...] = field(default_factory=lambda: ALL_DOMAINS)
    dry_run: bool = False

    @classmethod
    def from_payload(cls, payload: dict) -> "OntologyConfig":
        lookback_days = int(payload.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
        max_entities = int(payload.get("max_entities") or DEFAULT_MAX_ENTITIES)
        max_entities = min(max(max_entities, 1), HARD_MAX_ENTITIES)
        domains = payload.get("domains") or list(ALL_DOMAINS)
        domains = tuple(d for d in domains if d in ALL_DOMAINS) or ALL_DOMAINS
        return cls(
            lookback_days=max(1, lookback_days),
            max_entities=max_entities,
            domains=domains,
            dry_run=bool(payload.get("dry_run", False)),
        )
