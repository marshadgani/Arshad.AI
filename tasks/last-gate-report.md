# Arshad.AI Quality Gate Report

**Branch:** `claude/chat-mobile-health-integration-if20cp` -> `claude/ai-personal-assistant-main`
**Change:** FEAT-171 to 176, bug fixes done directly (no pipeline, per the bug-fix rule). The dashboard and the Finance and Stocks pages now serve real data instead of rows seeded from `seed_from_mock.py`. Also adds the bug-fix auto-merge rule to CLAUDE.md.
**Date:** 2026-10-07

### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

## Gate Summary

| # | Agent | Result |
|---|---|---|
| 1 | code-reviewer | WARN, 0 Critical. Open-state filter ran after a 200-row window, so older open PRs could be missed. Fixed with a SQL filter |
| 2 | security-auditor | PASS. 1 low finding (`/agent-activity` not scoped per user). Fixed by joining runs to the user's chat sessions |
| 3 | debugger | WARN, 0 Critical. Bad stored latitude caused a 500, one failed Hacker News story dropped all news, null title read "None". All fixed |
| 4 | test-writer | FAIL on `domains.py` (0 percent). Fixed with route tests. Now 92 percent on changed code |
| 5 | refactorer | Reported 1 Critical, refuted (see below). 2 warnings deferred |
| 6 | doc-writer | WARN. Its docstring finding was wrong, 3 endpoints are still seed-backed |
| 7 | silent-failure-hunter | WARN, 0 Critical. Stack traces now logged. Stale news cache added. Rest deferred |
| 8 | pr-test-analyzer | WARN. Added query-scoping, domain endpoint and malformed-payload tests |

## Verdict: WARN, mergeable

Backend: 989 pass, 9 fail. The same 9 fail without these changes (they need a database or auth setup, in `test_auth`, `test_auth_password`, `test_ontology_extraction`, `test_token_service`). 57 new tests pass. Lint clean.

## Subagent claim refuted (manual cross-check)

- Refactorer C1 said `/health-habits` always returns empty because the Whoop and Apple Health handlers return plain dicts. HALLUCINATED -> manual: PASS. Both handlers return `JSONResponse` (`whoop.py`, `apple_health.py`), the debugger and code-reviewer confirmed it, and a test using a real `JSONResponse` passes.

## Fixed in this PR (from gate findings)

- `/agent-activity` is scoped to the caller through `ConversationSession.user_id`.
- GitHub rows are filtered to `state == "open"` in SQL before the limit, so Focus and Decisions pick the true oldest item.
- Gmail snippets no longer appear as tasks. Task labels read "Updated N d ago", so they never trigger the overdue styling.
- News and weather tolerate malformed upstream payloads, one failed story, and a bad stored location. News serves the last good list when Hacker News is down.
- Null GitHub titles no longer render as "None".
- Failure logs include stack traces.
- New tests assert the SQL is bound to the current user for tasks, decisions, focus, notifications, agent activity, weather and domain KPIs.

## Deferred (non-blocking)

- [ ] `/events` returns an empty list when the Google fetch fails, the same as when no events exist. Add an `unavailable` flag.
- [ ] `/news` and `/health-habits` do not tell the user an upstream failed. Whoop `needs_reauth` is not shown.
- [ ] `list_health_habits` calls the Whoop and Apple Health handlers directly. Extract shared service functions.
- [ ] `_collection` helper is used by only some routes.
- [ ] `AgentUsageLog` has no `user_id` column. Runs without a chat session are hidden. Add the column in a migration.
- [ ] `/agents`, `/quick-actions`, `/knowledge-suggestions` and the seed rows are still seed-backed.
- [ ] Focus card button has no click handler.
