### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

**FEAT-182: record every Claude Code subagent run on the AI Ecosystem page, plus the Google token refresh fix**

Eight agents ran: code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer, silent-failure-hunter, pr-test-analyzer. No Critical findings. Every security finding was fixed. The test-writer's one FAIL (coverage) was fixed.

**Verdict: WARN.** The only open items are documentation edits and follow-up features, listed below.

Changes:
- A `SubagentStop` hook (`.claude/hooks/subagent_usage_log.py`) posts each subagent run (name, model, tokens, duration, success) to `POST /api/v1/ai-ecosystem/log`. It runs async and always exits 0.
- `/log` moved to `ai_ecosystem_ingest.py`. It accepts a dedicated `X-Usage-Key`, or a normal user JWT as before.
- A new agent name is registered on first sight, so built-in subagents appear on the page.
- `google_token.py`: any refresh failure now raises `TokenUnavailableError`, so `/dashboard/events` and `/dashboard/briefing` fall back instead of returning 500.

Fixed after the gate:
- SEC-001: `/log` is rate limited (300 per minute) and auto-registration stops at 100 rows.
- SEC-002: `model` must match `^[A-Za-z0-9._:/-]+$`. Tokens are capped at 10,000,000 and duration at 7 days.
- SEC-003: a second key, `AGENT_USAGE_INGEST_KEY_NEXT`, is accepted so the key can rotate with no downtime.
- SEC-004: an unset server key and a wrong key now give the same 401. The real reason goes to the server log. The key is never logged.
- The 401 now carries `WWW-Authenticate`, and the duplicate error helper is gone (uses the shared `http_error`).
- `google_token.py` logs the original error. A 200 with a missing or malformed body is also mapped to `TokenUnavailableError`.
- The hook survives odd input: non-object JSON, non-string `agent_type`, mixed naive and aware timestamps, non-UTF-8 transcripts, unhashable message ids. An unreadable transcript still records the run.
- The hook writes failures to `.claude/hooks/.usage-hook.log` (gitignored), because an async hook's stderr is likely never seen. The hook timeout is 100s so two 45s attempts fit.
- Tests: 182 pass across the four related files. Full backend suite 1,666 pass. The 9 failures and 55 errors are the same set as on main (the sandbox has no database or Redis).
- Measured coverage: `usage_ingest.py` 100%, `ai_ecosystem_ingest.py` 100%, `google_token.py` 100% (was about 48%), hook 97%.
- The `ON CONFLICT (agent_name) DO NOTHING` statement is asserted by compiling it for Postgres. The unique constraint `uq_agent_registry_agent_name` exists in migration `i1f2g3h4a5b6`.

Residual risk, accepted for a single-user system:
- Anyone holding the ingest key can add usage rows and inflate the numbers. They cannot read data or change existing agents. Rotate with the `_NEXT` key.
- Auto-registered agents stay active so they show on the page. The 100-row cap is what bounds flooding.

Deferred warnings:
- [ ] `CLAUDE.md` §9 hooks table has no `SubagentStop` row, §6 env table lacks `AGENT_USAGE_INGEST_KEY`, `AGENT_USAGE_INGEST_KEY_NEXT`, `ARSHAD_USAGE_KEY`, `ARSHAD_USAGE_URL`, and `.claude/rules/api.md` needs a note that `/log` accepts the ingest key. These are the owner's instruction files, so they were not edited on a reviewer's request.
- [ ] A revoked Google token looks the same as "never linked" on the dashboard. A `needs_reauth` flag needs an API and frontend change, like Whoop and Shopify.
- [ ] After `invalid_grant`, every dashboard request retries the refresh (up to 10s). Marking the row as revoked would stop that.
- [ ] No real-Postgres integration test for the registry insert race.
- [ ] The production registry still shows `ai-engineer` as Opus. Main's agent file says Sonnet, so re-register it.
- [ ] Setup before the page shows data: set `AGENT_USAGE_INGEST_KEY` on Render and `ARSHAD_USAGE_KEY` in the Claude Code environment.
