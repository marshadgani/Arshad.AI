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
6. **Never launch a second, separate `Workflow` run while one is still active**, even
   for unrelated new features — the per-role mutex lives in that run's own script
   state and does NOT extend across separate invocations. If a run is active and a
   new feature comes in, add it to the Queue table as `queued` and either wait for
   the active run to settle before launching a combined resume, or let it sit for
   the hourly Routine to pick up together with whatever's still pending then.

## Active run

| Field | Value |
|---|---|
| active_run_id | wf_14899418-22d |
| session | session_01S3fJzZzJykfHRA9jhMycuk |
| started | 2026-09-06 |

*(A run_id is only valid within the session that created it. If you're in a different session, ignore this field and start fresh per step 3 above — then update this table.)*

## Always-on continuation (standing Routine)

Per CLAUDE.md's "🔁 Always-On Pipeline" policy, this queue is checked and driven
forward automatically, not just when Arshad is actively chatting:

| Field | Value |
|---|---|
| routine_id | trig_018w2XJ9mHBfqUZ1uciMNqit |
| name | Dev-Team Pipeline Continuation |
| schedule | hourly (`create_new_session_on_fire: true`) |
| created | 2026-09-06 |

If this routine is ever missing (check `list_triggers`), recreate it — see CLAUDE.md.
Every firing reads this file, resumes/restarts any `queued`/`in_flight`/`error`
feature's Workflow run, and updates this file when it settles. It no-ops if the
queue below is empty.

## Queue

| FEAT_ID | Requirement (short) | Status | Branch | EA Decision | Notes |
|---|---|---|---|---|---|
| FEAT-118 | Chat window blocks screen (redesign) + app-wide mobile responsiveness | in_flight | dev-team/feat-118-* (TBD) | — | Second run halted at Software Architect on a FALSE-POSITIVE denylist violation: the agent returned absolute paths (`/home/user/Arshad.AI/frontend/...`) and the denylist check flagged the leading `/` as a path-escape attempt. Fixed (`normalizePath()` strips the project root before any check) — real denylist rules (auth/middleware/CI/secrets) unaffected. Resumed on the same run_id `wf_14899418-22d`, this time combined with FEAT-119 and FEAT-120 in one call. Also discovered: many specialist agents write directly to disk via their own Write tool grant, not just the final Ship stage — checkpointed via WIP commits throughout so nothing is lost regardless. |
| FEAT-119 | Shopify integration — live store confirmed to have real orders. Populate `/shopify` domain page (currently a stub) with real KPIs (revenue, order count, conversion rate, low-stock count) and a live order feed, per the connector-analysis recommendation. New OAuth-backed integration provider following the Whoop pattern. | in_flight | dev-team/feat-119-* (TBD) | — | Launched together with FEAT-118 and FEAT-120 in one Workflow call (`wf_14899418-22d`) now that the prior run has settled — see concurrency constraint below. |
| FEAT-120 | Connect Whoop and Apple Fitness/Health data to populate the Health & Fitness dashboard section. Whoop already has partial backend integration (`backend/src/api/v1/whoop.py`, `backend/src/integrations/personal/oauth_providers.py`) — this feature should audit/complete it and add the missing Apple Health side (no existing integration found for Apple Health; will need research into what's actually available — HealthKit has no public REST API, so this likely means an export-file ingestion path or a third-party sync service, which Code Explorer/Solution Architect should investigate and flag as a decision point if ambiguous). | in_flight | dev-team/feat-120-* (TBD) | — | Same launch as FEAT-119. |

**Important — concurrency constraint on launching:** Two or more features can only share the "same specialist role never runs concurrently" guarantee if they run inside the SAME `Workflow()` invocation (the `locks` object is local to one script execution, not shared across separate calls). Never start a second `Workflow` run while another is still active — wait for it to settle, then resume/restart with the full set of pending features in one `args.features` array.

**Known gap:** only 9 of the 28 roles CLAUDE.md documents have actual `.claude/agents/dev-team/*.md` files (`bug-fixer`, `business-analyst`, `developer`, `enterprise-architect`, `orchestrator`, `process-organiser`, `solution-architect`, `test-script-writer`, `tester`). The other ~19 conceptual roles have no dev-team-specific agent — the workflow script maps them to the closest existing agent in the full roster instead (e.g. `system-engineer` → `system-architect`, `senior-engineer` → `code-analyzer`). If a future stage errors with "agent type not found," check this mapping first before assuming it's a new bug.

## Completed

*(none yet — move rows here from Queue once a run finishes, with final branch + EA decision)*
