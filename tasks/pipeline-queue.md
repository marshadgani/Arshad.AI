# Dev-Team Pipeline Queue

> Tracks every feature/change/bug that has gone through, or is waiting to go through,
> the `.claude/workflows/dev-team-pipeline.js` Workflow. Source of truth for resuming
> the pipeline in a NEW session — `resumeFromRunId` only works within the session that
> created the run, so a fresh session re-seeds from the artifacts referenced here
> instead of replaying already-completed stages.

## How to use this file (for Claude, every session)

1. On any user message describing a change, new feature, or bug — assign the next
   `FEAT_ID` from `tasks/.feature-counter` (increment it), and append a row below
   with `status: queued`.
2. If a workflow run is already active THIS session, resume it:
   `Workflow({ scriptPath: ".claude/workflows/dev-team-pipeline.js", resumeFromRunId: "<run_id>", args: { features: [...all queued + in-flight features...] } })`
   — completed features return instantly from cache; the new one interleaves.
3. If this is a NEW session (no active run_id), start a fresh run with `args.features`
   containing only the features still `queued` or `in_flight` in this file. Do NOT
   re-include `completed` features as full entries — their code is already committed;
   there's nothing to resume for them.
4. After each run completes (success, halt, or error), update this file: move the
   row to `completed`/`halted`/`error`, record the branch name and EA decision.
5. Never run two Workflow invocations concurrently against the same run_id from two
   different conversation turns — check `/workflows` or this file's `active_run_id`
   field first.

## Active run

| Field | Value |
|---|---|
| active_run_id | wf_14899418-22d |
| session | session_01S3fJzZzJykfHRA9jhMycuk |
| started | 2026-09-06 |

*(A run_id is only valid within the session that created it. If you're in a different session, ignore this field and start fresh per step 3 above — then update this table.)*

## Queue

| FEAT_ID | Requirement (short) | Status | Branch | EA Decision | Notes |
|---|---|---|---|---|---|
| FEAT-118 | Chat window blocks screen (redesign) + app-wide mobile responsiveness | in_flight | dev-team/feat-118-* (TBD) | — | First run errored at System Engineer stage — 6 role names in the script (`system-engineer`, `engineer`, `frontend-engineer`, `senior-engineer`, `software-architect`, `performance-optimisation-engineer`) don't exist in this harness's agent registry. Fixed (see `.claude/agents/dev-team/` note below) and resumed on the same run_id `wf_14899418-22d` — first 5 stages replayed from cache. |

**Known gap:** only 9 of the 28 roles CLAUDE.md documents have actual `.claude/agents/dev-team/*.md` files (`bug-fixer`, `business-analyst`, `developer`, `enterprise-architect`, `orchestrator`, `process-organiser`, `solution-architect`, `test-script-writer`, `tester`). The other ~19 conceptual roles have no dev-team-specific agent — the workflow script maps them to the closest existing agent in the full roster instead (e.g. `system-engineer` → `system-architect`, `senior-engineer` → `code-analyzer`). If a future stage errors with "agent type not found," check this mapping first before assuming it's a new bug.

## Completed

*(none yet — move rows here from Queue once a run finishes, with final branch + EA decision)*
