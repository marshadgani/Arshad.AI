# Merge-to-Main Gate Report — FEAT-157 (corrected)

**Verdict: ⚠️ WARN — mergeable.** Zero FAIL, zero Critical remaining. All Critical/Warning findings from both gate rounds were fixed; remaining items are logged as follow-up tickets (FEAT-160, FEAT-161) rather than expanding this fix's scope.

## What this covers

FEAT-157: `POST /api/v1/integrations/{slug}/sync` returned a live HTTP 500 in production (`asyncpg.exceptions.DataError: can't subtract offset-naive and offset-aware datetimes`), confirmed via an end-to-end browser test logged in as the real user.

**Root cause (corrected mid-review):** the first gate round reviewed a fix based on a wrong hypothesis — that `Integration.last_synced_at` / `IntegrationOAuthToken.expires_at` were tz-naive Postgres columns. The code-reviewer agent traced the actual migration history and a direct `information_schema.columns` query against production confirmed both were already `TIMESTAMP WITH TIME ZONE`; only the SQLAlchemy model declaration had drifted. The real root cause: `DagTriggerQueue.requested_at` (written by every integration sync via `make_sync_via_dag()`) declares `TIMESTAMP(timezone=True)` but defaulted via the naive `datetime.utcnow`. The same pattern was found in `obsidian.py`, `conversation.py`, and `ingested.py` (11 occurrences total).

## Fix

- New `utcnow()` helper (`backend/src/models/base.py`) — aware UTC now, used everywhere the naive `datetime.utcnow` default/onupdate pattern appeared.
- `integration.py`: corrected model/DB drift on `last_synced_at`/`expires_at` (no migration needed, DB already matched); migration `n1k2l3m4a5b6` narrowed to the two columns confirmed genuinely naive in production (`integration_ingest_tokens.last_used_at`/`.revoked_at`), with a `lock_timeout` guard on both `upgrade()` and `downgrade()`.
- `calendar.py`/`github.py` ingestion date parsers: an all-day Google Calendar event's `start.date` (no offset) parsed to the same class of naive datetime, feeding straight into `occurred_at` — fixed to treat an offset-less parsed value as UTC.
- Test coverage: `test_integration_model_timestamp_columns.py` now calls each default/onupdate callable and asserts the produced value is tz-aware (not just a name match), including the previously-untested `ConversationSession.updated_at` onupdate path. New `test_ingestion_datetime_parsing.py` covers the parser fix.

## Gate agent results (8-agent panel, re-run after root-cause correction)

| Agent | Round 1 (wrong root cause) | Round 2 (corrected) |
|---|---|---|
| code-reviewer | Critical: migration wrong for 2 already-aware columns | Critical: `calendar.py` all-day-event naive datetime — **fixed**. Important: `TimestampedMixin` drift risk — spun off as **FEAT-160** |
| security-auditor | PASS (advisory only) | PASS, no blockers |
| debugger | Warning: deploy-ordering, lock_timeout | Confirmed root cause correct; lock_timeout on downgrade — **fixed**; deploy-verification reminder carried to post-push check |
| test-writer | WARN (declaration-only tests) | WARN → onupdate + behavioral-call gaps — **fixed** |
| refactorer | Suggestion: `revoked_at` consistency | Warning: `__qualname__` literal vs `utcnow.__qualname__`; Suggestion: extract helper — **both fixed** |
| doc-writer | Warning: `revoked_at` exclusion undocumented | Warning: model/DB drift invisible in `integration.py` — **fixed** with inline comments |
| silent-failure-hunter | Warning: pre-existing broad catch (unrelated) | Critical: `chat.py` SSE stream can silently truncate on a pre-yield DB error — **not in this diff's scope**, spun off as **FEAT-161** |
| pr-test-analyzer | WARN (implementation-detail tests) | WARN → onupdate + behavioral-call gaps — **fixed** (same as test-writer) |

## Follow-ups queued (not blocking this merge)

- **FEAT-160** — `TimestampedMixin` timezone drift risk (project-wide model convention question, not a live bug).
- **FEAT-161** — `chat.py`'s SSE stream can silently truncate instead of a clean 500 on a pre-yield DB error. This is a live risk independent of FEAT-157, flagged as worth prioritizing separately.

## Tests

`backend/tests/test_integration_model_timestamp_columns.py` (11 tests) and `backend/tests/test_ingestion_datetime_parsing.py` (6 tests) — all passing. Full backend suite: 704 passed, 7 pre-existing failures unrelated to this change (sandbox DB-connectivity limitations on OAuth-redirect tests, documented in prior sessions).

## Commits

- `8e24d27` — root-cause correction (utcnow helper, narrowed migration, model drift fix)
- `82bdb5a` — gate-feedback hardening (behavioral tests, downgrade lock_timeout, drift comments)
- `fa34cc7` — calendar/github ingestion parser fix (code-reviewer Critical finding)

## Next step after merge

Deployment Verification Protocol (CLAUDE.md §23): confirm `alembic upgrade head` actually ran on Render (watch for the `DATABASE_URL_DIRECT`/pooler issue), then confirm a live `POST /api/v1/integrations/google_calendar/sync` returns 200, not 500.
