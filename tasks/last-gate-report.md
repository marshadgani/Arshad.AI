### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

**FEAT-179: infrastructure readiness check for the trip checker**

Eight agents ran: code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer, silent-failure-hunter, pr-test-analyzer.

**Verdict: WARN. No Critical findings, no security findings left open.**

Fixed in this push:
- Render service ids are validated before they enter a URL path.
- A failed or unreadable deploy lookup is stored as `unchecked`, never as healthy. One flaky service no longer drops the snapshot.
- Only known healthy deploy statuses count as healthy. Unknown statuses read as `render_unreadable`.
- `last_error` stores the exception type and HTTP status only.
- API key length is capped at 512 characters. Re-keying clears `synced_at`.
- Docs: Supabase docstring, Render docstring, `.claude/rules/api.md` infra flags, FEAT-129 tracker row.
- Tests added for cancellation re-raise, `mark_error` status suffix and unchecked mapping.

Suites: backend targeted 225 passed. Full backend shows the same database-dependent baseline failures as main. Frontend 495 passed, `tsc` clean. Ruff clean on changed files.

Deferred warnings:
- [ ] Duplicate test files for FEAT-179 should merge.
- [ ] Parameter-object refactor for `_infrastructure_findings` and the trip service.
- [ ] Route and service extraction, per-provider split in `_infrastructure_findings`.
- [ ] Render lists at most 10 services and Supabase 10 projects. The result flags truncation.
- [ ] Neither integration is connected in production. The check reports `unknown` until the owner adds keys on the Integrations page.
