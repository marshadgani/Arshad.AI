### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

**FEAT-123: Google Drive permissions audit, and fixes to FEAT-132 (Render deploy verdict)**

Eight agents ran: code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer, silent-failure-hunter, pr-test-analyzer. No Critical findings. The pipeline's own gate report was replaced: it reported every agent as PASS with no findings, which the independent review did not bear out.

**Verdict: WARN.**

Why this merge matters: FEAT-132 reached main on its own and carried the Drive wiring in `main.py` and `dashboard.py` without the Drive files. Main could not start and Render's deploy of main failed. This merge adds the missing Drive modules.

Fixed after the gate:
- Drive rate limit on the audit endpoint (10 per minute per user).
- Drive file links are relayed only when they are Google-hosted.
- A Drive reply that is not the documented file list is reported as `malformed_response` and no longer reads as "no risky files" or marks the integration broken.
- A file with a wrong-typed `id`, `name`, `modifiedTime` or link is dropped and counted as unreadable instead of crashing the route.
- A Drive 403 now asks for a reconnect, matching the Drive sync.
- The knowledge suggestions report `not_synced` for a connected but never-synced account and `cache_unreadable` for bad cache entries.
- The Knowledge search card shows a hint with a link to Integrations when it has no suggestions.
- Render: `deploy_id` must match `dep-[a-zA-Z0-9]{1,64}` (it goes into an upstream URL path). An empty metrics series is now missing data and forces "unknown".
- A FEAT-179 test that FEAT-132 broke by moving the infra lookup is fixed.
- Docs: `.claude/rules/api.md` entries for the Drive and Render endpoints, docstrings.
- 20 new tests. Backend targeted run 463 passed, frontend 549 passed, `tsc` clean, ruff clean.

Checked and false: the doc-writer's claim that no Drive test files exist. They exist (ten files) and pass.

Deferred warnings:
- [ ] Render verdict: a thin sample (2 log lines per window) can still produce "improvement", and a partial loss of log levels is not flagged (silent-failure R1, R2).
- [ ] Render shared key: every signed-in user can use the deployment Render key. Safe only while the login allowlist admits the owner. There is no owner role in the app.
- [ ] Drive: transient failures set the integration to `error`, which the dashboard then reports as a sync error.
- [ ] Drive: shared-drive files are not listed, with no flag.
- [ ] Duplicate HTTP-layer tests across two Drive test files, source-text guard tests, and a 7-module package for a small read-only feature.
- [ ] The dashboard hook exposes only the data array, not the state flags.
