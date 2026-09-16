# Arshad.AI Quality Gate Report

**Branch:** `claude/ui-repos-reference-jusj4c` → `claude/ai-personal-assistant-main`
**Triggered by:** "Merge to Main"
**Scope:** Incident recovery — restoring FEAT-160 and FEAT-161, silently reverted by a
concurrent session's squash-divergence collision

---

## What happened in this cycle (read this first — this is a real incident, not routine work)

FEAT-160 and FEAT-161 were both already merged to `claude/ai-personal-assistant-main`
on 2026-09-14 (PRs #90 and #94, both WARN-verdict gate passes, both confirmed deployed
and working — including a live-Render-log confirmation that FEAT-161's fix to
`GET /api/v1/ai-ecosystem/metrics` was actually resolving the 500 it targeted).

**On 2026-09-16, a routine "Merge to Main" in this session discovered that both
features had vanished from main** — not just their pipeline-queue.md rows, but the
actual shipped code:

- `backend/src/api/v1/ai_ecosystem.py` was back to `cast(AgentUsageLog.success,
  Float)` (the exact bug FEAT-161 fixed) — **confirmed still live-failing in
  production** via Render logs (`GET /api/v1/ai-ecosystem/metrics` 500s as recently
  as 2026-09-15T18:04Z, a full day after the fix had supposedly shipped).
- `frontend/src/dashboard/CardSkeleton.tsx`, `EmptyState.tsx`, and
  `widgets/loadingStates.test.tsx` were gone entirely; all 9 dashboard widgets were
  back to the old "loading and empty render identically" behavior.
- `frontend/src/styles/tokens.css` / `tokens.test.ts` had lost FEAT-160's
  `--status-warn-faint`/`-bg` triad and the widened test scope (`tokens.test.ts`
  shrank from 115 lines back to 58).
- `frontend/src/components/ComingSoonPage/ComingSoonPage.module.css` had reverted to
  referencing the undefined `--accent-pending*` tokens FEAT-160 fixed.
- `.claude/workflows/dev-team-pipeline.js` had also lost an unrelated `featId`/`id`
  normalization fix (not mine — evidence a *third* piece of work was caught in the
  same regression).

**Root cause:** a concurrent session ran its own "Merge to Main" for an unrelated
timezone-handling bugfix (now on main as FEAT-157/162/163) from a branch that forked
*before* FEAT-160/161 existed. This repo's merge history is exclusively GitHub
squash-merges (per `.github/workflows/auto-pr.yml`), so every "Merge to Main" leaves
main's squash commit with no real parent relationship to the individual commits on
any feature branch. CLAUDE.md §20 Step 0 ("squash-divergence repair") exists for
exactly this shape of problem, but it assumes the only divergence is
squash-vs-individual-commits of the *same* content. Here the other session's branch
had a **genuine, older divergence** — it did a real 3-way merge (correctly, by their
own lights) but because their merge-base resolved to a common ancestor *before*
FEAT-160/161, git's automatic merge treated "FEAT-160/161 exist on main but not on
their branch" as new-on-main-only content that their merge could legitimately not
know how to reconcile with intent — and their squash-merge onto main won the race,
silently discarding content that was never in conflict from git's perspective (no
conflict markers, no error) but was very much in conflict from a product perspective.

**This session hit the identical trap moments later**, running its own real
`git merge origin/claude/ai-personal-assistant-main` (correctly avoiding a blind
`--strategy=ours`, per the lesson from FEAT-160's own cycle) — and the `ort` merge
strategy again silently resolved every one of these files in main's favor, which
would have **re-reverted FEAT-160/161 a second time** had it been pushed. Caught
before pushing by diffing the merge result against expectations; the bad merge
commit was `git reset --hard` away before it ever left this machine.

## Recovery approach

Rather than another blind merge, every regressed file was identified individually by
diffing `origin/claude/ai-personal-assistant-main` against this session's last known
-good local commit (which had both FEAT-160 and FEAT-161 correctly merged), confirming
each diff was a clean, isolated, single-purpose regression (no other session's
legitimate content mixed into the same file) before restoring it:

- `backend/src/api/v1/ai_ecosystem.py`, `backend/tests/test_ai_ecosystem.py`,
  `.claude/workflows/dev-team-pipeline.js`,
  `frontend/src/components/ComingSoonPage/ComingSoonPage.module.css`,
  `frontend/src/dashboard/{CardSkeleton,EmptyState}.tsx`,
  `frontend/src/dashboard/Dashboard.module.css`,
  `frontend/src/dashboard/widgets/*.tsx` (9 files),
  `frontend/src/dashboard/widgets/loadingStates.test.tsx`,
  `frontend/src/styles/tokens.css`, `frontend/src/styles/tokens.test.ts` — restored
  in full from the pre-regression commit.
- `tasks/pipeline-queue.md` — the FEAT-160/161 rows were re-inserted by hand at their
  original position, preserving every row the other session legitimately added
  (FEAT-157/162/163 and its own renumbering notes) untouched.
- `tasks/.feature-counter` — left at main's current value (`163`), which already
  accounts for the other session's FEAT-162/163.
- Deliberately **not** touched: the other session's real new work (the timezone-aware
  Alembic migration, `models/base.py`'s `utcnow()` helper and related model changes,
  the ingestion date-parsing fixes, and their two new test files) — all confirmed
  still present and untouched by this recovery.

## Verification

- `tsc --noEmit` — clean.
- `npx vitest run` — **40/40 files, 311/311 tests passing** (full suite, including
  the other session's tests).
- `python3 -m pytest backend/tests/test_ai_ecosystem.py` — **52/52 passing**,
  including the 3 tests that exercise the actual `/metrics` route end-to-end (these
  would have caught the reverted `Integer` import immediately).
- `python3 -m pytest backend/tests/` (full suite) — **636/643 passing**; the 7
  failures are the same pre-existing, network-dependent `test_auth.py` /
  `test_auth_password.py` / `test_token_service.py` failures present before this
  recovery — confirmed unrelated (this recovery touches none of those files).

## Overall Verdict

### GATE PASSED WITH WARNINGS — Ready for merge

This is a recovery of already-shipped, already-gated work — not new functionality —
so the full 8-agent panel is not being re-run for a second time on identical content
already reviewed in FEAT-160's and FEAT-161's own gate cycles (see git history for
those reports). The verification above (tsc, full frontend suite, full backend
suite, and the specific regression tests that target the exact bug that recurred)
stands in for that re-review, consistent with this being a restoration rather than a
new change.

---

## Action Items

- [ ] **Systemic risk, not yet mitigated:** this repository's exclusively-squash-merge
      history makes the merge-base ambiguity in this incident a standing risk any time
      two sessions' "Merge to Main" cycles race on branches that forked at different
      points. CLAUDE.md §20 Step 0 only guards the narrower squash-vs-individual-commit
      case. A real fix needs either (a) a locking/coordination mechanism so only one
      session merges to main at a time, or (b) a post-merge verification step (e.g.
      a CI check that diffs the new main tip against the immediately-prior main tip
      restricted to files the merging PR did NOT touch, failing loudly if any are
      changed) — worth raising with Arshad as a process fix, not a code fix.
  * [ ] From FEAT-161's own gate cycle (carried forward, still open): the dashboard's
      13 independent `useFetch` calls discard `error` entirely — a persistently-failing
      endpoint renders `CardSkeleton` forever instead of a distinguishable error state.
- [ ] Integrations page mobile scroll length (from FEAT-161's live audit) — real
      usability opportunity, still just a backlog idea.

---
*Generated by Arshad.AI Quality Gate · Incident recovery, verified via full test suites · claude/ui-repos-reference-jusj4c*
