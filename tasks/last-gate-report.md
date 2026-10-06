# Arshad.AI Quality Gate Report

**Branch:** `dev-team/feat-167-ontology-visibility-control-path` -> `claude/ai-personal-assistant-main`
**Feature:** FEAT-167, vault publish control. Lets the user publish or unpublish ontology entities (private to public) through an authenticated API and a phone-friendly page. It is the only code path that loosens visibility. Pipeline verdict: Enterprise Architect approved with caveats.
**Date:** 2026-10-06

## Gate Summary

| # | Agent | Result |
|---|---|---|
| 1 | code-reviewer | WARN, 0 Critical. Page issues fixed (see below) |
| 2 | security-auditor | PASS, 0 Critical or High. 4 low or info findings: 3 fixed, 2 deferred (see below) |
| 3 | debugger | WARN, 0 crash-level bugs. DB error mapping and ordering fixed |
| 4 | test-writer | PASS. Estimated coverage 97 percent (service), 95 percent (API), 27 frontend tests |
| 5 | refactorer | WARN, 0 Critical. Redundant visibility guard kept on purpose |
| 6 | doc-writer | WARN. Route docstring and rollback reasoning added. Login-name warning made permanent |
| 7 | silent-failure-hunter | WARN, 0 Critical. Stale banner and stale row state fixed |
| 8 | pr-test-analyzer | WARN. The permission-switch leak test is real. Gaps logged |

## Verdict: WARN, mergeable

**GATE PASSED WITH WARNINGS**

Manual verification: backend 919 pass and 8 fail. The same 8 fail on main, so they predate this change. Frontend 338 of 338 pass. Type check clean. The 88 FEAT-167 backend tests all pass on real Postgres 16, including tenant isolation and the permission-switch leak tests.

## Fixed in this PR (from gate findings)

- A database error or lock clash now returns a structured 409 `visibility_update_failed`, with rollback. The commit moved inside the guarded block. Any other error also rolls back before it propagates.
- Entity list ordering has `id` as a tie-breaker, so pages cannot repeat or skip rows.
- Paging clears the selection, so a publish click cannot act on rows no longer in view.
- Stale row overrides are cleared on paging, filter change and after a failed change.
- Bulk Publish and Unpublish are disabled while a request is in flight.
- The "Visibility saved" banner clears when a later change fails.
- A 422 shows a plain message. A 404 message needs the `entity_not_found` code.
- "Back to first page" appears when the offset ends up past the total.
- The always-visible help text says a person's GitHub login name is written to the vault.
- Route docstring and tests added: DB error 409, commit failure 409, unexpected error rollback, paging clears selection, in-flight buttons, banner on failure, 422 message, persistent warning.

## Deferred (non-blocking, security notes)

- [ ] SEC-1 (Low): the database trigger does not itself check that both ends of a link are public when a link is promoted. The rule lives only in application SQL. Needs a new migration, never an edit of the old one.
- [ ] SEC-2 (Low): no rate limit on the PATCH route. Impact is limited to the caller's own rows.
- [ ] Report how many links changed in the response and the log.
- [ ] Two-connection test for the neighbour locking, and a test that a bare link promotion is rejected by the trigger.
- [ ] Optional: lock timeout on the neighbour lock query.
