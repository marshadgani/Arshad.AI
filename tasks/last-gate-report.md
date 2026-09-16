# Merge-to-Main Gate Report — tooling/tracking fixes (2026-09-16)

## Overall Verdict

### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

Zero FAIL, zero Critical remaining. One Critical and one Important finding were raised by the panel and fixed live during this gate; everything else is WARN/Suggestion-tier and non-blocking.

## What this covers

Diff between `claude/ai-personal-assistant-CcA11` and `claude/ai-personal-assistant-main`, 4 files:

- `.claude/workflows/dev-team-pipeline.js` — fixes the `f.featId.toLowerCase()` crash that took down the entire 13-feature dev-team pipeline batch (`wf_03f9b5b9-9d2`): launch calls pass `{id: "FEAT-N", ...}` per CLAUDE.md's own examples, but every internal reference expected `.featId`. Normalizes both key names at the single feature-array consumption point, with a fail-fast guard for malformed entries (added live during this gate — see below).
- `tasks/alternate-features.md` — logs the rate-limited 13-feature batch's preserved WIP branch per §24.
- `tasks/pipeline-queue.md` — records the batch settlement and relaunch.
- `tasks/lessons.md` — three new lessons (GATE PASSED phrase requirement, `Workflow({name})` stale-script-copy gotcha, resume-args-not-persisted gotcha) — **excluded from this diff's gate scope**: `tasks/lessons.md` is on the pipeline's own `DENY_PREFIXES` denylist and was committed separately (not part of this Merge-to-Main diff), consistent with that policy.

## Gate agent results (8-agent panel)

| Agent | Verdict | Findings |
|---|---|---|
| code-reviewer | PASS after fix | Important: missing-key case silently completed a full run under `featId: undefined` — **fixed** (fail-fast guard). Suggestions: `String()` coercion, cosmetic doc wording — **fixed**. |
| security-auditor | PASS | No secrets exposure (confirmed the test-session password was never written to any tracked file). One pre-existing, non-blocking informational item (unsanitized featId reaching shell-instruction text) — not introduced by this diff, logged as a future backlog item, not merge-blocking. |
| debugger | PASS | Propagation of the normalized `f` into `runFeaturePipeline` and its `.catch()` verified correct (per-iteration `const` binding, no loop-variable-capture bug). One pre-existing Warning (same missing-key gap as code-reviewer's finding) — fixed by the same guard. |
| test-writer | WARN (not blocking) | No test harness exists for `.claude/workflows/*.js` anywhere in the repo; correctly scoped out of the "coverage < 70% = FAIL" rule, which targets shipped application code. Validated instead by `node --check` plus a live pipeline re-run exercising the exact fix path. |
| refactorer | PASS | No Critical/Warning. One low-priority suggestion (the `{id}`/`{featId}` dual-key contract is now permanent — documented). |
| doc-writer | PASS after fix | Warning: `pipeline-queue.md`'s `started` field was ambiguous with two `active_run_id` rows — **fixed**. Suggestions: reworded "historically" → "currently" (permanent contract, not transitional) — **fixed**. |
| silent-failure-hunter | PASS after fix | **Critical**: the normalization's `rawF.featId` read was unguarded against `rawF` being `null`/`undefined` — a synchronous throw outside any catch, aborting the whole batch and losing every feature queued after the bad entry (a real regression in error isolation, not pre-existing). **Fixed**: guard `!rawF` before any property access; malformed entries now produce an explicit per-item `{status:'error'}` result instead of crashing the loop. |
| pr-test-analyzer | PASS | Same no-test-harness reasoning as test-writer; recommends accepting the merge and logging a backlog item for a future Node test harness — not required for this diff. |

## Fixes applied live during this gate

1. **(Critical, silent-failure-hunter)** Guard `!rawF` before any property access in the feature-array loop; malformed entries produce an explicit error result instead of throwing synchronously outside any catch boundary.
2. **(Important, code-reviewer)** Fail fast with a named error when a feature entry has neither `.featId` nor `.id`, instead of silently running a full 30-stage pipeline under `featId: undefined`.
3. **(Suggestion, code-reviewer)** `String()` coercion on the normalized `featId` so a numeric id doesn't crash the same `.toLowerCase()` call later.
4. **(Warning, doc-writer)** Reworded "historically" to reflect that the `{id}`/`{featId}` dual-key contract is permanent per CLAUDE.md, not transitional.
5. **(Warning, doc-writer + code-reviewer)** Fixed `pipeline-queue.md`'s ambiguous `started` field and `alternate-features.md`'s stale pre-relaunch checklist item.

## Verification

- `node --check .claude/workflows/dev-team-pipeline.js` — clean.
- Fix validated live: run `wf_cc6ac57f-b37` relaunched twice with the pre-hardening version of the fix and correctly produced `Feature FEAT-125 — Code Explorer ...` labels (no more `undefined`) before being stopped to prioritize this gate.
- No application code (backend/frontend) touched — this diff is entirely internal tooling + tracking docs.

## Follow-ups (not blocking this merge)

- SEC-informational: sanitize `featId` to `[A-Za-z0-9_-]` before it reaches shell-instruction text in `dev-team-pipeline.js` (pre-existing, low severity, not introduced by this diff).
- Consider a lightweight Node test harness for `.claude/workflows/*.js` scripts (test-writer/pr-test-analyzer suggestion — no such harness exists in the repo today).
- The 13-feature dev-team pipeline batch itself remains stopped mid-run (per Arshad's explicit instruction, to prioritize this merge) — resume later per `tasks/pipeline-queue.md`'s active_run_id row.
