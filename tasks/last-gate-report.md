# Arshad.AI Quality Gate Report

**Branch:** `fix/google-reauth-connect` -> `claude/ai-personal-assistant-main`
**Feature:** FEAT-169, Google Connect re-authorizes a revoked login. Connect on an existing Google account only marked the card Connected and never sent the user to Google. It now tests the stored login and starts the Google consent flow when it is rejected.
**Date:** 2026-10-07

## Gate Summary

| # | Agent | Result |
|---|---|---|
| 1 | code-reviewer | FAIL on iteration 1 (user expired after rollback). Fixed. Re-check found one more path on the outage branch. Fixed |
| 2 | security-auditor | WARN. Google outage made Connect return 500, and lock and write on every click. Fixed. Re-check WARN for decrypt errors. Fixed |
| 3 | debugger | WARN. Unhandled Google errors. Fixed |
| 4 | test-writer | PASS |
| 5 | refactorer | WARN. Duplicated attach call. Fixed |
| 6 | doc-writer | FAIL on iteration 1 (docstrings). Fixed, re-check PASS |
| 7 | silent-failure-hunter | WARN. Same Google error gap. Fixed, now logged |
| 8 | pr-test-analyzer | WARN. Gaps covered by new tests |

Iteration 2 re-ran code-reviewer, security-auditor and doc-writer only. The other five were not re-run, since their findings were fixed in the same code and covered by tests.

## Verdict: WARN, mergeable

**GATE PASSED WITH WARNINGS**

Tests: 51 pass in `tests/test_personal_attach.py`. The same 4 Postgres-only tests error here because the sandbox has no database.

## Fixed in this PR

- Connect on a Google card now checks the stored refresh token. A rejected token starts the Google consent flow.
- The probe skips while the access token is valid, so a normal click does no Google call or lock.
- Google outages, timeouts, missing config, decrypt and database errors fail open to the old behaviour and are logged.
- The user id is read before the rollback, and the user is refreshed after it.

## Open

- [ ] Operator action: the Google redirect URI `${BACKEND_URL}/api/v1/integrations/personal/attach/google/callback` must be saved on the Google OAuth client.
