# /orchestrate

General-purpose multi-agent orchestrator. Takes an objective, plans a task graph across the 15 project + dev-team agents, dispatches them, and runs the 6-agent quality gate at the end.

## Usage

```
/orchestrate <objective>
```

## When to use this vs /dev-team

| Use | Why |
|---|---|
| `/dev-team <feature>` | New feature build — deterministic 9-stage pipeline (BA → EA-pre → SA → Dev → PO → TSW → Tester → BugFixer↔Tester → EA-post) |
| `/orchestrate <objective>` | Anything else — audits, refactors, documentation sweeps, multi-agent investigations, hybrid plans |

If the objective is "build feature X", route to `/dev-team`. If it's "audit Y", "refactor Z to use X", "document the W flow", "investigate why X is slow" — route here.

## What this command does

1. Spawns the orchestrator subagent: `Task(subagent_type="orchestrator", prompt=<objective>)`
2. The orchestrator runs autonomously: plan → dispatch → gate → report
3. Returns the orchestrator's `final.md` content to the user
4. Path to full run artifacts is included in the return

## Cost shape

The orchestrator runs on Opus. Each dispatched agent runs on its own tier (Haiku/Sonnet per frontmatter). Hard caps inside the agent: 25 Task() calls per run, 3 replans, 30-min wall clock.

## Persistence

Every run writes to `tasks/orchestrator-runs/<RUN-ID>/` (committed). Includes:
- `plan.json` — initial task graph
- `plan-revisions/` — each replan
- `progress.md` — live checkpoint
- `artifacts/` — per-task outputs
- `gate-report.md` — 6-agent gate verdict
- `final.md` — run summary

The terminal gate report is also written to `tasks/last-gate-report.md` per CLAUDE.md §20.

## Cancellation

The user halts by interrupting the parent Task call (Esc). The orchestrator keeps `progress.md` fresh so resuming is possible — re-invoke with the same objective and reference the prior run-id in the prompt.

## Auto-trigger

Not auto-triggered today. CLAUDE.md §21 routes feature requirements to `/dev-team`; everything else is explicit. Add §21-style routing here only if you want this command to fire on every non-feature prompt — not the default.
