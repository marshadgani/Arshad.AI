# /dev-team

Thin wrapper around the **dev-team-orchestrator** agent. Spawns it as a Task() subagent and surfaces its return value to you.

## Usage

```
/dev-team <feature requirement>
```

Or auto-triggered per CLAUDE.md §21 when a user prompt classifies as a feature requirement.

## What this command does

1. Spawns the orchestrator subagent:
   ```
   Task(subagent_type="dev-team-orchestrator",
        description="Run dev-team pipeline",
        prompt=<requirement>)
   ```
2. The orchestrator runs all 11 steps autonomously (Step 0 through Step 11) — confirms the feature, issues a FEAT-NNN, dispatches BA → EA-pre → SA → Dev → PO → TSW → Tester → BugFixer↔Tester loop → EA-post, validates the denylist, atomically updates `tasks/process-hierarchy.md`, creates the `dev-team/<feat-id>-<slug>` branch, commits, and writes the `tasks/pipeline-runs.md` row.
3. Returns the orchestrator's final report block (Feature ID, Branch, Status, EA decision, artifact paths) to the user.

## Cost model

All 8 dev-team agents + the orchestrator are Claude-Code-native. **Zero `ANTHROPIC_API_KEY` consumption.** The orchestrator runs on Opus (per its frontmatter); dispatched agents run on their own pinned tier (Haiku for BA + PO, Sonnet for the rest).

## Where the recipe lives

The full 11-step recipe — confirmation, denylist, sanitization, halt logic, log format — is in the orchestrator agent at `.claude/agents/dev-team/orchestrator.md`. This command is a wrapper; the agent is the implementation.

## Halts

The orchestrator may halt at Steps 0, 2, 4, 5, or 8. In all cases it logs the row to `tasks/pipeline-runs.md` with status `halted` and writes the halt reason. Step 9 (EA post-build) **always** runs even after a Step 8 cap-halt.

## Cancellation

The user halts by interrupting the parent Task call (Esc). The orchestrator persists artifacts after every step, so a halted run is recoverable from `tasks/agent-outputs/<role>/FEAT-NNN_*.json`.
