# Arshad.AI Autonomous Backlog

Tasks here are executed automatically by `.github/workflows/autonomous-backlog.yml`
every 2 hours. Tasks marked `requires_human: yes` are skipped until Arshad reviews them.

Add tasks with: `python scripts/backlog_add.py --title "..." --description "..." --autonomous yes`

---

<!--
TASK FORMAT (copy-paste template):

### TASK-NNN
- status: pending
- requires_human: no
- title: Short title
- added: YYYY-MM-DD
- description: Full description of what to do. Be specific about files, behaviour, acceptance criteria.
- context: relevant/files/or/dirs (space-separated)
-->

<!-- No tasks yet. New tasks appear here as the session builds up. -->

### TASK-001
- status: pending
- requires_human: yes
- title: Phase 2: drop orphaned weather table and its seed writes
- added: 2026-09-13
- description: backend/src/models/dashboard.py:180 (Weather table) and scripts/seed_from_mock.py's weather seed writes are orphaned now that FEAT-138 removed the seeded fallback read path in services/weather/service.py. Two-phase destructive change per .claude/rules/database.md: this is Phase 2 (removal) once no reads are confirmed in production.
- context: backend/src/models/dashboard.py, backend/scripts/seed_from_mock.py; reads removed in FEAT-138

