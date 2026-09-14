"""Canonical definition of the skill category enum.

Single source of truth for the four legal `category` values. The persistence
layer (`src/models/skill.py`, which turns this into a DB CHECK constraint) and
the presentation layer (`src/schemas/ai_ecosystem.py`, which reuses the same
`Literal` for request/response validation) both import from here, so rows that
never pass through `RegisterSkillRequest` — such as the manifest bulk-upsert
in `src/skills/service.py` — still cannot carry an unknown category.

`scripts/register_skills.py` deliberately does NOT import this module: it is a
pure, dependency-free generator that runs outside the backend package, so its
own local category Literal is kept in sync by hand (see the comment there).
"""

from __future__ import annotations

from typing import Literal, get_args

SkillCategory = Literal["development", "security", "data", "other"]

SKILL_CATEGORIES: tuple[SkillCategory, ...] = get_args(SkillCategory)

DEFAULT_SKILL_CATEGORY: SkillCategory = "other"
