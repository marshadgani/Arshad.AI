# Alternate Features Registry

> Governed by CLAUDE.md §24 (Alternate Feature Preservation, PERMANENT).
> This file tracks every piece of real work that exists in the codebase but
> is not (yet, or ever) merged to `claude/ai-personal-assistant-main` —
> halted pipeline features, experimental approaches, abandoned attempts.
>
> Say **"bring me all the alternate features"** (or a near-match) in any
> session to have this file read back and summarized.
>
> Halted dev-team pipeline features are also tracked in their own detail in
> `tasks/pipeline-queue.md` (Halted rows) — this file cross-references them
> by FEAT_ID rather than duplicating their full notes, and is the place for
> everything the pipeline queue doesn't cover.

## Registry

| ID | Description | Branch | Progress point | Status | Notes |
|---|---|---|---|---|---|
| FEAT-121 | Google Calendar auto-booking + time audit + Spotify focus-telemetry | — (design stage only, no code branch yet) | Blocked at Architecture Critic after 3 redesign passes — design is genuinely hard (crash-recovery schema, leaked-time detection false positives, unstable evidence timestamps) | halted | See `tasks/pipeline-queue.md` FEAT-121 row for full detail. Needs Arshad's decision: allow more redesign iterations, reduce scope, or give the Solution Architect explicit upfront guidance. |
| FEAT-122 | Gmail universal ingest bus + dropped-ball detector | — (design stage only) | Architecture Critic blocking after 2 rounds (non-functional retry logic in `_retry.py`) | halted | Awaiting convergence-test relaunch. |
| FEAT-123 | Google Drive permissions audit + knowledge_suggestions | — (design stage only) | Architecture Critic blocking after 2 rounds (Alembic `down_revision` mismatch) | halted | Awaiting convergence-test relaunch. |
| FEAT-124 | Zoom promise ledger + Obsidian filing | — (design stage only) | Architecture Critic blocking after 2 rounds (unregistered DAG ids) | halted | Awaiting convergence-test relaunch. |
| FEAT-126 | Zomato pre-staged cart + spend tracking + burnout chart | — (design stage only) | EA pre-build rejected with resubmission checklist (domain placement, OAuth base class, missing FKs, gateway routing, table naming, split burnout chart out) | halted | Needs BPDD revision, not a redesign-loop retry. |
| FEAT-127 | Figma token-drift check + auto-diagrams | — (design stage only) | Architecture Critic blocking after 2 rounds | halted | Awaiting convergence-test relaunch. |
| FEAT-128 | Canva product creatives + monthly one-pager | — (design stage only) | Architecture Critic blocking after 2 rounds (Shopify API version pinned outside support window) | halted | Awaiting convergence-test relaunch. |
| FEAT-130 | Calendly dynamic availability + single-use links + no-show scoring | — (design stage only) | EA pre-build halted (rate limiting, URL-encoding edge case, deployment-doc note, no-show DAG idempotency) | halted | Needs BPDD revision, not a redesign-loop retry. |
| FEAT-131 | Uber cost-of-attendance annotation + leave-by alarm | — (design stage only) | Architecture Critic blocking after 2 rounds (`CREATE INDEX CONCURRENTLY` inside an Alembic migration) | halted | Awaiting convergence-test relaunch. |
| FEAT-132 | Render per-deploy regression verdict | — (design stage only) | Architecture Critic blocking after 2 rounds (log level discarded before classification) | halted | Awaiting convergence-test relaunch. |
| FEAT-133 | Supabase branch-per-feature + advisors-to-backlog | — (design stage only) | Architecture Critic blocking after 2 rounds (step ordering contradicts orchestrator.md) | halted | Awaiting convergence-test relaunch. |
| FEAT-134 | Vercel toolbar-comment-to-pipeline bridge | — (design stage only) | Architecture Critic blocking after 2 rounds (`get_runtime_errors` poller never wired) | halted | Awaiting convergence-test relaunch. |
| FEAT-139 | GitHub activity feed/widget fed by `ingested_github_activity` | `dev-team/feat-139-141-halted-wip` | Real code written: `github_mapping.py`, `github_store.py`, `github_outcome.py` etc. — unresolved Security Auditor escalation | halted | Needs Arshad's review of the security finding before retry. |
| FEAT-140 | Relabel Home & IoT, Learning, Travel as "Coming soon" (remove fabricated static KPIs) | `dev-team/feat-139-141-halted-wip` | Real code written: `comingSoonDomains.ts`, `ComingSoonPages.test.tsx` etc. — pipeline-script warning ("added_at timestamp not provided"), likely a logging defect not a real block | halted | Worth a quick look at the pipeline script before re-running. |
| FEAT-141 | Obsidian "second brain" ontology layer (linked entities, MOCs, knowledge graph) | `dev-team/feat-139-141-halted-wip` | Real code written: `backend/src/models/ontology.py`, `frontend/src/types/ontology.ts`, `useOntologyEntities.ts`, `useOntologyStatus.ts`, `useTriggerOntologySync.ts`, ontology Alembic migration, `.claude/rules/api.md` + CLAUDE.md doc updates | halted | Unresolved Security Auditor escalation; also a Bug Fixer iteration hit the 32000-output-token API limit mid-fix — fix content may need splitting smaller if retried. Needs Arshad's review of the security finding before retry. |
| FEAT-143 (1st attempt) | Username/password login alongside Google/GitHub OAuth | — (no branch — blocked before code commit) | Architecture Critic blocked after 2 redesign rounds: timing-oracle bug in dummy_verify placement, untestable timing-equalisation test, global (not per-IP) rate limiter as self-lockout/DoS risk, silent registration-endpoint scope change | superseded | Relaunched 2026-09-14 with explicit fixes for all four issues — see the live `FEAT-143` row in `tasks/pipeline-queue.md` for the current attempt. This row kept for history only. |

## How to add an entry

- Pipeline-native halted feature → reuse its `FEAT-<N>` ID (don't renumber), pull branch/progress from `tasks/pipeline-queue.md`.
- Non-pipeline experimental/ad-hoc work → mint the next `ALT-<N>` ID.
- Always fill in a real branch name if any code was committed — never leave code sitting only in a working tree with no entry here.
