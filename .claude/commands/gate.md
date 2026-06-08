# /gate — Arshad.AI Quality Gate

Runs the complete quality gate before any merge to `main`.
Orchestrates all 8 review agents in parallel, compiles a master report,
posts it to the GitHub PR, and presents a PASS/FAIL decision.

## Usage

```
/gate                    ← auto-detects open PR for current branch
/gate <pr-number>        ← target a specific PR
```

## Auto-Trigger

This command runs **automatically** whenever the user:
- Says "create PR", "open PR", "PR to main", or "pull request"
- Says "Merge to Main" (gate runs first; merge only if PASS)
- Uses `/gate` explicitly

---

## Gate Protocol (execute exactly in this order)

### Step 0 — Resolve Context

1. Run `git branch --show-current` to get the source branch.
2. Run `git diff claude/ai-personal-assistant-main...HEAD --stat` to get the change scope.
3. Run `git log claude/ai-personal-assistant-main..HEAD --oneline` to list commits in this branch.
4. If a PR number was provided, use it. Otherwise search for an open PR for
   this branch via `mcp__github__search_pull_requests` with `head:<branch>`.
5. If no PR exists yet, create one via `mcp__github__create_pull_request`:
   - title: branch name in sentence case
   - base: `main`
   - body: auto-generated from commit list
   Record the PR number for the report.

---

### Step 1 — Run All 8 Agents in Parallel

Launch all agents simultaneously using the `Agent` tool.
**Do not wait for one to finish before starting the next.**
Each agent receives the full diff context.

```
Agents to run in parallel:
  1. code-reviewer          → bugs, logic errors, performance issues
  2. security-auditor       → OWASP top 10, secrets, injection, auth
  3. debugger               → trace potential runtime failures and error paths
  4. test-writer            → assess test coverage gaps; list missing tests
  5. refactorer             → structural issues, naming, duplication, complexity
  6. doc-writer             → missing docstrings, outdated comments, API docs gaps
  7. silent-failure-hunter  → swallowed exceptions, HTTP 200 masking errors, missing error propagation
  8. pr-test-analyzer       → test quality, negative test coverage, behaviour vs implementation verification
```

Each agent must return a structured result:
```
STATUS: PASS | WARN | FAIL
CRITICAL: <count>
WARNINGS: <count>
SUMMARY: <2-3 sentences>
FINDINGS: <bulleted list>
```

**Gate thresholds:**
| Agent | FAIL condition | WARN condition |
|---|---|---|
| code-reviewer | any Critical bug | any Warning-level issue |
| security-auditor | any vulnerability (any severity) | any hardcoded config value |
| debugger | any unhandled error path in new code | any untested edge case |
| test-writer | coverage < 70% on changed files | coverage 70–80% |
| refactorer | complexity score > 10 on any function | duplicated logic blocks |
| doc-writer | public API endpoint undocumented | inline comment missing on complex logic |
| silent-failure-hunter | any swallowed exception or HTTP 200 masking a real error | any missing error log on a caught exception |
| pr-test-analyzer | any BPDD requirement with no test | any test verifying internals rather than behaviour |

---

### Step 2 — Compile Master Gate Report

Aggregate all 8 agent results into this exact report format:

```markdown
# Arshad.AI Quality Gate Report

**PR:** #<number> — <title>
**Branch:** `<source>` → `main`
**Triggered by:** <user message / /gate>
**Date:** <today>

---

## Gate Summary

| # | Gate | Agent | Result | Critical | Warnings |
|---|---|---|---|---|---|
| 1 | Code Review | code-reviewer | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 2 | Security Audit | security-auditor | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 3 | Bug Analysis | debugger | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 4 | Test Coverage | test-writer | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 5 | Code Quality | refactorer | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 6 | Documentation | doc-writer | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 7 | Silent Failures | silent-failure-hunter | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |
| 8 | Test Quality | pr-test-analyzer | ✅ PASS / ⚠️ WARN / ❌ FAIL | N | N |

## Overall Verdict

<!-- PASS if zero FAIL gates and zero Critical issues across all agents -->
<!-- WARN if any WARN gates but zero FAIL gates -->
<!-- FAIL if any gate returned FAIL or any Critical issue found -->

### ✅ GATE PASSED — Ready for merge
OR
### ⚠️ GATE PASSED WITH WARNINGS — Review warnings before merging
OR
### ❌ GATE BLOCKED — Fix all FAIL gates before merging to main

---

## Detailed Findings

### 1. Code Review (code-reviewer)
**Status:** ✅/⚠️/❌
<findings from code-reviewer agent>

### 2. Security Audit (security-auditor)
**Status:** ✅/⚠️/❌
<findings from security-auditor agent>

### 3. Bug Analysis (debugger)
**Status:** ✅/⚠️/❌
<findings from debugger agent>

### 4. Test Coverage (test-writer)
**Status:** ✅/⚠️/❌
<findings from test-writer agent>

### 5. Code Quality (refactorer)
**Status:** ✅/⚠️/❌
<findings from refactorer agent>

### 6. Documentation (doc-writer)
**Status:** ✅/⚠️/❌
<findings from doc-writer agent>

### 7. Silent Failures (silent-failure-hunter)
**Status:** ✅/⚠️/❌
<findings from silent-failure-hunter agent>

### 8. Test Quality (pr-test-analyzer)
**Status:** ✅/⚠️/❌
<findings from pr-test-analyzer agent>

---

## Action Items

<!-- Only include if any gate WARN or FAIL -->
Priority order for fixes (Critical first):
- [ ] <item 1>
- [ ] <item 2>

---
*Generated by Arshad.AI Quality Gate · All 8 agents · Auto-posted to PR*
```

---

### Step 3 — Post Report to GitHub PR

Post the full compiled report as a PR comment:
```
mcp__github__add_issue_comment(
  owner="marshadgani",
  repo="Arshad.AI",
  issue_number=<pr_number>,
  body=<full_report_markdown>
)
```

---

### Step 4 — Present Decision to User

After posting, show the user:

**If GATE PASSED (no FAIL gates, no Critical issues):**
```
✅ Quality Gate PASSED — Report posted to PR #<N>

All 8 agents approved this change.
Say "Merge to Main" to merge PR #<N> into main.
```

**If GATE PASSED WITH WARNINGS:**
```
⚠️ Quality Gate PASSED WITH WARNINGS — Report posted to PR #<N>

<list warnings>

You may still merge. Say "Merge to Main" to proceed,
or fix the warnings first and re-run /gate.
```

**If GATE BLOCKED:**
```
❌ Quality Gate BLOCKED — Report posted to PR #<N>

Critical issues must be resolved before merging:
<list Critical issues from all agents>

Fix the issues above, commit, then re-run /gate.
```

---

### Step 5 — "Merge to Main" handler

When the user says **"Merge to Main"** (exact phrase, case-insensitive):

1. If gate has not been run yet in this session → run `/gate` first, then offer merge.
2. If gate result is BLOCKED → refuse merge, show blocking issues.
3. If gate result is PASS or WARN → execute merge:

```
mcp__github__merge_pull_request(
  owner="marshadgani",
  repo="Arshad.AI",
  pullNumber=<pr_number>,
  mergeMethod="squash",
  commitTitle="<PR title> (#<N>)",
  commitMessage="Merged via Arshad.AI Quality Gate — all 8 agents passed."
)
```

4. After merge, confirm:
```
🎉 PR #<N> merged into main via squash merge.
Branch `<source>` can now be deleted.
```

---

## Notes

- WARN gates never block a merge — only FAIL gates do.
- Security gate is the strictest: any vulnerability (including WARN-level) upgrades to FAIL.
- The gate report is always posted to the PR regardless of outcome.
- Re-running `/gate` on the same PR overwrites the previous comment if possible,
  or posts a new comment labelled "Gate Re-run #N".
