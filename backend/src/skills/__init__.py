"""Skill registry domain package.

Layers, innermost first — each may import the one above it, never below:

    categories.py   the four legal category values (no dependencies)
    manifest.py     location + safe loading of the committed manifest.json
    repository.py   every SQL statement against `skill_registry`
    service.py      use cases + transaction boundaries (register, sync)

Callers — the HTTP routes in `src/api/v1/ai_ecosystem_skills.py` and the
startup sync in `scripts/seed_from_mock.py` — depend on `service` (and, for
reads, `repository`). Intentionally free of package-level imports so
`src.models.skill` can import `src.skills.categories` without a circular
import.
"""
