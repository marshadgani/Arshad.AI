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
- title: Decide whether domain applications and agents get their own detail destinations
- added: 2026-09-14
- description: FEAT-UNDEFINED-001 removed the dead 'Open →' and 'Configure' buttons from DomainPage because no per-application or per-agent destination exists. If that IA is wanted, it needs: a url/route field on Application and DomainAgent (frontend/src/data/mockData.ts + backend/src/schemas/domain.py + Alembic migration), new routes in App.tsx, and re-adding the affordances plus the :focus-within styles removed from DomainPage.module.css. Delete the 'placeholder guard' case in DomainPage.test.tsx when doing so.
- context: frontend/src/components/DomainPage.tsx, frontend/src/components/DomainPage.module.css, backend/src/schemas/domain.py

